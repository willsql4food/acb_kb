from typing import List, Optional, Tuple
from pyspark.sql import SparkSession, functions as F, Window
from delta.tables import DeltaTable
from functools import reduce   


class fnd_dim_utils:
    """
    Helper for maintaining SCD‑Type‑2 dimensions in the EDM
    
    """



    def __init__(self, spark: SparkSession):
        self.spark = spark

    # ════════════════════  METADATA HELPERS  ════════════════════
    # internal generic loader --------------------------------------------------
    def _get_cols(
        self,
        *,
        col_catalog_table_nm: str,
        table_nm: str,
        schema_nm: str,
        flag_col: str,         # e.g. "is_pk" / "is_md5_hash"
        flag_value: bool = True
    ) -> List[str]:
        """
        Fetch column names from catalog where `flag_col == flag_value`
        ordered by `column_order`.
        """
        df = (self.spark.table(col_catalog_table_nm)
                .filter(
                    (F.col("schema_name") == schema_nm)
                    & (F.col("table_name") == table_nm)
                    & (F.col(flag_col) == flag_value)
                    & (F.col("is_metadata") == False)
                )
                .select("column_order", "column_name")
                .orderBy("column_order")
                .collect())

        return [r["column_name"] for r in df]

    # public wrappers ----------------------------------------------------------
    def get_pk_cols(
        self,
        col_catalog_table_nm: str,
        table_nm: str,
        schema_nm: str = "es088740"
    ) -> List[str]:
        """Natural‑key columns (ordered)."""
        return self._get_cols(
            col_catalog_table_nm=col_catalog_table_nm,
            table_nm=table_nm,
            schema_nm=schema_nm,
            flag_col="is_pk"
        )

    def get_md5_cols(
        self,
        col_catalog_table_nm: str,
        table_nm: str,
        schema_nm: str = "es088740"
    ) -> List[str]:
        """Columns to include in MD5 hash (ordered)."""
        return self._get_cols(
            col_catalog_table_nm=col_catalog_table_nm,
            table_nm=table_nm,
            schema_nm=schema_nm,
            flag_col="is_md5_hash"
        )

    def get_pass_through_cols(
        self,
        col_catalog_table_nm: str,
        table_nm: str,
        schema_nm: str = "es088740"
    ) -> List[str]:
        """
        Columns that are **neither** PK nor MD5‑hashed – useful for
        auditing flags, load timestamps, etc.
        """
        df = (self.spark.table(col_catalog_table_nm)
                .filter(
                    (F.col("schema_name") == schema_nm)
                    & (F.col("table_name") == table_nm)
                    & (F.col("is_pk") == False)
                    & (F.col("is_md5_hash") == False)
                    & (F.col("is_metadata") == False)
                )
                .select("column_order", "column_name")
                .orderBy("column_order")
                .collect())

        return [r["column_name"] for r in df]

    # ════════════════════  CORE SCD METHODS  ════════════════════
    # ─────────────────────  1. upsert  ─────────────────────

    def upsert(
        self,
        *,
        stg_table: str,
        dim_table: str,
        natural_key_cols: List[str],
        business_date_col: str,
        hash_cols: List[str],
        pass_through_cols: Optional[List[str]] = None,
        end_of_time: Optional[str] = None
    ) -> Tuple[int, int]:
        """
        Incrementally merge *stg_table* into *dim_table* (SCD‑Type‑2).
        Returns (inserted_count, updated_count).
        """
        if pass_through_cols is None:
            pass_through_cols = []

        spark = self.spark
        exec_ts = spark.sql("SELECT current_timestamp()").first()[0]
        stg = spark.read.table(stg_table)

        # ─────────────── keep latest per PK ───────────────
        w_latest = (Window.partitionBy(*natural_key_cols)
                        .orderBy(F.col(business_date_col).desc()))
        stg = (stg.withColumn("_row", F.row_number().over(w_latest))
                .filter("_row = 1")
                .drop("_row"))

        # ─────────────── MD5 hash ───────────────
        md5_expr = F.md5(
            F.concat_ws("||",
                        *[F.coalesce(F.col(c).cast("string"), F.lit(""))
                        for c in hash_cols])
        )
        stg = stg.withColumn("md5_hash", md5_expr)

        # ─────────────── derive CURRENT / FUTURE flags ––––
        if spark.catalog.tableExists(dim_table):
            current_ref = (spark.read.table(dim_table)
                        .filter("is_current = true")
                        .select(*natural_key_cols,
                                F.col("start_date").alias("curr_start_date")))
        else:
            current_ref = spark.createDataFrame([], stg.select(*natural_key_cols)
                                                    .schema.add("curr_start_date", "date"))

        join_expr = reduce(
                lambda a, b: a & b,
                [F.col(f"s.{c}") == F.col(f"c.{c}") for c in natural_key_cols]
            )
            
        stg = (stg.alias("s")
                    .join(current_ref.alias("c"), join_expr, "left")
                    .select("s.*", F.col("c.curr_start_date"))
                    # derive helper columns
                    .withColumn("start_date", F.col(business_date_col).cast("date"))
                    .withColumn(
                        "is_future_record",
                        F.col(business_date_col) > F.current_date()
                    )
                    .withColumn(
                        "is_current",
                        (~F.col("is_future_record")) &
                        (F.col("curr_start_date").isNull() |
                        (F.col("start_date") >= F.col("curr_start_date")))
                    )
                    .withColumn(
                        "end_date",
                        F.when(F.col("is_future_record"),
                                F.lit(end_of_time).cast("date"))
                        .when(
                            (F.col("curr_start_date").isNotNull()) &
                            (F.col("start_date") < F.col("curr_start_date")),
                            F.expr("date_sub(curr_start_date, 1)")
                        )
                        .otherwise(F.lit(end_of_time).cast("date"))
                    )
                    .withColumn("created_at",  F.current_timestamp())
                    .withColumn("updated_at",  F.current_timestamp())
                    .drop("curr_start_date"))      # remove helper column

        # ───────────── 2. EXPIRE *current* rows that changed ─────────────
        if spark.catalog.tableExists(dim_table):
            dim   = DeltaTable.forName(spark, dim_table)
            eq_pk = " AND ".join([f"tgt.{c}=src.{c}" for c in natural_key_cols])

            # 2‑A current rows → expire  (src date must be “today or earlier”)
            expire_cond = (
                f"tgt.is_current = true AND {eq_pk} "
                "AND tgt.md5_hash <> src.md5_hash "
                "AND src.start_date >= tgt.start_date "      #  newer or same period
                "AND src.start_date <= current_date()"       # still not in the future
            )
            (dim.alias("tgt")
                .merge(stg.select(*natural_key_cols,
                                "md5_hash", "start_date").alias("src"),
                    expire_cond)
                .whenMatchedUpdate(set={
                    "end_date"   : F.expr("date_sub(src.start_date, 1)"),
                    "is_current" : F.lit(False),
                    "updated_at" : F.current_timestamp()
                })
                .execute())

            # 2‑B future rows → overwrite (unchanged)
            fut_cond = (
                f"tgt.is_future_record = true AND {eq_pk} "
                "AND tgt.start_date = src.start_date "
                "AND tgt.md5_hash <> src.md5_hash"
            )
            upd_map = {c: f"src.{c}"
                    for c in hash_cols + pass_through_cols
                    if c not in natural_key_cols}
            upd_map["md5_hash"]   = "src.md5_hash"
            upd_map["updated_at"] = F.current_timestamp()

            (dim.alias("tgt")
                .merge(stg.alias("src"), fut_cond)
                .whenMatchedUpdate(set=upd_map)
                .execute())

        # ───────────── 3. INSERT brand‑new / changed rows ─────────────
        active_dim = (
            spark.read.table(dim_table)
                .filter("is_current = true OR is_future_record = true")
            if spark.catalog.tableExists(dim_table)
            else spark.createDataFrame([], stg.schema)
        )

        to_insert = (stg.alias("s")
                    .join(
                        active_dim.select(*natural_key_cols,
                                        "md5_hash",
                                        "start_date").alias("d"),
                        on=([F.col(f"s.{c}") == F.col(f"d.{c}")
                            for c in natural_key_cols] +
                            [F.col("s.start_date") == F.col("d.start_date")] +
                            [F.col("s.md5_hash") == F.col("d.md5_hash")]),
                        how="left_anti"))

        insert_cols = (natural_key_cols +
                    [c for c in hash_cols if c not in natural_key_cols] +
                    pass_through_cols +
                    ["md5_hash", "start_date", "end_date",
                        "is_current", "is_future_record",
                        "created_at", "updated_at"])

        inserted_count = to_insert.count()
        if inserted_count:
            (to_insert.select(insert_cols)
                    .write.format("delta")
                    .mode("append")
                    .saveAsTable(dim_table))

        # ───────────── 4. METRICS ─────────────
        updated_count = (
            spark.read.table(dim_table)
                .filter((F.col("updated_at") >= exec_ts) &
                        (F.col("is_current") == False) &
                        (F.col("is_future_record") == False))
                .count()
        )

        print(f"Records inserted : {inserted_count}")
        print(f"Records updated  : {updated_count}")
        return inserted_count, updated_count




        # ─────────────────────  2. ROLL‑FORWARD  ─────────────────────
    def roll_forward(
        self,
        *,
        dim_table: str,
        natural_key_cols: List[str],
        effective_date_col: str = "start_date",
        end_date_col: str = "end_date",
        current_flag_col: str = "is_current",
        future_flag_col: str = "is_future_record"
    ) -> Tuple[int, int]:
        """
        Promote future‑dated rows whose start_date is today or earlier.
        Returns (promoted_count, expired_count)
        """
        spark = self.spark
        if not spark.catalog.tableExists(dim_table):
            return 0, 0

        delta_dim = DeltaTable.forName(spark, dim_table)
        ts_now = spark.sql("SELECT current_timestamp()").first()[0]

        ready = (spark.read.table(dim_table)
                 .filter(
                     f"{future_flag_col}=true "
                     f"AND {effective_date_col} <= current_date()")
                 .select(*natural_key_cols, effective_date_col)
                 .distinct())

        promoted = ready.count()
        if promoted == 0:
            return 0, 0

        eq_pk = " AND ".join([f"tgt.{c}=src.{c}" for c in natural_key_cols])

        # expire old‑current
        expire_cond = f"tgt.{current_flag_col}=true AND {eq_pk}"
        (delta_dim.alias("tgt")
                  .merge(ready.alias("src"), expire_cond)
                  .whenMatchedUpdate(set={
                      end_date_col      : F.expr(f"date_sub(src.{effective_date_col},1)"),
                      current_flag_col  : F.lit(False),
                      "updated_at"      : F.current_timestamp()
                  })
                  .execute())

        # promote future rows
        promote_cond = (
            f"tgt.{future_flag_col}=true "
            f"AND tgt.{effective_date_col} <= current_date() "
            f"AND {eq_pk}"
        )
        (delta_dim.alias("tgt")
                  .merge(ready.alias("src"), promote_cond)
                  .whenMatchedUpdate(set={
                      current_flag_col : F.lit(True),
                      future_flag_col  : F.lit(False),
                      "updated_at"     : F.current_timestamp()
                  })
                  .execute())

        expired = (
            spark.read.table(dim_table)
                 .filter((F.col("updated_at") >= ts_now) &
                         (F.col(current_flag_col) == False) &
                         (F.col(future_flag_col) == False))
                 .count()
        )

        print(f"Records promoted : {promoted}")
        print(f"Records expired  : {expired}")
        return promoted, expired

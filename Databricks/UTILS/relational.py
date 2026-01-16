from datetime import datetime
from pyspark.sql import DataFrame, functions as fn
from pyspark.sql.connect.session import SparkSession

# Build Lineage - enumerates the levels of a hierarchy and a concatenated lineage path
# Parameters:
#   src:        the source dataframe
#   spark:      the spark session from the caller
#   child:      the name of the field containing the child identifier
#   parent:     the name of the field containing the parent identifier
#   lineage:    the name of the field containing the element to be added to the lineage
#   delimiter:  the delimiter to be used between elements in the lineage
#               Optional - defaults to comma
#   debug:      When true, the procedure emits status messages, progress reports, etc.
#
# Returns a copy of the given dataframe with two fields added:
#   level:      depth of row in the hierarchy (0 is top / row(s) without parents)
#   lineage:    a delimited list the row and its ancestors
#
def buildLineage(src: DataFrame, 
                 spark: SparkSession, 
                 child: str, 
                 parent: str, 
                 lineage: str, 
                 delimiter = ",", 
                 debug = False):
    # Build names for temporary objects using given parameters and a timestamp
    now = datetime.now()
    vwSrc = f"vw_src_hierarchy_{child}_{parent}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}"
    vw = f"vw_hierarchy_{child}_{parent}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}"
    tbl = f"hive_metastore.default.tbl_hierarchy_{child}_{parent}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}"

    # Write the source data frame to a temporary view
    src.createOrReplaceTempView(vwSrc)

    # ========================================================================
    # We can only iterate over clean data - either:
    #   + top level (parent is null)
    #   + parent exists as a child in another record
    # ========================================================================
    # The parent is either null or exists as a child in another record
    spark.sql(f"select * from {vwSrc} s where s.{parent} is null or s.{parent} in (select {child} from {vwSrc})").createOrReplaceTempView(vw)
    
    # Get row count for progress reporting (if debug enabled)
    rcSrc = src.count()
    rcToDo = spark.sql(f'select count(*) from {vw}').collect()[0][0]

    if debug:
        print(f"Source has {rcSrc:,} rows. ({rcToDo:,} are valid)")
        
    # Create the temp table with the row(s) having no parent
    spark.sql(f"select *, 0 as level, {lineage} as lineage from {vw} where {parent} is null"
              ).writeTo(tbl).createOrReplace()
    # Get current row count
    rcDone = spark.sql(f'select count(*) from {tbl}').collect()[0][0]

    if debug:
        print(f"\tLevel 0:\t{rcDone:,} rows ({(rcDone / rcToDo * 100):3.2f}%)")

    # Orphaned children are possible (parent is supplied, but does not exist)
    # Return these in final result set with -1 level & NULL lineage...
    query = f"""select v.*, -1 as level, null as lineage 
                    from {vwSrc} v 
                    where v.{parent} is not null and v.{parent} not in (select {child} from {vwSrc})"""
    orphans = spark.sql(query)
    orphans.writeTo(tbl).append()
    rcToDo += orphans.count()

    if debug:
        print(f"\t+ Orphans:\t{orphans.count():,} rows")
    
    # Iterate until all rows have been added to the result 
    # With circuit breakers: max iterations and no growth in row count
    iter = 0
    rcDone = spark.sql(f'select count(*) from {tbl}').collect()[0][0]

    while rcToDo > rcDone:
        # Throw an assertion error if max recursion limit reached - this is a *failure*
        iter += 1
        assert iter < 100, f"Max recursion limit ({iter}) reached"
        
        # Get last row count so we can detect and escape infinite loop
        rcLast = rcDone

        rows = spark.sql(f"""select s.*
                        , p.level + 1 as level
                        , concat(p.lineage, '{delimiter}', s.{lineage}) as lineage
                from {vw} s 
                join {tbl} p on s.{parent} = p.{child}
                where not exists (select * from {tbl} where {child} = s.{child})"""
                )
        rows.writeTo(tbl).append()

        rcDone = spark.sql(f'select count(*) from {tbl}').collect()[0][0]
        
        if debug:
            print(f"\tLevel {iter}:\t{rcDone:,} rows ({(rcDone / rcToDo * 100):3.2f}%)")

        # If no rows were added this should be the end, but if rows remain a loop has been detected
        if rcLast >= rcDone:
            rows = spark.sql(f"""select *, -2 as level, NULL as lineage
                    from {vw} 
                    where {child} not in (select {child} from {tbl})"""
                    )
            print(f"Infinite loop detected - {rows.count()} rows added with level = -2.")
            rows.writeTo(tbl).append()
            break

    # Collect the data and create a new dataframe with it
    result = spark.createDataFrame(
        spark.sql(f"select * from {tbl}").collect(), 
        spark.read.table(tbl).schema
        )

    # Clean up temporary objects
    spark.sql(f"drop table {tbl}")
    spark.sql(f"drop view {vw}")

    # Send the result to the caller
    return result
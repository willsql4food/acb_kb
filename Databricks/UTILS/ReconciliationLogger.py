# reconciliation_logger.py

import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional, Dict, Any

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, 
    DoubleType, TimestampType, BooleanType, LongType
)


class ReconciliationLogger:
    """
    Logger for reconciliation runs and events.

    One instance per (source_system, target_system, source_table, target_table) per job run.
    """

    def __init__(
        self,
        spark: SparkSession,
        source_system: str,
        target_system: str,
        source_table: str,
        target_table: str,
        job_run_id: Optional[str] = None,
        run_mode: str = "MANUAL",              # 'MANUAL', 'SCHEDULED', 'TRIGGERED'
        notes: Optional[str] = None,
        runs_table: str = "metadata_dev.audit.reconciliation_runs",
        events_table: str = "metadata_dev.audit.reconciliation_events",
        initiated_by: Optional[str] = None,    # if None, DB default current_user() is used
    ):
        self.spark = spark
        self.runs_table = runs_table
        self.events_table = events_table

        self.run_id = str(uuid.uuid4())
        self.run_start_ts = datetime.now(timezone.utc)
        self.run_end_ts: Optional[datetime] = None

        self.source_system = source_system
        self.target_system = target_system
        self.source_table = source_table
        self.target_table = target_table
        self.job_run_id = job_run_id
        self.run_mode = run_mode
        self.notes = notes
        self.initiated_by = initiated_by

        # Counters
        self.total_rules_executed = 0
        self.rules_passed = 0
        self.rules_failed = 0
        self.rules_warning = 0
        self.rules_error = 0
        self.rules_skipped = 0

        self._closed = False

    # ------------ internal helpers ------------ #

    def _update_counters_for_status(self, status: str):
        """Update run-level counters based on rule status."""
        self.total_rules_executed += 1

        s = (status or "").upper()
        if s == "PASS":
            self.rules_passed += 1
        elif s == "FAIL":
            self.rules_failed += 1
        elif s == "WARN":
            self.rules_warning += 1
        elif s == "ERROR":
            self.rules_error += 1
        elif s == "SKIP":
            self.rules_skipped += 1

    def _get_event_schema(self):
        """Return the schema for reconciliation_events table."""
        return StructType([
            StructField("run_id", StringType(), False),
            StructField("rule_name", StringType(), False),
            StructField("rule_id", LongType(), True),
            StructField("exception_id", LongType(), True),
            StructField("scope", StringType(), False),
            StructField("column_name", StringType(), True),
            StructField("metric_name", StringType(), False),
            StructField("severity", StringType(), False),
            StructField("tolerance_type", StringType(), True),
            StructField("tolerance_value", DoubleType(), True),
            StructField("source_value", StringType(), True),
            StructField("target_value", StringType(), True),
            StructField("difference", DoubleType(), True),
            StructField("status", StringType(), False),
            StructField("error_message", StringType(), True),
            StructField("execution_start_ts", TimestampType(), False),
            StructField("execution_end_ts", TimestampType(), False),
            StructField("execution_time_ms", LongType(), True),
            StructField("was_overridden", BooleanType(), False),
            StructField("override_details", StringType(), True),
        ])

    def _get_run_schema(self):
        """Return the schema for reconciliation_runs table."""
        return StructType([
            StructField("run_id", StringType(), False),
            StructField("job_run_id", StringType(), True),
            StructField("source_system", StringType(), False),
            StructField("target_system", StringType(), False),
            StructField("source_table", StringType(), False),
            StructField("target_table", StringType(), False),
            StructField("total_rules_executed", IntegerType(), False),
            StructField("rules_passed", IntegerType(), False),
            StructField("rules_failed", IntegerType(), False),
            StructField("rules_warning", IntegerType(), False),
            StructField("rules_error", IntegerType(), False),
            StructField("rules_skipped", IntegerType(), False),
            StructField("run_status", StringType(), False),
            StructField("run_start_ts", TimestampType(), False),
            StructField("run_end_ts", TimestampType(), False),
            StructField("run_mode", StringType(), False),
            StructField("notes", StringType(), True),
            StructField("initiated_by", StringType(), True),
        ])

    def _insert_event_row(self, data: Dict[str, Any]):
        """
        Insert a single reconciliation event into metadata_dev.audit.reconciliation_events.

        We avoid specifying event_id (IDENTITY) or created_ts (default).
        """
        schema = self._get_event_schema()
        df = self.spark.createDataFrame([data], schema=schema)
        tmp_view = "_tmp_reconciliation_event"

        df.createOrReplaceTempView(tmp_view)

        self.spark.sql(f"""
            INSERT INTO {self.events_table} (
                run_id,
                rule_name,
                rule_id,
                exception_id,
                scope,
                column_name,
                metric_name,
                severity,
                tolerance_type,
                tolerance_value,
                source_value,
                target_value,
                difference,
                status,
                error_message,
                execution_start_ts,
                execution_end_ts,
                execution_time_ms,
                was_overridden,
                override_details
            )
            SELECT
                run_id,
                rule_name,
                rule_id,
                exception_id,
                scope,
                column_name,
                metric_name,
                severity,
                tolerance_type,
                tolerance_value,
                source_value,
                target_value,
                difference,
                status,
                error_message,
                execution_start_ts,
                execution_end_ts,
                execution_time_ms,
                was_overridden,
                override_details
            FROM {tmp_view}
        """)

        self.spark.catalog.dropTempView(tmp_view)

    def _insert_run_row(self, run_status: str, notes: Optional[str]):
        """
        Insert a single reconciliation run into metadata_dev.audit.reconciliation_runs.

        We do NOT specify run_timestamp or created_ts to let defaults apply.
        """
        data = {
            "run_id": self.run_id,
            "job_run_id": self.job_run_id,
            "source_system": self.source_system,
            "target_system": self.target_system,
            "source_table": self.source_table,
            "target_table": self.target_table,
            "total_rules_executed": int(self.total_rules_executed),
            "rules_passed": int(self.rules_passed),
            "rules_failed": int(self.rules_failed),
            "rules_warning": int(self.rules_warning),
            "rules_error": int(self.rules_error),
            "rules_skipped": int(self.rules_skipped),
            "run_status": run_status,
            "run_start_ts": self.run_start_ts,
            "run_end_ts": self.run_end_ts,
            "run_mode": self.run_mode,
            "notes": notes if notes is not None else self.notes,
            "initiated_by": self.initiated_by,
        }

        schema = self._get_run_schema()
        df = self.spark.createDataFrame([data], schema=schema)
        tmp_view = "_tmp_reconciliation_run"

        df.createOrReplaceTempView(tmp_view)

        self.spark.sql(f"""
            INSERT INTO {self.runs_table} (
                run_id,
                job_run_id,
                source_system,
                target_system,
                source_table,
                target_table,
                total_rules_executed,
                rules_passed,
                rules_failed,
                rules_warning,
                rules_error,
                rules_skipped,
                run_status,
                run_start_ts,
                run_end_ts,
                initiated_by,
                run_mode,
                notes
            )
            SELECT
                run_id,
                job_run_id,
                source_system,
                target_system,
                source_table,
                target_table,
                total_rules_executed,
                rules_passed,
                rules_failed,
                rules_warning,
                rules_error,
                rules_skipped,
                run_status,
                run_start_ts,
                run_end_ts,
                initiated_by,
                run_mode,
                notes
            FROM {tmp_view}
        """)

        self.spark.catalog.dropTempView(tmp_view)

    # ------------ public API ------------ #

    @property
    def id(self) -> str:
        """Return the run_id."""
        return self.run_id

    @contextmanager
    def log_rule(
        self,
        rule_name: str,
        metric_name: str,
        scope: str = "TABLE",             # 'TABLE' or 'COLUMN'
        severity: str = "ERROR",          # 'ERROR', 'WARN', 'INFO'
        column_name: Optional[str] = None,
        rule_id: Optional[int] = None,
        exception_id: Optional[int] = None,
        tolerance_type: Optional[str] = None,   # 'ABS', 'NONE', etc.
        tolerance_value: Optional[float] = None,
        was_overridden: bool = False,
        override_details: Optional[str] = None,
    ):
        """
        Context manager to log a single rule execution.

        Usage:
            with logger.log_rule(...) as rule:
                # compute metrics here
                rule.set_values(...)

        If an exception occurs, an 'ERROR' event is logged and the exception is re-raised.
        """

        start_ts = datetime.now(timezone.utc)

        class RuleContext:
            def __init__(self):
                self._values: Dict[str, Any] = {
                    "source_value": None,
                    "target_value": None,
                    "difference": None,
                    "status": "PASS",        # default, can be overridden
                    "error_message": None,
                }

            def set_values(
                self,
                *,
                source_value: Optional[str] = None,
                target_value: Optional[str] = None,
                difference: Optional[float] = None,
                status: str = "PASS",
                error_message: Optional[str] = None,
            ):
                """
                Set final metric values and status for this rule.
                Numeric values can also be passed as strings in source_value/target_value.
                """
                self._values.update(
                    dict(
                        source_value=source_value,
                        target_value=target_value,
                        difference=difference,
                        status=status,
                        error_message=error_message,
                    )
                )

        ctx = RuleContext()
        exc_type = exc_val = exc_tb = None

        try:
            yield ctx
        except Exception as e:
            # Log as ERROR and re-raise
            exc_type, exc_val, exc_tb = e.__class__, e, e.__traceback__
            ctx._values["status"] = "ERROR"
            ctx._values["error_message"] = str(e)
        finally:
            end_ts = datetime.now(timezone.utc)
            duration_ms = int((end_ts - start_ts).total_seconds() * 1000)

            status = ctx._values["status"] or "PASS"

            event_data = {
                "run_id": self.run_id,
                "rule_name": rule_name,
                "rule_id": rule_id,
                "exception_id": exception_id,
                "scope": scope,
                "column_name": column_name,
                "metric_name": metric_name,
                "severity": severity,
                "tolerance_type": tolerance_type,
                "tolerance_value": tolerance_value,
                "source_value": ctx._values["source_value"],
                "target_value": ctx._values["target_value"],
                "difference": ctx._values["difference"],
                "status": status,
                "error_message": ctx._values["error_message"],
                "execution_start_ts": start_ts,
                "execution_end_ts": end_ts,
                "execution_time_ms": duration_ms,
                "was_overridden": bool(was_overridden),
                "override_details": override_details,
            }

            self._update_counters_for_status(status)
            self._insert_event_row(event_data)

            if exc_type is not None:
                raise exc_val

    def end_run(self, run_status: Optional[str] = None, notes: Optional[str] = None):
        """
        Close the run and write the reconciliation_runs row.

        Default run_status if not provided:
            * 'SUCCESS' if no FAILED/ERROR rules
            * 'FAILED' otherwise
        """
        if self._closed:
            return

        self.run_end_ts = datetime.now(timezone.utc)

        if run_status is None:
            if self.rules_failed == 0 and self.rules_error == 0:
                run_status = "SUCCESS"
            else:
                run_status = "FAILED"

        self._insert_run_row(run_status=run_status, notes=notes)
        self._closed = True
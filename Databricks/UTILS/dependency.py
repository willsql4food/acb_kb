from pyspark.sql import DataFrame, functions as fn
from pyspark.sql.connect.session import SparkSession
from UTILS import environment
from datetime import datetime
import time

def subTime(
    t: float, 
    unit: str) -> float:
    """
    Subtracts a time interval from the current time.

    Parameters
    --------------------
    t : float
        The time interval to subtract.
    unit : str
        The unit of the time interval, such as h, min, sec, etc.
    
    Returns
    --------------------
    float
        The resulting time (seconds since epoch date).
    """

    # Acceptable units and their scales
    con = [
        {'unit': 'h', 'scale': 3600}, {'unit': 'hr', 'scale': 3600}, {'unit': 'hour', 'scale': 3600},
        {'unit': 'm', 'scale': 60}, {'unit': 'min', 'scale': 60}, {'unit': 'minute', 'scale': 60},
        {'unit': 's', 'scale': 1}, {'unit': 'sec', 'scale': 1}, {'unit': 'second', 'scale': 1}
        ]

    # Try scaling the given interval according to the unit specifier
    try:
        interval = t * [c['scale'] for c in con if c['unit'] == unit][0]

    # If the unit is not recognized, raise an exception with the acceptable units
    except IndexError:
        raise Exception("Invalid unit.  Please use one of the following: " + str([c['unit'] for c in con]) + ".")

    # Send the caller the current time minus the scaled interval
    return time.time() - interval

def setProcessState(
    processName: str,
    stateName: str,
    spark: SparkSession
):
    """
    Adds a row to the control.process_execution_state table to record the current state of the process.

    Parameters
    --------------------
    processName : str
        The name of the process.
    stateName : str
        The name of the state.
    spark : SparkSession
        The caller's SparkSession, passed so this function can execute in the same context.
    """

    # Verify parameters were passed
    assert processName, "processName is required"
    assert stateName, "stateName is required"

    # Get environment (dev, qa, etc.)
    env = environment.currentEnv(spark)

    # Verify process and state exist
    r = spark.sql(f"select id from metadata_{env}.control.process where name = '{processName}'")
    assert r.count() > 0, f"No such process '{processName}'"
    pid = r.collect()[0][0]

    r = spark.sql(f"select id from metadata_{env}.control.execution_state where name = '{stateName}'")
    assert r.count() > 0, f"No such execution state '{stateName}'"
    sid = r.collect()[0][0]

    # Insert the process execution state
    spark.sql(f"insert into metadata_{env}.control.process_execution_state (process_id, state_id) values ({pid}, {sid})")
    r = spark.sql(f"select max(state_change_time) from metadata_{env}.control.process_execution_state where process_id = {pid} and state_id = {sid}")
    if r.count() > 0:
        ts = r.collect()[0][0]

    print(f"Process: {processName} ({pid}) changed to execution state {stateName} ({sid}) at {ts}")

# Shortcut functions for calling setProcessState with common execution states:
def startProcess(processName: str, spark: SparkSession):
    """
    Shortcut for setProcessState(processName, 'Started', spark)
    """
    setProcessState(processName, 'Started', spark)

def failProcess(processName: str, spark: SparkSession):
    """
    Shortcut for setProcessState(processName, 'Failed', spark)
    """
    setProcessState(processName, 'Failed', spark)

def succeedProcess(processName: str, spark: SparkSession):
    """
    Shortcut for setProcessState(processName, 'Succeeded', spark)
    """
    setProcessState(processName, 'Succeeded', spark)

def get_cat_sch_name(fqdn):
    """
    If possible, cuts the fully-qualified domain name of the table into catalog, schema and table name

    Parameters
    --------------------
    fqdn : str
        The fully-qualified name of the table.

    Returns
    --------------------
    dict
        The name components in the form {"cat": catalog, "sch": schema, "tbl": table_name}.
    """

    l = fqdn.split('.')
    if len(l) == 3:
        return {"cat": l[0], "sch": l[1], "tbl": l[2]}
    else:
        return {"cat": '', "sch": '', "tbl": fqdn}

def add_table_hierarchy(
    target_table,
    source_tables,
    spark
):
    """
    Adds a row to control.table_hierarchy for each dependency .

    Parameters
    --------------------
    source_table : str
        The fully qualified name of the target table.
    source_table : list
        The fully qualified name of each of the tables the target depends on.
    spark : SparkSession
        The caller's SparkSession, passed so this function can execute in the same context.
    """

    # Get the operating environment
    env = environment.currentEnv(spark)

    # Cut the target_table into catalog, schema and table_name if possible
    tgt = get_cat_sch_name(target_table)

    for st in source_tables:
        src = get_cat_sch_name(st)
        sql = f"""insert into metadata_{env}.control.table_hierarchy (
            target_catalog, target_schema, target_table, source_catalog, source_schema, source_table, is_active, update_date)
            select '{tgt["cat"]}', '{tgt["sch"]}', '{tgt["tbl"]}', '{src["cat"]}', '{src["sch"]}', '{src["tbl"]}', 1, '{datetime.now()}'
            where not exists (  select * 
                                from metadata_{env}.control.table_hierarchy 
                                where target_catalog = '{tgt["cat"]}' and target_schema = '{tgt["sch"]}' and target_table = '{tgt["tbl"]}'
                                    and source_catalog = '{src["cat"]}' and source_schema = '{src["sch"]}' and source_table = '{src["tbl"]}'
                                )
        """
        spark.sql(sql)

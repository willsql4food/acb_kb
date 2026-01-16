from pyspark.sql.connect.session import SparkSession
from dbruntime.databricks_repl_context import get_context

def whereAmI(
    spark: SparkSession
):
    """
    Determines the working environment

    Parameters
    --------------------
    spark : SparkSession
        The caller's SparkSession, passed so this function can execute in the same context.
    
    Returns
    --------------------
    dict
        Key / value pairs: url, id, name, env
    """
    
    # See if this has already been done; if so, just read it out of the spark.conf
    ctxt = get_context()
    id = ctxt.workspaceId
    url = ctxt.apiUrl

    # name: query the system table for the name correpsonding to the id
    name = spark.sql(f"select workspace_name from system.access.workspaces_latest where workspace_id = {id}").collect()[0][0]

    # env: the environment is spelled out between the first two dashes
    env = name.split('-')[1]

    # Bundle it all up and return to the user
    ret = {"url": url, "id": id, "name": name, "env": env}
    return ret

def currentEnv(
    spark: SparkSession
):
    """
    Determines the working environment

    Parameters
    --------------------
    spark : SparkSession
        The caller's SparkSession, passed so this function can execute in the same context.
    
    Returns
    --------------------
    string : environment value (typically dev, qa, prod, or sbx)
    """
    return whereAmI(spark)['env']

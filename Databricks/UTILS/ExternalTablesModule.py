# Databricks notebook source
from pyspark.sql.functions import col
from pyspark.sql.types import TimestampType, DateType, FloatType, DoubleType, LongType
from datetime import datetime 

# COMMAND ----------

# MAGIC %md
# MAGIC ### Creating widgets to consume parameters

# COMMAND ----------

# Create a text widget for the Parquet file path
dbutils.widgets.text("file_path", "", "Parquet File Path")
dbutils.widgets.text("sql_table_name", "", "SQL Table Name")
dbutils.widgets.text("sql_database_name", "", "SQL Database Name")
dbutils.widgets.text("sql_schema_name", "", "SQL Schema Name")
dbutils.widgets.text("external_data_source", "", "External Data Source Name")   #AzureBlobStorageDatalakeDev
dbutils.widgets.dropdown("save_parquet", "FALSE", ["TRUE", "FALSE"])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Consuming parameters from widgets

# COMMAND ----------

file_path = dbutils.widgets.get("file_path")  # Path of the Parquet file
sql_table_name = dbutils.widgets.get("sql_table_name")  # Desired SQL table name
sql_database_name = dbutils.widgets.get("sql_database_name")
sql_schema_name = dbutils.widgets.get("sql_schema_name")
save_parquet = dbutils.widgets.get("save_parquet")
external_data_source = dbutils.widgets.get("external_data_source")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parse file path to a standard format independently of the file type (CSV/Parquet)

# COMMAND ----------

base_path = '/mnt/datalake'
extFileFormat = 'ParquetFormat'
if not file_path.lower().startswith(base_path):
    file_path = base_path.rstrip('/') + '/' + file_path.lstrip('/')
else:
    file_path = '/' + file_path.lstrip('/')

# COMMAND ----------

file_path

# COMMAND ----------

def convertLong(df, file_path):

    # Inspect each column and cast only if the type is datetime, timestamp, or float
    for field in df.schema.fields:
        if isinstance(field.dataType, (LongType)):  # removing TimestampType, DateType, FloatType, DoubleType, LongType seem to work
            df = df.withColumn(field.name, col(f"`{field.name}`").cast("string"))
    parquet_path = file_path.split('files')[0] + f'latestFile3.parquet'
    # df = df.coalesce(1)
    df.write.mode("overwrite").option("compression", "snappy").parquet(parquet_path)
    df = spark.read.format('parquet').option('mergeSchema','true').option('mode', 'FAILFAST').load(parquet_path)
    
    return df, parquet_path

# COMMAND ----------

if not file_path.endswith('.parquet'):
    print('parquet folder')
    if not file_path.endswith('/'):
        parquet_path = file_path + '/'
    df = spark.read.format('parquet').option('mergeSchema','true').option('mode', 'FAILFAST').load(parquet_path)
    print(df.count())
    if save_parquet == "TRUE": 
        df, parquet_path = convertLong(df, file_path)
elif file_path.endswith('.parquet'):
    print('parquet')
    parquet_path = file_path
    df = spark.read.format('parquet').option('mergeSchema','true').option('mode', 'FAILFAST').load(parquet_path)
    print(df.count())

# COMMAND ----------

table_path = parquet_path.removeprefix(base_path)
if '*' in table_path:
    table_path = parquet_path.split('*')[0]

# COMMAND ----------

# MAGIC %md
# MAGIC ### Dynamically generating the DDL query to create the external table 

# COMMAND ----------

# Function to map Spark data types to SQL Server data types
def spark_to_sql_type(spark_type):
    # Check if the type is a decimal with specified precision and scale
    if spark_type.lower().startswith("decimal("):
        # Return the type as DECIMAL with the same precision and scale
        return spark_type.upper()
    mapping = {
        "integer": "INT",
        "int": "INT",
        "long": "BIGINT",
        "double": "FLOAT",
        "string": "NVARCHAR(4000)", 
        "boolean": "BIT",
        "date": "DATE",
        "timestamp": "DATETIME",
        "float": "REAL" 
    }
    return mapping.get(spark_type.lower(), "NVARCHAR(4000)")  



# Generate DDL statement for external table
ddl_columns = []
for field in df.schema.fields:     
    # print(field.dataType.simpleString(), '  --->   ' , spark_to_sql_type(field.dataType.simpleString()))
    sql_type = spark_to_sql_type(field.dataType.simpleString())
    ddl_columns.append(f"[{field.name}] {sql_type}")
    
new_line = ",\n        "
# Formatting the CREATE EXTERNAL TABLE statement
ddl_statement = f"""
IF EXISTS (SELECT * FROM sys.external_tables WHERE name = N'{sql_table_name}')
BEGIN
    DROP EXTERNAL TABLE [{sql_database_name}].[{sql_schema_name}].[{sql_table_name}];
END

CREATE EXTERNAL TABLE [{sql_database_name}].[{sql_schema_name}].[{sql_table_name}] (
    {new_line.join(ddl_columns)}
)
WITH (
    LOCATION = '{table_path}',  -- location of parquet file
    DATA_SOURCE =  {external_data_source},  --external data source name AzureBlobStorageDatalakeDev
    FILE_FORMAT = {extFileFormat},  -- SQL external file format 
    REJECT_TYPE = VALUE,  -- VALUE or PERCENTAGE
    REJECT_VALUE = 1000  -- reject limit
);
"""


# Output the DDL statement
print(ddl_statement)

# COMMAND ----------

  dbutils.notebook.exit(ddl_statement)

# COMMAND ----------



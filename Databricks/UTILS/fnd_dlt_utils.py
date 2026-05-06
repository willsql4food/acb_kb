from databricks.sdk.runtime import *

import enum
import dlt
import pyspark.sql.functions as F
from pyspark.sql.functions import col

import json

class dltType(enum.Enum):
    bronze = 1
    silver = 2

class dltWatermark:
    def __init__(self, source, dltType):
        self.dltType = dltType
        self.source = source

    def getWatermark(self, watermark):
        if self.dltType == dltType.bronze:
            q = f"SELECT autoloaderPath, autoloaderRoot, autoloaderFileType, bronzeTableName, schemaLocation FROM {watermark} WHERE dltPipeline = '{self.source}' AND bronzeIsActive = True;"
        elif self.dltType == dltType.silver:
            q = f"SELECT bronzeCatalogName, bronzeSchemaName, bronzeTableName, silverTableName, primaryKey, sequenceKey, applyDelete, exceptColumnList FROM {watermark} WHERE dltPipeline = '{self.source}' AND silverIsActive = True;"

        df = spark.sql(q)

        return json.loads(df.toPandas().to_json(orient='records'))

class dltUtils:
    def __init__(self, spark, source, dltType):
        self.spark = spark
        self.source = source
        self.dltType = dltType

    def createDLT(self, paramList):
        if self.dltType == dltType.bronze:
            autoloaderPath = paramList["autoloaderPath"]
            autoloaderRoot = paramList["autoloaderRoot"]
            autoloaderFileType = paramList["autoloaderFileType"]
            bronzeTableName = paramList["bronzeTableName"]
            schemaLocation = paramList["schemaLocation"]

            self.createBronzeTable(bronzeTableName, autoloaderPath, autoloaderRoot, autoloaderFileType, schemaLocation)
            
        elif self.dltType == dltType.silver:
            bronzeTable = f"{paramList['bronzeCatalogName']}.{paramList['bronzeSchemaName']}.{paramList['bronzeTableName']}"
            view = f"vw{paramList['bronzeTableName']}_br"
            silverTableName = paramList['silverTableName']
            primaryKeyStr = paramList['primaryKey']
            sequenceKey = paramList['sequenceKey']
            applyDelete = paramList['applyDelete']
            exceptColumnListStr = paramList['exceptColumnList']

            primaryKeyStr = primaryKeyStr.replace(" ", "")
            primaryKey = []
            primaryKey = primaryKeyStr.split(",")

            
            exceptColumnList = []
            if exceptColumnListStr is not None and exceptColumnListStr != "":
                exceptColumnListStr = exceptColumnListStr.replace(" ", "")
                exceptColumnList = exceptColumnListStr.split(",")

            #exceptColumnList.append("_rescued_data")

            self.createSilverTable(bronzeTable, view, silverTableName, primaryKey, sequenceKey, applyDelete, exceptColumnList)

    def createBronzeTable(self, bronzeTableName, autoloaderPath, autoloaderRoot, autoloaderFileType, schemaLocation):
    
        @dlt.table(
            name = f"{bronzeTableName}",
            comment = f"bronze {bronzeTableName} from {self.source}")

        def t():
            return(spark.readStream
                .format("cloudFiles")
                .option(f"cloudFiles.format",f"{autoloaderFileType}")
                .option("cloudFiles.inferColumnTypes",True)
                .option("cloudFiles.schemaLocation",f"{schemaLocation}/{autoloaderRoot}")
                .load(f"{autoloaderPath}/{autoloaderRoot}")
                .select(F.current_timestamp().alias("process_timestamp"),
                        col("_metadata.file_name").alias("input_file_name"),
                        "*"
                        )
                )

    def createSilverTable(self, tableName, view, silverTableName, primaryKey, sequenceKey, applyDelete, exceptColumnList):
        
        @dlt.view(
            name = f"{view}",
            comment = f"view of bronze {tableName} from {self.source}")
        def t():
            return self.spark.readStream.table(f"{tableName}")
        
        dlt.create_streaming_table(
            name = f"{silverTableName}",
            comment = f"silver {silverTableName} from {self.source}"
        )

        if applyDelete:
            dlt.apply_changes(
                target = f"{silverTableName}",
                source = f"{view}",
                keys = primaryKey,
                sequence_by = F.col(f"{sequenceKey}"),
                apply_as_deletes = applyDelete,
                except_column_list = exceptColumnList)
        else:
            dlt.apply_changes(
                target = f"{silverTableName}",
                source = f"{view}",
                keys = primaryKey,
                sequence_by = F.col(f"{sequenceKey}"),
                except_column_list = exceptColumnList)

        
    
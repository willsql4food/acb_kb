from databricks.sdk.runtime import *

import enum
import pyspark.sql.functions as F
from uuid import uuid4
from datetime import datetime

class hashType(enum.Enum):
    XXHASH64 = 1
    HASH = 2
    SHA2 = 3
    SHA = 4
    MD5 = 5
    CRC32 = 6

class fndCdcUtils:
    def __init__(self, table, primaryKey, hashKey, dateKey, batchKey):
        self.guid = uuid4()
        self.cdcTable = table
        self.cdcPrimaryKey = primaryKey
        self.cdcHashKey = hashKey
        self.cdcDateKey = dateKey
        self.cdcBatchKey = batchKey

    ## generates a hash across all columns in the dataframe
    def generateRowHash(self, df, hashType):
        if hashType == hashType.XXHASH64:
            return F.xxhash64(F.col("*"))
        elif hashType == hashType.HASH:
            return F.hash(F.col("*"))
        elif hashType == hashType.SHA2:
            return F.sha2(F.concat_ws("", F.col("*")), 256)
        elif hashType == hashType.SHA: 
            return F.sha(F.concat_ws("", F.col("*")))
        elif hashType == hashType.MD5:
            return F.sha(F.concat_ws("", F.col("*")))
        elif hashType == hashType.CRC32:
            return F.crc32(F.concat_ws("", F.col("*")))

    # Check to see if table exists.  Supports fully qualified table name or just the table name
    # also validates that the column names match the expected columns
    def checkCdcTable(self):
        r = spark.catalog.tableExists(self.cdcTable)

        if r == True:
            cols = spark.catalog.listColumns(self.cdcTable)
            
            c = []                      
            
            for col in cols:
                c.append(col.name)

            ls = self.cdcPrimaryKey.replace(', ', ',').split(',')
            ls.append(self.cdcBatchKey)
            ls.append(self.cdcDateKey)
            ls.append(self.cdcHashKey)
            ls.append("operation")

            if set(c) != set(ls):
                raise Exception(f"The table {self.cdcTable} does not match the expected columns.")
                r = False
        
        return r

    ## create a reference table for cdc logging
    def createCdcTable(self, view, overwrite = False):
        if overwrite == True:
            overwriteSql = "CREATE OR REPLACE TABLE "
        elif overwrite == False:
            overwriteSql = "CREATE TABLE IF NOT EXISTS "

        sql = (f"{overwriteSql}{self.cdcTable} AS SELECT {self.cdcPrimaryKey}, {self.cdcBatchKey}, {self.cdcDateKey}, {self.cdcHashKey}, 'I' AS operation FROM {view} WHERE 1 = 2")
        
        spark.sql(sql)

    # merge the cdc table with the source table
    def mergeCdcTable(self, view, markDelete = False):
        sql = f"MERGE INTO {self.cdcTable} t USING (SELECT {self.cdcPrimaryKey}, {self.cdcBatchKey}, {self.cdcDateKey}, {self.cdcHashKey} FROM {view}) s {self.strSplitJoinKey(self.cdcPrimaryKey,'s','t')} WHEN MATCHED AND t.{self.cdcHashKey} <> s.{self.cdcHashKey} THEN UPDATE SET t.{self.cdcBatchKey} = s.{self.cdcBatchKey}, t.{self.cdcDateKey} = s.{self.cdcDateKey}, t.{self.cdcHashKey} = s.{self.cdcHashKey}, t.operation = 'U' WHEN NOT MATCHED BY TARGET THEN INSERT ({self.cdcPrimaryKey}, {self.cdcBatchKey}, {self.cdcDateKey}, {self.cdcHashKey}, operation) VALUES ({self.cdcPrimaryKey}, {self.cdcBatchKey}, {self.cdcDateKey}, {self.cdcHashKey}, 'I')"

        if markDelete == True:
            sql = sql + f" WHEN NOT MATCHED BY SOURCE THEN UPDATE SET t.{self.cdcBatchKey} = '{self.guid}', t.{self.cdcDateKey} = '{datetime.now()}', {self.cdcHashKey} = 0, t.operation = 'D'"

        #return(sql)
        spark.sql(sql)


    ## generates a JOIN string for one or more keys in a comma delimited string
    def strSplitJoinKey(self, primaryKey, sourceAlias = 's', targetAlias = 't'):
        pkArray = primaryKey.replace(', ', ',').split(',')
        jn = 'ON '
        for p in pkArray:
            jn = jn + sourceAlias + '.' + p + ' = ' + targetAlias + '.' + p + ' AND '

        jn = jn + '1 = 1'
        return jn


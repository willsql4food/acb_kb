# Databricks notebook source
# DBTITLE 1,Fully Qualified Table Name
def getFQN(table, catalog = "default", schema = "default"):
    if catalog == "default":
        catalog = spark.catalog.currentCatalog()
    
    if schema == "default":
        schema = spark.sql("SELECT current_schema()").first()[0]

    return f"{catalog}.{schema}.{table}"

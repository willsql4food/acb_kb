from databricks.sdk.runtime import *
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import *
from datetime import datetime
from typing import Dict, Optional
import uuid
import traceback
import json

# ============================================
# CONFIGURATION VARIABLES
# ============================================

# Logging Configuration
LOG_CATALOG = f"metadata_{env}"
LOG_SCHEMA = "edm"
LOG_TABLE = "on_prem_load_logging"
LOG_TABLE_FULL = f"{LOG_CATALOG}.{LOG_SCHEMA}.{LOG_TABLE}"

# Secret Scope Configuration
SECRET_SCOPE = "bronzeingestion-secret-scope"
DEFAULT_SECRET_SUFFIX =  f"onprem-sql-staging-{env}" 

# SQL Server Configuration
SQL_SERVER_PORT = 1433
SQL_DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
DEFAULT_BATCH_SIZE = 10000
DEFAULT_SCHEMA = "dbo"

# Default System Names
DEFAULT_SOURCE_SYSTEM = "EDM"
DEFAULT_TARGET_SYSTEM = "ON_PREM"

# Error Message Configuration
MAX_ERROR_MESSAGE_LENGTH = 4000

# Environment Mapping
ENV_MAPPING = {
    'development': 'dev',
    'production': 'prd',
    'quality assurance': 'qa',
    'qa': 'qa',
    'prod': 'prd',
    'dev': 'dev',
    'prd': 'prd'
}





"""
Usage:
    
    loader = OnPremDataLoader()
    loader.write_to_sql_server(
        df=your_dataframe,
        table_name="your_table",
        schema_name="dbo"
    )
"""



class OnPremDataLoader:
    """
    A class to handle data loading to SQL Server 
    """
    
    def __init__(self, spark: Optional[SparkSession] = None, config: Optional[Dict] = None, override_env: Optional[str] = None):
        """
        Initialize the OnPremDataLoader.
        
        Args:
            spark: Optional SparkSession. If not provided, will get or create one.
            config: Optional configuration dictionary to override defaults
            override_env: Optional environment override. If not provided, will auto-detect from cluster.
        """
        self.spark = spark or SparkSession.builder.appName("OnPremDataLoad").getOrCreate()
        
        # Get environment (use override if provided, otherwise auto-detect)
        self.env = override_env or self._get_environment()
        print(f"Initialized OnPremDataLoader with environment: {self.env}")
        
        # Override configuration if provided
        if config:
            self.log_table_full = config.get('log_table', LOG_TABLE_FULL)
            self.secret_scope = config.get('secret_scope', SECRET_SCOPE)
            self.default_secret_suffix = config.get('secret_suffix', DEFAULT_SECRET_SUFFIX)
            self.default_batch_size = config.get('batch_size', DEFAULT_BATCH_SIZE)
        else:
            self.log_table_full = LOG_TABLE_FULL
            self.secret_scope = SECRET_SCOPE
            self.default_secret_suffix = DEFAULT_SECRET_SUFFIX
            self.default_batch_size = DEFAULT_BATCH_SIZE
    
    # ============================================
    # ENVIRONMENT DETECTION METHOD
    # ============================================
    
    def _get_environment(self) -> str:
        """
        Get environment tag from cluster tags and map to standardized values.
        Returns 'unknown' if environment cannot be determined.
        """
        try:
            tags_json = self.spark.conf.get("spark.databricks.clusterUsageTags.clusterAllTags")
            if tags_json:
                tags = json.loads(tags_json)
                # Use next() with a generator expression to find the environment tag
                env_tag = next((tag['value'] for tag in tags if tag.get('key') == 'environment'), 'unknown')
                
                # Convert to lowercase and map to standardized value
                env_normalized = env_tag.lower().strip()
                return ENV_MAPPING.get(env_normalized, env_normalized)
                
        except Exception as e:
            print(f"Error retrieving environment from cluster tags: {e}")
            return 'unknown'
    
    def get_current_environment(self) -> str:
        """
        Public method to get the current environment.
        """
        return self.env
    
    # ============================================
    # LOGGING METHODS
    # ============================================
    
    def _log_to_table(self, log_record: Dict) -> None:
        """
        Write a log record to the logging table.
        """
        try:
            # Ensure all required fields have default values
            log_record_defaults = {
                "process_name": "",
                "table_name": "",
                "schema_name": "",
                "operation_type": "",
                "start_time": None,
                "end_time": None,
                "duration_seconds": None,
                "records_processed": None,
                "records_inserted": None,
                "records_updated": None,
                "records_deleted": None,
                "status": "UNKNOWN",
                "error_message": None,
                "source_system": DEFAULT_SOURCE_SYSTEM,
                "target_system": DEFAULT_TARGET_SYSTEM,
                "batch_id": str(uuid.uuid4()),
                "run_date": datetime.now().date(),
                "created_by": self._get_username(),
                "created_timestamp": datetime.now(),
                "additional_info": {}
            }
            
            # Update defaults with provided values
            log_record_defaults.update(log_record)
            
            # Build SQL INSERT statement
            insert_sql = self._build_insert_sql(log_record_defaults)
            
            self.spark.sql(insert_sql)
            print(f"✓ Log entry written for {log_record_defaults['table_name']} - Status: {log_record_defaults['status']}")
            
        except Exception as e:
            print(f"Warning: Failed to write to logging table: {str(e)}")
    
    def _build_insert_sql(self, record: Dict) -> str:
        """
        Build SQL INSERT statement for logging.
        """
        # Helper function to format SQL values
        def format_value(value, value_type):
            if value is None:
                return 'NULL'
            elif value_type == 'timestamp':
                return f"timestamp'{value}'"
            elif value_type == 'date':
                return f"date'{value}'"
            elif value_type == 'string':
                # Escape single quotes
                escaped = str(value).replace("'", "''")
                return f"'{escaped}'"
            elif value_type == 'number':
                return str(value)
            else:
                return 'NULL'
        
        # Format additional_info as map
        if record['additional_info']:
            map_items = [f"'{k}', '{v}'" for k, v in record['additional_info'].items()]
            map_str = f"map({', '.join(map_items)})"
        else:
            map_str = "map()"
        
        insert_sql = f"""
        INSERT INTO {self.log_table_full}
        (process_name, table_name, schema_name, operation_type, start_time, end_time,
         duration_seconds, records_processed, records_inserted, records_updated, records_deleted,
         status, error_message, source_system, target_system, batch_id, run_date,
         created_by, created_timestamp, additional_info)
        VALUES
        ({format_value(record['process_name'], 'string')},
         {format_value(record['table_name'], 'string')},
         {format_value(record['schema_name'], 'string')},
         {format_value(record['operation_type'], 'string')},
         {format_value(record['start_time'], 'timestamp')},
         {format_value(record['end_time'], 'timestamp')},
         {format_value(record['duration_seconds'], 'number')},
         {format_value(record['records_processed'], 'number')},
         {format_value(record['records_inserted'], 'number')},
         {format_value(record['records_updated'], 'number')},
         {format_value(record['records_deleted'], 'number')},
         {format_value(record['status'], 'string')},
         {format_value(record['error_message'], 'string')},
         {format_value(record['source_system'], 'string')},
         {format_value(record['target_system'], 'string')},
         {format_value(record['batch_id'], 'string')},
         {format_value(record['run_date'], 'date')},
         {format_value(record['created_by'], 'string')},
         {format_value(record['created_timestamp'], 'timestamp')},
         {map_str})
        """
        
        return insert_sql
    
    def _create_log_entry(
        self,
        process_name: str,
        table_name: str,
        schema_name: str,
        operation_type: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        records_processed: Optional[int] = None,
        records_inserted: Optional[int] = None,
        records_updated: Optional[int] = None,
        records_deleted: Optional[int] = None,
        status: str = "RUNNING",
        error_message: Optional[str] = None,
        source_system: str = DEFAULT_SOURCE_SYSTEM,
        target_system: str = DEFAULT_TARGET_SYSTEM,
        batch_id: Optional[str] = None,
        additional_info: Optional[Dict[str, str]] = None,
        env: Optional[str] = None
    ) -> Dict:
        """
        Create a log entry dictionary.
        """
        duration = None
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()
        
        # Use provided env or default to instance env
        env = env or self.env
        
        return {
            "process_name": process_name,
            "table_name": table_name,
            "schema_name": schema_name,
            "operation_type": operation_type.upper(),
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration,
            "records_processed": records_processed,
            "records_inserted": records_inserted,
            "records_updated": records_updated,
            "records_deleted": records_deleted,
            "status": status,
            "error_message": error_message[:MAX_ERROR_MESSAGE_LENGTH] if error_message else None,
            "source_system": source_system,
            "target_system": f"{target_system}_{env.upper()}" if env else target_system,
            "batch_id": batch_id or str(uuid.uuid4()),
            "run_date": start_time.date() if start_time else datetime.now().date(),
            "created_by": self._get_username(),
            "created_timestamp": datetime.now(),
            "additional_info": additional_info or {}
        }
    
    def _get_username(self) -> str:
        """
        Get the current username safely.
        """
        try:
            return self.spark.sql("SELECT current_user()").collect()[0][0]
        except:
            return "databricks_user"
    
    # ============================================
    # CONNECTION METHODS
    # ============================================
    
    def _parse_connection_string(self, connection_string: str) -> Dict[str, str]:
        """
        Parse SQL Server connection string into components.
        """
        conn_dict = {}
        for item in connection_string.split(';'):
            if '=' in item:
                key, value = item.split('=', 1)
                key = key.strip().lower().replace(' ', '_')
                conn_dict[key] = value.strip()
        return conn_dict
    
    def _get_connection_config(self, secret_name: str) -> Dict[str, str]:
        """
        Retrieve and parse connection configuration from Databricks Secret Scope.
        """
        try:
            connection_string = dbutils.secrets.get(scope=self.secret_scope, key=secret_name)
            conn_params = self._parse_connection_string(connection_string)
            
            jdbc_config = {
                "server": conn_params.get('data_source', ''),
                "database": conn_params.get('initial_catalog', ''),
                "user": conn_params.get('user_id', ''),
                "password": conn_params.get('password', ''),
                "integrated_security": conn_params.get('integrated_security', 'False')
            }
            
            jdbc_config["url"] = (
                f"jdbc:sqlserver://{jdbc_config['server']}:{SQL_SERVER_PORT};"
                f"databaseName={jdbc_config['database']};"
                f"encrypt=false;trustServerCertificate=true"
            )
            
            return jdbc_config
        except Exception as e:
            print(f"Error retrieving connection config from secret '{secret_name}': {str(e)}")
            raise
    
    # ============================================
    # MAIN WRITE METHOD
    # ============================================
    
    def write_to_sql_server(
        self,
        df: DataFrame,
        table_name: str,
        schema_name: str = DEFAULT_SCHEMA,
        env: Optional[str] = None,  #  will auto-detected if not provided
        mode: str = "overwrite",
        batch_size: int = None,
        num_partitions: Optional[int] = None,
        secret_suffix: str = None,
        additional_options: Optional[Dict[str, str]] = None,
        process_name: Optional[str] = None,
        source_system: str = DEFAULT_SOURCE_SYSTEM,
        batch_id: Optional[str] = None
    ) -> bool:
        """
        Write DataFrame to SQL Server table using JDBC with comprehensive logging.
        Environment is auto-detected if not provided.
        
        Args:
            df: DataFrame to write
            table_name: Target table name
            schema_name: Target schema name (default: "dbo")
            env: Optional environment. If not provided, uses auto-detected from cluster.
            mode: Write mode - "overwrite", "append", "ignore", "error" (default: "overwrite")
            batch_size: Number of rows to insert per batch
            num_partitions: Number of partitions for parallel writes
            secret_suffix: Suffix for the secret name
            additional_options: Additional JDBC options
            process_name: Name of the process for logging
            source_system: Source system name for logging
            batch_id: Batch ID for tracking related loads
            
        Returns:
            Boolean indicating success or failure
        """
        # Use provided env or default to auto-detected env
        env = env or self.env
        
        if env == 'unknown':
            raise ValueError("Environment could not be determined. Please provide 'env' parameter explicitly or ensure cluster has 'environment' tag.")
        
        # Use defaults if not provided
        batch_size = batch_size or self.default_batch_size
        secret_suffix = secret_suffix or self.default_secret_suffix
        
        # Generate batch_id if not provided
        if not batch_id:
            batch_id = str(uuid.uuid4())
        
        # Set process name if not provided
        if not process_name:
            process_name = f"write_to_sql_{table_name}"
        
        # Start timing
        start_time = datetime.now()
        
        print(f"[{start_time}] Starting write to SQL Server: {schema_name}.{table_name}")
        print(f"Batch ID: {batch_id}")
        print(f"Environment: {env}")
        print(f"Mode: {mode}")
        
        # Initial log entry
        initial_log = self._create_log_entry(
            process_name=process_name,
            table_name=table_name,
            schema_name=schema_name,
            operation_type=mode,
            start_time=start_time,
            status="RUNNING",
            source_system=source_system,
            target_system=f"ON_PREM_SQL_{env.upper()}",
            batch_id=batch_id,
            env=env
        )
        self._log_to_table(initial_log)
        
        try:
            # Get record count
            record_count = df.count()
            print(f"Records to process: {record_count}")
            
            # Cache the dataframe
            df_cached = df.cache()
            
            # Get connection configuration
            secret_name = f"{env}-{secret_suffix}"
            jdbc_config = self._get_connection_config(secret_name)
            
            # Prepare the full table name
            full_table_name = f"{schema_name}.{table_name}"
            
            # Repartition if specified
            if num_partitions:
                df_cached = df_cached.repartition(num_partitions)
                print(f"Repartitioned to {num_partitions} partitions")
            
            # Build and execute the writer
            writer = df_cached.write \
                .format("jdbc") \
                .option("url", jdbc_config["url"]) \
                .option("dbtable", full_table_name) \
                .option("user", jdbc_config["user"]) \
                .option("password", jdbc_config["password"]) \
                .option("driver", SQL_DRIVER) \
                .option("batchsize", batch_size) \
                .mode(mode)
            
            if additional_options:
                for key, value in additional_options.items():
                    writer = writer.option(key, value)
            
            writer.save()
            
            # Unpersist cached dataframe
            df_cached.unpersist()
            
            # End timing
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Log success
            success_log = self._create_log_entry(
                process_name=process_name,
                table_name=table_name,
                schema_name=schema_name,
                operation_type=mode,
                start_time=start_time,
                end_time=end_time,
                records_processed=record_count,
                records_inserted=record_count if mode.lower() in ["overwrite", "append"] else 0,
                records_updated=0,
                status="SUCCESS",
                source_system=source_system,
                target_system=f"ON_PREM_SQL_{env.upper()}",
                batch_id=batch_id,
                env=env,
                additional_info={
                    "server": jdbc_config.get("server", ""),
                    "database": jdbc_config.get("database", ""),
                    "batch_size": str(batch_size),
                    "num_partitions": str(num_partitions) if num_partitions else "default",
                    "environment": env
                }
            )
            self._log_to_table(success_log)
            
            print(f"[{end_time}] Successfully wrote {record_count} records to {schema_name}.{table_name}")
            print(f"Duration: {duration:.2f} seconds")
            if duration > 0:
                print(f"Records per second: {record_count/duration:.2f}")
            
            return True
            
        except Exception as e:
            # End timing
            end_time = datetime.now()
            error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
            
            print(f"[{end_time}] FAILED to write to {schema_name}.{table_name}")
            print(f"Error: {str(e)}")
            
            # Log failure
            failure_log = self._create_log_entry(
                process_name=process_name,
                table_name=table_name,
                schema_name=schema_name,
                operation_type=mode,
                start_time=start_time,
                end_time=end_time,
                records_processed=0,
                status="FAILED",
                error_message=error_msg,
                source_system=source_system,
                target_system=f"ON_PREM_SQL_{env.upper()}",
                batch_id=batch_id,
                env=env
            )
            self._log_to_table(failure_log)
            
            raise
    
    def process_batch(
        self,
        tables_config: List[Dict],
        env: Optional[str] = None,  # Now optional
        batch_id: Optional[str] = None,
        stop_on_error: bool = False
    ) -> Dict[str, bool]:
        """
        Process multiple tables in a batch.
        Environment is auto-detected if not provided.
        
        Args:
            tables_config: List of table configurations
            env: Optional environment override
            batch_id: Optional shared batch ID
            stop_on_error: Whether to stop on first error
            
        Returns:
            Dictionary with table names and success status
        """
        # Use provided env or default to auto-detected env
        env = env or self.env
        
        if not batch_id:
            batch_id = str(uuid.uuid4())
        
        print(f"Starting batch process with ID: {batch_id}")
        print(f"Environment: {env}")
        print(f"Processing {len(tables_config)} tables")
        
        results = {}
        
        for config in tables_config:
            table_name = config.get("target_table", "unknown")
            
            try:
                # Read source data
                source_table = config.get("source_table")
                df = self.spark.table(source_table)
                
                # Apply transformations if provided
                if "transformations" in config and callable(config["transformations"]):
                    df = config["transformations"](df)
                
                # Write with logging
                success = self.write_to_sql_server(
                    env=env,
                    df=df,
                    table_name=config.get("target_table"),
                    schema_name=config.get("target_schema", DEFAULT_SCHEMA),
                    mode=config.get("mode", "overwrite"),
                    batch_size=config.get("batch_size", self.default_batch_size),
                    num_partitions=config.get("num_partitions"),
                    secret_suffix=config.get("secret_suffix", self.default_secret_suffix),
                    additional_options=config.get("additional_options"),
                    process_name=config.get("process_name", f"batch_load_{table_name}"),
                    source_system=config.get("source_system", DEFAULT_SOURCE_SYSTEM),
                    batch_id=batch_id
                )
                
                results[table_name] = success
                
            except Exception as e:
                print(f"Failed to process table {table_name}: {str(e)}")
                results[table_name] = False
                
                if stop_on_error:
                    break
        
        # Print summary
        successful = sum(1 for v in results.values() if v)
        failed = len(results) - successful
        
        print(f"\nBatch {batch_id} completed:")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")
        
        return results
    
    # ============================================
    # MONITORING METHODS
    # ============================================
    
    def get_recent_logs(self, hours: int = 24) -> DataFrame:
        """Get recent log entries."""
        query = f"""
        SELECT 
            log_id,
            process_name,
            table_name,
            schema_name,
            operation_type,
            start_time,
            end_time,
            duration_seconds,
            records_processed,
            status,
            target_system,
            SUBSTRING(error_message, 1, 100) as error_summary,
            batch_id
        FROM {self.log_table_full}
        WHERE start_time >= current_timestamp() - INTERVAL {hours} HOURS
        ORDER BY start_time DESC
        LIMIT 50
        """
        return self.spark.sql(query)
    
    def get_batch_summary(self, batch_id: str) -> DataFrame:
        """Get summary for a specific batch."""
        query = f"""
        SELECT 
            batch_id,
            COUNT(*) as total_tables,
            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
            SUM(records_processed) as total_records,
            MIN(start_time) as batch_start,
            MAX(end_time) as batch_end,
            SUM(duration_seconds) as total_duration_seconds
        FROM {self.log_table_full}
        WHERE batch_id = '{batch_id}'
        GROUP BY batch_id
        """
        return self.spark.sql(query)
    
    def get_table_history(self, table_name: str, days: int = 7) -> DataFrame:
        """Get load history for a specific table."""
        query = f"""
        SELECT 
            run_date,
            table_name,
            operation_type,
            start_time,
            duration_seconds,
            records_processed,
            status,
            target_system,
            batch_id
        FROM {self.log_table_full}
        WHERE table_name = '{table_name}'
            AND run_date >= current_date() - {days}
        ORDER BY start_time DESC
        """
        return self.spark.sql(query)
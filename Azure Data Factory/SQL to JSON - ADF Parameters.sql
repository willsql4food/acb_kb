/* ====================================================================================================================
Sample of SQL table to parameter list in JSON
	Author:		A. Carter Burleigh (ACB)
	Info:		See selfDoc: section
---	----------	-------------------------------------------------------------------------------------------------------
ACB	2024-07-12	Initial development
=======================================================================================================================
We're after something in this format:
{
	"parameters": [
		{
			"name": "dsSecretName",
			"value": "qa-conn-string-mms"
		},
		{
			"name": "dsKVBaseURL",
			"value": "https://akv-ab092898.vault.azure.net/"
		},
		{
			"name": "SinkdsFilePath",
			"value": "bronze/Google/fnd-cloud-project/analytics_250303278"
		}
	]
}
*/

/* ====================================================================================================================
	Temporary table as a sample - this would be a real table with proper defaults, foreign keys, indexes, etc.
==================================================================================================================== */
declare @tParams table 
	( 
		id int not null identity(1,1)
	,	dataset_id int not null default 0		/* Would foreign key to wm.dataSet */
	,	prefix varchar(255) null
	,	parameter varchar(255) not null
	,	[value] varchar(2000) not null
	)

/* ====================================================================================================================
	Add some sample data
==================================================================================================================== */
insert into @tParams (prefix, parameter, [value])
values	(null, 		'dsSecretName', 	'qa-conn-string-mms')
	,	(null, 		'dsKVBaseURL', 		'https://akv-ab092898.vault.azure.net/')
	,	('Source', 	'dsSqlDB', 			'LoadControl')
	,	('Sink', 	'dsFilePath', 		'bronze/Google/fnd-cloud-project/analytics_250303278')
	,	('Sample', 	'SpecialChars',		'"Hello world!"
"This is a new line..."')

/* ====================================================================================================================
	Quick check of the data
==================================================================================================================== */
select * from @tParams where dataset_id = 0

/* ====================================================================================================================
	Query using the FOR JSON PATH directive to get our desired end result 
	NOTE: the ROOT directive wraps it in a single crispy JSON object with a nice, chewy array of parameters inside.
==================================================================================================================== */
select		[name] = concat(prefix, parameter)
		,	[value]
from		@tParams
where		dataset_id = 0
for json path, root('parameters')

/*
We got: (NOTE that SQL handles escape of special characters)
-----------------------------------------------------------------------------------------------------------------------
{
	"parameters": [
		{
			"name": "dsSecretName",
			"value": "qa-conn-string-mms"
		},
		{
			"name": "dsKVBaseURL",
			"value": "https:\/\/akv-ab092898.vault.azure.net\/"
		},
		{
			"name": "SourcedsSqlDB",
			"value": "LoadControl"
		},
		{
			"name": "SinkdsFilePath",
			"value": "bronze\/Google\/fnd-cloud-project\/analytics_250303278"
		},
		{
			"name": "SampleSpecialChars",
			"value": "\"Hello world!\"\r\n\"This is a new line...\""
		}
	]
}
*/
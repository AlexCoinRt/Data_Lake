from datetime import timedelta, datetime
from random import randint

from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.contrib.operators.dataproc_operator import DataProcHiveOperator

username = 'alapenko'
default_args = {
    'owner': username,
    'depends_on_past': False,
    'start_date': datetime(2013, 1, 1, 0, 0, 0),
    'retries': 1,
    'retry_delay': timedelta(seconds=120),
}

dag = DAG(
    username + '_data_lake_etl',
    default_args=default_args,
    description='Datalake tasks',
    schedule_interval="0 0 1 1 *",
    concurrency=3,
    max_active_runs=3,
)
tasks = ('billing', 'issue', 'payment', 'traffic')
ods = []
for task in tasks:
    if task == 'billing':
      
        query = """insert overwrite table alapenko.ods_billing partition (year='{{ execution_date.year }}') 
               select user_id, billing_period, service, tariff, cast(sum as DECIMAL(10,2)), cast(created_at as TIMESTAMP) 
               from alapenko.stg_billing where year(created_at) = {{ execution_date.year }};"""
    
    elif task == 'issue':
      
        query = """insert overwrite table alapenko.ods_issue partition (year='{{ execution_date.year }}') 
               select cast(user_id as INT), cast(start_time as TIMESTAMP), cast(end_time as TIMESTAMP), title, description, service 
               from alapenko.stg_issue where year(start_time) = {{ execution_date.year }};"""
        
    elif task == 'payment':
      
        query = """insert overwrite table alapenko.ods_payment partition (year='{{ execution_date.year }}') 
               select user_id, pay_doc_type, pay_doc_num, account, phone, billing_period, cast(pay_date as DATE), cast(sum as DECIMAL(10,2))
               from alapenko.stg_payment where year(cast(pay_date as DATE)) = {{ execution_date.year }};"""
    
	elif task == 'traffic':
      
        query = """insert overwrite table alapenko.ods_traffic partition (year='{{ execution_date.year }}') 
               select user_id, cast(from_unixtime(`timestamp` div 1000) as TIMESTAMP), device_id, device_ip_addr, bytes_sent, bytes_received 
               from alapenko.stg_traffic where year(from_unixtime(`timestamp` div 1000)) = {{ execution_date.year }};"""
        
    ods = DataProcHiveOperator(
        task_id='ods_' + task,
        dag=dag,
        query=query,
        job_name=username + '_{{ execution_date.year }}_ods_' + task + '_{{ params.job_suffix }}',
        params={"job_suffix": randint(0, 100000)},
        cluster_name='cluster-dataproc',
        region='europe-west3',
    )
    if task == 'traffic':
        dm = DataProcHiveOperator(
            task_id='dm_traffic',
            dag=dag,
            query="""insert overwrite table alapenko.dm_traffic partition (year='{{ execution_date.year }}')  
                     select user_id, max(bytes_received), min(bytes_received), round(avg(bytes_received)) as avg_traf
                     from alapenko.ods_traffic where year = {{ execution_date.year }} group by user_id order by avg_traf;""",
            job_name=username + '_{{ execution_date.year }}_dm_traffic_{{ params.job_suffix }}',
            params={"job_suffix": randint(0, 100000)},
            cluster_name='cluster-dataproc',
            region='europe-west3',
        )
        ods >> dm

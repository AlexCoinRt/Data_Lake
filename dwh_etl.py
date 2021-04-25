from datetime import timedelta, datetime
from random import randint

from airflow import DAG
from airflow.operators.postgres_operator import PostgresOperator
from airflow.operators.dummy_operator import DummyOperator

USERNAME = 'alapenko'

default_args = {
    'owner': USERNAME,
    'start_date': datetime(2013, 1, 1, 0, 0, 0)
}

dag = DAG(
    dag_id=USERNAME + '_dwh_etl',
    default_args=default_args,
    default_view='graph',
    description='DWH ETL tasks by ' + USERNAME,
    schedule_interval="@yearly",
    max_active_runs=1,
    params={'schemaName': USERNAME},
)

## ЗАГРУЗКА ДАННЫХ

ods_reload = PostgresOperator(
    task_id="ods_reload", 
    dag=dag,
    sql="""
    delete from {{ params.schemaName }}.ods_payment_table cascade
    where extract(year from pay_date) = {{ execution_date.year }};

    delete from {{ params.schemaName }}.ods_payment_hashed_table cascade
    where extract(year from effective_from) = {{ execution_date.year }};

    insert into {{ params.schemaName}}.ods_payment_table
        (select * 
         from {{ params.schemaName }}.stg_payment 
         where extract(year from pay_date) = {{ execution_date.year }});

    insert into {{ params.schemaName}}.ods_payment_hashed_table
        (select v.*, '{{ execution_date }}'::date as load_dts
         from {{ params.schemaName }}.ods_payment_view as v
         where extract(year from v.effective_from) = {{ execution_date.year }});
"""
)

dds_hub_user = PostgresOperator(
    task_id="dds_hub_user",
    dag=dag,
    sql="""
    insert into {{ params.schemaName }}.dds_hub_user_table 
    (select * from {{ params.schemaName }}.dds_hub_user_view);
"""
)

dds_hub_account = PostgresOperator(
    task_id="dds_hub_account",
    dag=dag,
    sql="""
    insert into {{ params.schemaName }}.dds_hub_account_table 
    (select * from {{ params.schemaName }}.dds_hub_account_view);
"""
)

dds_hub_billing_period = PostgresOperator(
    task_id="dds_hub_billing_period",
    dag=dag,
    sql="""
    insert into {{ params.schemaName }}.dds_hub_billing_period_table 
    (select * from {{ params.schemaName }}.dds_hub_billing_period_view);
"""
)

dds_lnk_payment = PostgresOperator(
    task_id="dds_lnk_payment",
    dag=dag,
    sql="""
    insert into {{ params.schemaName }}.dds_lnk_payment_table 
    (select * from {{ params.schemaName }}.dds_lnk_payment_view);
"""
)

dds_sat_user = PostgresOperator(
    task_id="dds_sat_user",
    dag=dag,
    sql="""
    delete from {{ params.schemaName }}.dds_sat_user_table 
    where extract(year from load_dts) = {{ execution_date.year }};

    insert into {{ params.schemaName }}.dds_sat_user_table
    with source_data as (
        select user_pk,
               user_hashdiff,
               phone,
               effective_from,
               load_dts,
               rec_source
        from {{ params.schemaName }}.ods_payment_hashed_table
        where extract(year from load_dts) = {{ execution_date.year }}
    ),
    update_records as (
        select s.*
        from {{ params.schemaName }}.dds_sat_user_table as s
            join source_data as src
                on s.user_pk = src.user_pk and s.load_dts <= (select max(load_dts) from source_data)
    ),
    latest_records as (
        select * from (
            select  user_pk,
                    user_hashdiff,
                    load_dts,
                    rank() over (partition by user_pk order by load_dts desc) as row_rank
            from update_records
        ) as ranked_recs
        where row_rank = 1),
    records_to_insert as (
        select distinct a.*
        from source_data as a
            left join latest_records
                on latest_records.user_hashdiff = a.user_hashdiff and
                    latest_records.user_pk = a.user_pk
        where latest_records.user_hashdiff is null
    )
select * from records_to_insert;
"""
)

dds_sat_payment = PostgresOperator(
    task_id="dds_sat_payment",
    dag=dag,
    sql="""
    delete from {{ params.schemaName }}.dds_sat_payment_table 
    where extract(year from load_dts) = {{ execution_date.year }};

    insert into {{ params.schemaName }}.dds_sat_payment_table
    with source_data as (
        select pay_pk,
               pay_hashdiff,
               pay_doc_type,
               pay_doc_num,
               pay_sum,
               effective_from,
               load_dts,
               rec_source
        from {{ params.schemaName }}.ods_payment_hashed_table
        where extract(year from load_dts) = {{ execution_date.year }}
    ),
    update_records as (
        select s.*
        from {{ params.schemaName }}.dds_sat_payment_table as s
                 join source_data as src
                      on s.pay_pk = src.pay_pk and s.load_dts <= (select max(load_dts) from source_data)
    ),
    latest_records as (
        select *
        from (
                 select pay_pk,
                 pay_hashdiff,
                 load_dts,
                 rank() over (partition by pay_pk order by load_dts desc) as row_rank
                 from update_records
             ) as ranked_recs
        where row_rank = 1),
    records_to_insert as (
        select distinct a.*
        from source_data as a
           left join latest_records
               on latest_records.pay_hashdiff = a.pay_hashdiff and
                   latest_records.pay_pk = a.pay_pk
        where latest_records.pay_hashdiff is null
    )
select * from records_to_insert;
"""
)

## СТРУКТУРА DAG's

all_hubs_loaded = DummyOperator(task_id="all_hubs_loaded", dag=dag)
all_links_loaded = DummyOperator(task_id="all_links_loaded", dag=dag)
all_sats_loaded = DummyOperator(task_id="all_sats_loaded", dag=dag)

ods_reload >> [dds_hub_user, dds_hub_account, dds_hub_billing_period]

dds_hub_user >> all_hubs_loaded
dds_hub_account >> all_hubs_loaded
dds_hub_billing_period >> all_hubs_loaded

all_hubs_loaded >> dds_lnk_payment
dds_lnk_payment >> all_links_loaded

all_links_loaded >> [dds_sat_user, dds_sat_payment]
dds_sat_user >> all_sats_loaded
dds_sat_payment >> all_sats_loaded

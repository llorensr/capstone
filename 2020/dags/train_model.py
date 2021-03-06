from airflow import DAG
from airflow.utils.dates import days_ago
from custom_airflow.operators import CustomBigQueryOperator
from custom_airflow.operators import CustomBigQueryToCloudStorageOperator
from custom_airflow.operators import CustomGoogleCloudStorageDownloadDirectoryOperator
from custom_airflow.sensors import (BigQueryWildcardTableSuffixSensor,
                                    CustomBigQueryTableSensor)
from airflow.models import Variable
import os


default_args = {
    'start_date': days_ago(0),
    'project_id': Variable.get('gcp_project_id'),
    'bigquery_conn_id': Variable.get('bigquery_conn_id'),
    'dataset_id': Variable.get('bigquery_dataset_id'),
    'write_disposition': 'WRITE_TRUNCATE',
    'allow_large_results': True,
    'use_legacy_sql': False,
    'google_cloud_storage_conn_id': Variable.get('google_cloud_storage_conn_id')
}


# *****************************************************************************
# DAG DEFINITION
# *****************************************************************************
dag = DAG(
    'train_model',
    default_args=default_args,
    description='Train model pipeline',
    schedule_interval=None)


# *****************************************************************************
# TRAIN TITLES SENSOR
# *****************************************************************************
train_titles_sensor = BigQueryWildcardTableSuffixSensor(
    task_id='train_titles_sensor',
    dag=dag,
    table_id='stackoverflow_posts_title_*',
    initial_suffix='{{ dag_run.conf["initial_train_pdate"] }}',
    final_suffix='{{ dag_run.conf["final_train_pdate"] }}',
    timeout=60)


# *****************************************************************************
# TRAIN TAGS SENSOR
# *****************************************************************************
train_tagged_posts_sensor = BigQueryWildcardTableSuffixSensor(
    task_id='train_tagged_posts_sensor',
    dag=dag,
    table_id='stackoverflow_posts_tags_*',
    initial_suffix='{{ dag_run.conf["initial_train_pdate"] }}',
    final_suffix='{{ dag_run.conf["final_train_pdate"] }}',
    timeout=60)


# *****************************************************************************
# TEST TITLES SENSOR
# *****************************************************************************
test_titles_sensor = BigQueryWildcardTableSuffixSensor(
    task_id='test_titles_sensor',
    dag=dag,
    table_id='stackoverflow_posts_title_*',
    initial_suffix='{{ dag_run.conf["initial_test_pdate"] }}',
    final_suffix='{{ dag_run.conf["final_test_pdate"] }}',
    timeout=60)


# *****************************************************************************
# TEST TAGS SENSOR
# *****************************************************************************
test_tagged_posts_sensor = BigQueryWildcardTableSuffixSensor(
    task_id='test_tagged_posts_sensor',
    dag=dag,
    table_id='stackoverflow_posts_tags_*',
    initial_suffix='{{ dag_run.conf["initial_test_pdate" ]}}',
    final_suffix='{{ dag_run.conf["final_test_pdate"] }}',
    timeout=60)


# *****************************************************************************
# TAGS TABLE SENSOR
# *****************************************************************************
tags_table_sensor = CustomBigQueryTableSensor(
    task_id='tags_table_sensor',
    dag=dag,
    table_id='tags',
    timeout=60)


# *****************************************************************************
# SELECT TAGS
# *****************************************************************************
select_tags = CustomBigQueryOperator(
    task_id='select_tags',
    dag=dag,
    sql='sql/select_tags.sql',
    destination_dataset_table='{0}.{1}.selected_tags'
        .format(Variable.get('gcp_project_id'), Variable.get('bigquery_dataset_id')))


# *****************************************************************************
# FLATTEN TAGS
# *****************************************************************************
train_flatten_tags = CustomBigQueryOperator(
    task_id='train_flatten_tags',
    dag=dag,
    sql='sql/flatten_tags.sql',
    destination_dataset_table='{0}.{1}.train_flattened_tags'
        .format(Variable.get('gcp_project_id'), Variable.get('bigquery_dataset_id')),
    params={'train_test': 'train'})


test_flatten_tags = CustomBigQueryOperator(
    task_id='test_flatten_tags',
    dag=dag,
    sql='sql/flatten_tags.sql',
    destination_dataset_table='{0}.{1}.test_flattened_tags'
        .format(Variable.get('gcp_project_id'), Variable.get('bigquery_dataset_id')),
    params={'train_test': 'test'})


# *****************************************************************************
# CONSTRUCT TRAIN AND TEST TABLES
# *****************************************************************************
train_construct_table = CustomBigQueryOperator(
    task_id='train_construct_table',
    dag=dag,
    sql='sql/construct_table.sql',
    destination_dataset_table='{0}.{1}.train_table'
        .format(Variable.get('gcp_project_id'), Variable.get('bigquery_dataset_id')),
    params={'train_test': 'train'})


test_construct_table = CustomBigQueryOperator(
    task_id='test_construct_table',
    dag=dag,
    sql='sql/construct_table.sql',
    destination_dataset_table='{0}.{1}.test_table'
        .format(Variable.get('gcp_project_id'), Variable.get('bigquery_dataset_id')),
    params={'train_test': 'test'})


# *****************************************************************************
# EXPORT TO GOOGLE CLOUD STORAGE
# *****************************************************************************
train_export_to_cloud_storage = CustomBigQueryToCloudStorageOperator(
    task_id='train_export_to_cloud_storage',
    dag=dag,
    source_project_dataset_table="{{ task_instance.xcom_pull(task_ids='train_construct_table', key='table_uri') | replace('`', '') }}",
    destination_cloud_storage_uris=['gs://' + os.path.join(Variable.get('gcs_bucket'), Variable.get('gcs_prefix'), 'train-table', '*')],
    compression='NONE',
    export_format='CSV')


test_export_to_cloud_storage = CustomBigQueryToCloudStorageOperator(
    task_id='test_export_to_cloud_storage',
    dag=dag,
    source_project_dataset_table="{{ task_instance.xcom_pull(task_ids='test_construct_table', key='table_uri') | replace('`', '') }}",
    destination_cloud_storage_uris=['gs://' + os.path.join(Variable.get('gcs_bucket'), Variable.get('gcs_prefix'), 'test-table', '*')],
    compression='NONE',
    export_format='CSV')


# *****************************************************************************
# DOWNLOAD TO LOCAL
# *****************************************************************************
train_download_to_local = CustomGoogleCloudStorageDownloadDirectoryOperator(
    task_id='train_download_to_local',
    dag=dag,
    bucket=Variable.get('gcs_bucket'),
    prefix=os.path.join(Variable.get('gcs_prefix'), 'train-table/'),
    directory=Variable.get('local_working_dir'))


test_download_to_local = CustomGoogleCloudStorageDownloadDirectoryOperator(
    task_id='test_download_to_local',
    dag=dag,
    bucket=Variable.get('gcs_bucket'),
    prefix=os.path.join(Variable.get('gcs_prefix'), 'test-table/'),
    directory=Variable.get('local_working_dir'))


# *****************************************************************************
# RELATIONS BETWEEN TASKS
# *****************************************************************************
[train_tagged_posts_sensor, tags_table_sensor] >> select_tags
[select_tags, train_tagged_posts_sensor] >> train_flatten_tags
[select_tags, test_tagged_posts_sensor] >> test_flatten_tags
[train_flatten_tags, train_titles_sensor] >> train_construct_table
[test_flatten_tags, test_titles_sensor] >> test_construct_table
train_construct_table >> train_export_to_cloud_storage
test_construct_table >> test_export_to_cloud_storage
train_export_to_cloud_storage >> train_download_to_local
test_export_to_cloud_storage >> test_download_to_local

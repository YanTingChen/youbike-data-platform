"""BigQuery raw 表的欄位定義（與 transform.py 的輸出欄位一一對應）。"""

from google.cloud import bigquery

AVAILABILITY_SCHEMA = [
    bigquery.SchemaField("station_uid", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("station_id", "STRING"),
    bigquery.SchemaField("service_type", "INT64"),
    bigquery.SchemaField("service_status", "INT64"),
    bigquery.SchemaField("bikes_available", "INT64"),
    bigquery.SchemaField("docks_available", "INT64"),
    bigquery.SchemaField("general_bikes_available", "INT64"),
    bigquery.SchemaField("ebikes_available", "INT64"),
    bigquery.SchemaField("source_updated_at", "TIMESTAMP"),
    bigquery.SchemaField("api_updated_at", "TIMESTAMP"),
    bigquery.SchemaField("city", "STRING"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

STATION_SCHEMA = [
    bigquery.SchemaField("station_uid", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("station_id", "STRING"),
    bigquery.SchemaField("authority_id", "STRING"),
    bigquery.SchemaField("station_name", "STRING"),
    bigquery.SchemaField("station_name_en", "STRING"),
    bigquery.SchemaField("address", "STRING"),
    bigquery.SchemaField("address_en", "STRING"),
    bigquery.SchemaField("lat", "FLOAT64"),
    bigquery.SchemaField("lng", "FLOAT64"),
    bigquery.SchemaField("capacity", "INT64"),
    bigquery.SchemaField("service_type", "INT64"),
    bigquery.SchemaField("source_updated_at", "TIMESTAMP"),
    bigquery.SchemaField("api_updated_at", "TIMESTAMP"),
    bigquery.SchemaField("city", "STRING"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

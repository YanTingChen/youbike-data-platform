"""GCS 寫入與 BigQuery 載入介面。"""

from __future__ import annotations

import logging

from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)


def upload_text(project_id: str, bucket: str, blob_path: str, content: str, content_type: str) -> str:
    """上傳文字內容到 GCS，回傳 gs:// URI。"""
    client = storage.Client(project=project_id)
    blob = client.bucket(bucket).blob(blob_path)
    blob.upload_from_string(content.encode("utf-8"), content_type=content_type)
    uri = f"gs://{bucket}/{blob_path}"
    logger.info("已上傳 %s（%d bytes）", uri, len(content.encode("utf-8")))
    return uri


def load_ndjson_to_bigquery(
    project_id: str,
    location: str,
    gcs_uri: str,
    table_id: str,
    schema: list[bigquery.SchemaField],
) -> int:
    """以 Append 方式把 GCS 上的 NDJSON 載入 BigQuery。

    - 表格依 ingested_at 按天分區、依 station_uid 叢集，查詢時能裁剪掃描量、降低費用
    - raw 層只做 Append，去重交給 dbt（raw 保留完整紀錄，方便追查與重算）
    - 不存在時自動建表
    """
    client = bigquery.Client(project=project_id, location=location)
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        schema=schema,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="ingested_at"
        ),
        clustering_fields=["station_uid"],
    )
    job = client.load_table_from_uri(gcs_uri, table_id, job_config=job_config)
    job.result()  # 等待完成；失敗時會拋出例外讓 Airflow 重試
    logger.info("已載入 %d 列到 %s", job.output_rows, table_id)
    return int(job.output_rows or 0)

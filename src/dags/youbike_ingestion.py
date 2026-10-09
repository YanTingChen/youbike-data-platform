"""即時 API 無法回補，停用 catchup 並限制同時執行一輪。"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task

from ingestion.config import Settings
from ingestion.pipeline import extract_to_gcs, load_to_bigquery, raw_asset_name
from ingestion.transform import utc_now

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=5),
}


def build_ingestion_dag(dataset_name: str, schedule: str, doc: str):
    @dag(
        dag_id=f"youbike_{dataset_name}",
        schedule=schedule,
        start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["youbike", "ingestion", "tdx"],
        doc_md=doc,
    )
    def ingestion_dag():
        @task
        def extract() -> dict:
            return extract_to_gcs(dataset_name, Settings.from_env(), utc_now())

        # 載入成功後發出 Asset 事件，讓依賴最新資料的 DAG 接著執行（例如網頁快照）
        @task(outlets=[Asset(raw_asset_name(dataset_name))])
        def load(extracted: dict) -> int:
            return load_to_bigquery(dataset_name, Settings.from_env(), extracted["staged_uri"])

        load(extract())

    return ingestion_dag()


build_ingestion_dag(
    "bike_availability",
    schedule="*/10 * * * *",
    doc="台中 YouBike 即時車況，每 10 分鐘擷取一次，寫入 BigQuery `bike_availability`。",
)
build_ingestion_dag(
    "bike_stations",
    schedule="0 3 * * *",
    doc="台中 YouBike 站點基本資料，每天 03:00 擷取，供 dbt snapshot 追蹤站點變動（SCD Type 2）。",
)

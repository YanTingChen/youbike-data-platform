"""快照發布獨立排程，避免發布失敗影響擷取狀態。"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task
from airflow.sdk.exceptions import AirflowSkipException

from ingestion.pipeline import raw_asset_name
from serving.snapshot import fetch_snapshot, write_gcs


@dag(
    dag_id="youbike_snapshot",
    schedule=[Asset(raw_asset_name("bike_availability"))],
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-eng",
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "execution_timeout": timedelta(minutes=5),
    },
    tags=["youbike", "serving"],
)
def youbike_snapshot():
    @task
    def publish() -> int:
        uri = os.environ.get("SNAPSHOT_GCS_URI", "").strip()
        if not uri:
            raise AirflowSkipException("沒有設定 SNAPSHOT_GCS_URI，不發布快照")
        snapshot = fetch_snapshot()
        write_gcs(snapshot, uri)
        return len(snapshot["stations"])

    publish()


youbike_snapshot()

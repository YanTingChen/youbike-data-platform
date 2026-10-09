"""匯出公開快照，讓靜態網頁無須存取資料庫憑證。"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingestion.transform import display_station_name

logger = logging.getLogger(__name__)

SQL_FILE = Path(__file__).parent / "sql" / "snapshot.sql"

FORECASTS_QUERY = """
    select station_uid, forecast_for, predicted_bikes_available
    from `{forecasts}`
    -- 只要「還沒到期」的預測；第二個條件讓 BigQuery 只掃描最近的分區
    where forecast_for > current_timestamp()
      and forecast_for < timestamp_add(current_timestamp(), interval 1 day)
    qualify row_number() over (partition by station_uid order by feature_ts desc) = 1
"""
# 預測表要等模型第一次訓練並推論後才存在；不存在時改用這個空的查詢，網頁照常運作，只是沒有預測
NO_FORECASTS_QUERY = """
    select
        cast(null as string) as station_uid,
        cast(null as timestamp) as forecast_for,
        cast(null as float64) as predicted_bikes_available
    limit 0
"""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_snapshot(rows: Iterable[Mapping[str, Any]], generated_at: datetime) -> dict[str, Any]:
    """把查詢結果整理成網頁要的格式。純函式，方便單元測試。"""
    stations = []
    for row in rows:
        station: dict[str, Any] = {
            "id": row["station_uid"],
            # 來源的站名都帶有「YouBike2.0_」前綴，畫面上不需要
            "name": display_station_name(row["station_name"]),
            "lat": round(row["lat"], 5),
            "lng": round(row["lng"], 5),
            "bikes": int(row["bikes_available"]),
            "docks": int(row["docks_available"]),
            "in_service": bool(row["in_service"]),
        }
        if row.get("forecast_for") is not None and row.get("predicted_bikes_available") is not None:
            station["forecast"] = {
                "at": _iso(row["forecast_for"]),
                "bikes": round(float(row["predicted_bikes_available"]), 1),
            }
        stations.append(station)
    return {"generated_at": _iso(generated_at), "stations": stations}


def render_sql(project: str, raw_dataset: str, dbt_dataset: str, include_forecasts: bool) -> str:
    forecasts_query = (FORECASTS_QUERY if include_forecasts else NO_FORECASTS_QUERY).format(
        forecasts=f"{project}.{dbt_dataset}_ml.station_forecasts"
    )
    return SQL_FILE.read_text(encoding="utf-8").format(
        availability=f"{project}.{raw_dataset}.bike_availability",
        stations=f"{project}.{dbt_dataset}_marts.dim_bike_station",
        forecasts_query=forecasts_query.strip(),
    )


def fetch_snapshot() -> dict[str, Any]:
    """查詢 BigQuery，回傳快照。資料集名稱沿用擷取與 dbt 的環境變數。"""
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    project = os.environ["GCP_PROJECT_ID"]
    raw_dataset = os.environ.get("BQ_RAW_DATASET", "youbike_raw")
    dbt_dataset = os.environ.get("BQ_DBT_DATASET", "youbike")
    client = bigquery.Client(project=project, location=os.environ.get("BQ_LOCATION", "asia-east1"))

    try:
        client.get_table(f"{project}.{dbt_dataset}_ml.station_forecasts")
        include_forecasts = True
    except NotFound:
        include_forecasts = False

    job = client.query(render_sql(project, raw_dataset, dbt_dataset, include_forecasts))
    snapshot = build_snapshot((dict(row) for row in job.result()), datetime.now(UTC))
    if not snapshot["stations"]:
        # 寧可讓任務失敗、保留上一份快照，也不要用空的資料蓋掉它
        raise ValueError("最近 60 分鐘沒有任何車況資料，不更新快照")
    logger.info(
        "快照：%d 個站點，其中 %d 個有預測（查詢處理 %s bytes）",
        len(snapshot["stations"]),
        sum("forecast" in station for station in snapshot["stations"]),
        job.total_bytes_processed,
    )
    return snapshot


def to_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


def write_local(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(snapshot), encoding="utf-8")


def write_gcs(snapshot: dict[str, Any], uri: str) -> None:
    """上傳到 GCS（uri 形如 gs://bucket/path/snapshot.json）。物件要設成公開可讀，網頁才抓得到。"""
    from google.cloud import storage

    bucket_name, _, blob_path = uri.removeprefix("gs://").partition("/")
    blob = storage.Client(project=os.environ["GCP_PROJECT_ID"]).bucket(bucket_name).blob(blob_path)
    # 資料每 10 分鐘更新一次，不讓瀏覽器與 CDN 快取太久
    blob.cache_control = "public, max-age=60"
    blob.upload_from_string(to_json(snapshot).encode("utf-8"), content_type="application/json")
    logger.info("已上傳 %s", uri)

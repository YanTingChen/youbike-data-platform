"""保存原始資料供重算，再將清洗結果載入 BigQuery。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ingestion.config import Settings
from ingestion.tdx_client import TDXClient
from ingestion.transform import normalize_availability, normalize_stations, to_ndjson

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class Dataset:
    name: str
    fetch: Callable[[TDXClient, str], list[dict[str, Any]]]
    normalize: Callable[[list[dict[str, Any]], str, datetime], pd.DataFrame]
    table: str


DATASETS: dict[str, Dataset] = {
    "bike_availability": Dataset(
        name="bike_availability",
        fetch=lambda client, city: client.get_bike_availability(city),
        normalize=normalize_availability,
        table="bike_availability",
    ),
    "bike_stations": Dataset(
        name="bike_stations",
        fetch=lambda client, city: client.get_bike_stations(city),
        normalize=normalize_stations,
        table="bike_stations",
    ),
}


def raw_asset_name(dataset: str) -> str:
    """資料載入 BigQuery raw 表後發出的 Airflow Asset 名稱，下游 DAG 以它為排程。"""
    return f"youbike_raw_{dataset}"


def build_object_paths(dataset: str, city: str, ingested_at: datetime) -> tuple[str, str]:
    """依當地時間切日期與小時分區，檔名用 UTC 時間戳，回傳 (raw 路徑, staged 路徑)。"""
    local = ingested_at.astimezone(TAIPEI)
    partition = f"tdx/{dataset}/city={city}/dt={local:%Y-%m-%d}/hour={local:%H}"
    stamp = ingested_at.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    return f"raw/{partition}/{stamp}.json", f"staged/{partition}/{stamp}.ndjson"


def extract(
    dataset_name: str, settings: Settings, client: TDXClient, ingested_at: datetime
) -> dict[str, Any]:
    """抓取 API → 清洗 → 回傳原始資料、清洗後資料與 GCS 路徑（尚未上傳）。"""
    dataset = DATASETS[dataset_name]
    records = dataset.fetch(client, settings.city)
    df = dataset.normalize(records, settings.city, ingested_at)
    if df.empty:
        raise ValueError(f"{dataset_name} 沒有任何資料，可能是 API 異常，中止本次執行")
    raw_path, staged_path = build_object_paths(dataset_name, settings.city, ingested_at)
    logger.info("%s：API 回傳 %d 筆，清洗後 %d 筆", dataset_name, len(records), len(df))
    return {
        "records": records,
        "df": df,
        "raw_path": raw_path,
        "staged_path": staged_path,
    }


def extract_to_gcs(dataset_name: str, settings: Settings, ingested_at: datetime) -> dict[str, Any]:
    """Airflow 任務 1：抓取並把原始 JSON 與 NDJSON 上傳到 GCS。回傳值會存進 XCom（只放小資料）。"""
    from ingestion.storage import upload_text

    client = TDXClient(settings.tdx_client_id, settings.tdx_client_secret)
    result = extract(dataset_name, settings, client, ingested_at)
    upload_text(
        settings.gcp_project_id,
        settings.gcs_bucket,
        result["raw_path"],
        json.dumps(result["records"], ensure_ascii=False),
        "application/json",
    )
    staged_uri = upload_text(
        settings.gcp_project_id,
        settings.gcs_bucket,
        result["staged_path"],
        to_ndjson(result["df"]),
        "application/x-ndjson",
    )
    return {"staged_uri": staged_uri, "row_count": len(result["df"])}


def load_to_bigquery(dataset_name: str, settings: Settings, staged_uri: str) -> int:
    """Airflow 任務 2：把 GCS 上的 NDJSON 以 Append 載入 BigQuery raw 表。"""
    from ingestion.schemas import AVAILABILITY_SCHEMA, STATION_SCHEMA
    from ingestion.storage import load_ndjson_to_bigquery

    schema = AVAILABILITY_SCHEMA if dataset_name == "bike_availability" else STATION_SCHEMA
    table_id = f"{settings.gcp_project_id}.{settings.bq_raw_dataset}.{DATASETS[dataset_name].table}"
    return load_ndjson_to_bigquery(
        settings.gcp_project_id, settings.bq_location, staged_uri, table_id, schema
    )


def extract_to_local(dataset_name: str, settings: Settings, ingested_at: datetime, out_dir: Path) -> Path:
    """本機測試用：不需要 GCP，把同樣的檔案寫到本機資料夾。"""
    client = TDXClient(settings.tdx_client_id, settings.tdx_client_secret)
    result = extract(dataset_name, settings, client, ingested_at)
    raw_file = out_dir / result["raw_path"]
    staged_file = out_dir / result["staged_path"]
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(json.dumps(result["records"], ensure_ascii=False, indent=2), encoding="utf-8")
    staged_file.write_text(to_ndjson(result["df"]), encoding="utf-8")
    print(result["df"].head(10).to_string())
    return staged_file

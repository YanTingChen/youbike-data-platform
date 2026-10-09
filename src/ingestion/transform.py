"""攤平 TDX 資料並統一型態與 UTC 時間。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd


class SchemaError(ValueError):
    """API 回傳缺少必要欄位時拋出，讓 Airflow 任務失敗並告警，而不是寫入壞資料。"""


# TDX 即時車況欄位 → 我們的欄位名稱（巢狀欄位以底線攤平）
AVAILABILITY_FIELDS: dict[str, str] = {
    "StationUID": "station_uid",
    "StationID": "station_id",
    "ServiceType": "service_type",  # 1 = YouBike 1.0、2 = YouBike 2.0
    "ServiceStatus": "service_status",  # 0 = 停止營運、1 = 正常營運、2 = 暫停營運
    "AvailableRentBikes": "bikes_available",  # 可借車數
    "AvailableReturnBikes": "docks_available",  # 可還空位數
    "AvailableRentBikesDetail_GeneralBikes": "general_bikes_available",
    "AvailableRentBikesDetail_ElectricBikes": "ebikes_available",
    "SrcUpdateTime": "source_updated_at",  # 來源系統更新時間
    "UpdateTime": "api_updated_at",  # TDX 平台更新時間
}
AVAILABILITY_REQUIRED = ("StationUID", "AvailableRentBikes", "AvailableReturnBikes", "SrcUpdateTime")
AVAILABILITY_INT_COLUMNS = (
    "service_type",
    "service_status",
    "bikes_available",
    "docks_available",
    "general_bikes_available",
    "ebikes_available",
)

# TDX 站點基本資料欄位
STATION_FIELDS: dict[str, str] = {
    "StationUID": "station_uid",
    "StationID": "station_id",
    "AuthorityID": "authority_id",
    "StationName_Zh_tw": "station_name",
    "StationName_En": "station_name_en",
    "StationAddress_Zh_tw": "address",
    "StationAddress_En": "address_en",
    "StationPosition_PositionLat": "lat",
    "StationPosition_PositionLon": "lng",
    "BikesCapacity": "capacity",  # 總車位數
    "ServiceType": "service_type",
    "SrcUpdateTime": "source_updated_at",
    "UpdateTime": "api_updated_at",
}
STATION_REQUIRED = (
    "StationUID",
    "StationName_Zh_tw",
    "StationPosition_PositionLat",
    "StationPosition_PositionLon",
)
STATION_INT_COLUMNS = ("capacity", "service_type")
STATION_FLOAT_COLUMNS = ("lat", "lng")

TIMESTAMP_COLUMNS = ("source_updated_at", "api_updated_at")


def _normalize(
    records: list[dict[str, Any]],
    fields: dict[str, str],
    required: tuple[str, ...],
    city: str,
    ingested_at: datetime,
) -> pd.DataFrame:
    output_columns = [*fields.values(), "city", "ingested_at"]
    if not records:
        return pd.DataFrame(columns=output_columns)

    df = pd.json_normalize(records, sep="_")
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SchemaError(f"TDX 回傳缺少必要欄位：{missing}，實際欄位：{sorted(df.columns)}")

    # 只保留對照表中的欄位；選用欄位不存在時補空值
    df = df.reindex(columns=list(fields)).rename(columns=fields)
    df = df[df["station_uid"].notna()].copy()

    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce", format="ISO8601")

    df["city"] = city
    df["ingested_at"] = pd.Timestamp(ingested_at).tz_convert(UTC)
    return df[output_columns].reset_index(drop=True)


def normalize_availability(records: list[dict[str, Any]], city: str, ingested_at: datetime) -> pd.DataFrame:
    """即時車況 → 一列一站的 DataFrame。"""
    df = _normalize(records, AVAILABILITY_FIELDS, AVAILABILITY_REQUIRED, city, ingested_at)
    for col in AVAILABILITY_INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def normalize_stations(records: list[dict[str, Any]], city: str, ingested_at: datetime) -> pd.DataFrame:
    """站點基本資料 → 一列一站的 DataFrame。"""
    df = _normalize(records, STATION_FIELDS, STATION_REQUIRED, city, ingested_at)
    for col in STATION_INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in STATION_FLOAT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def display_station_name(name: Any) -> str:
    """來源站名都帶「YouBike2.0_」前綴，顯示時不需要。"""
    return str(name or "").removeprefix("YouBike2.0_")


def to_ndjson(df: pd.DataFrame) -> str:
    """轉成 BigQuery 載入用的 NDJSON（一行一筆），時間輸出為 ISO 8601 UTC。"""
    if df.empty:
        return ""
    out = df.copy()
    for col in out.columns:
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return out.to_json(orient="records", lines=True, force_ascii=False)


def utc_now() -> datetime:
    return datetime.now(UTC)

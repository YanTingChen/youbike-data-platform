"""資料清洗邏輯的單元測試（範例資料為示意，欄位結構依 TDX Bike API 規格）。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from ingestion.pipeline import build_object_paths
from ingestion.transform import SchemaError, normalize_availability, normalize_stations, to_ndjson

FIXTURES = Path(__file__).parent / "fixtures"
INGESTED_AT = datetime(2026, 10, 7, 11, 45, 0, tzinfo=UTC)


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_availability_flattens_and_casts_types():
    df = normalize_availability(load("tdx_bike_availability_sample.json"), "Taichung", INGESTED_AT)

    assert len(df) == 2
    first = df.iloc[0]
    assert first["station_uid"] == "TXG500601001"
    assert first["bikes_available"] == 5
    assert first["ebikes_available"] == 1
    assert str(df["bikes_available"].dtype) == "Int64"
    # 字串數字也會轉成整數
    assert df.iloc[1]["docks_available"] == 20


def test_availability_converts_taipei_time_to_utc():
    df = normalize_availability(load("tdx_bike_availability_sample.json"), "Taichung", INGESTED_AT)

    assert df.iloc[0]["source_updated_at"] == pd.Timestamp("2026-10-07T11:41:02Z")
    assert df.iloc[0]["ingested_at"] == pd.Timestamp(INGESTED_AT)
    assert df["city"].unique().tolist() == ["Taichung"]


def test_missing_optional_nested_field_becomes_null():
    df = normalize_availability(load("tdx_bike_availability_sample.json"), "Taichung", INGESTED_AT)
    assert pd.isna(df.iloc[1]["general_bikes_available"])


def test_missing_required_field_raises():
    records = [{"StationUID": "X", "AvailableRentBikes": 1}]
    with pytest.raises(SchemaError):
        normalize_availability(records, "Taichung", INGESTED_AT)


def test_empty_response_returns_empty_frame():
    df = normalize_availability([], "Taichung", INGESTED_AT)
    assert df.empty
    assert "station_uid" in df.columns


def test_stations_flatten_nested_name_and_position():
    df = normalize_stations(load("tdx_bike_stations_sample.json"), "Taichung", INGESTED_AT)

    row = df.iloc[0]
    assert row["station_name"] == "YouBike2.0_臺中火車站"
    assert row["lat"] == pytest.approx(24.13741)
    assert row["lng"] == pytest.approx(120.68566)
    assert row["capacity"] == 20


def test_ndjson_is_bigquery_friendly():
    df = normalize_availability(load("tdx_bike_availability_sample.json"), "Taichung", INGESTED_AT)
    lines = to_ndjson(df).strip().splitlines()

    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["source_updated_at"] == "2026-10-07T11:41:02.000000Z"
    assert first["ingested_at"] == "2026-10-07T11:45:00.000000Z"
    assert json.loads(lines[1])["general_bikes_available"] is None


def test_object_paths_partition_by_taipei_date_and_hour():
    # UTC 2026-10-07 17:30 是當地的 2026-10-08 01:30，日期分區應該是 10/08
    ts = datetime(2026, 10, 7, 17, 30, tzinfo=UTC)
    raw, staged = build_object_paths("bike_availability", "Taichung", ts)

    assert raw == "raw/tdx/bike_availability/city=Taichung/dt=2026-10-08/hour=01/20261007T173000Z.json"
    assert staged.startswith("staged/tdx/bike_availability/city=Taichung/dt=2026-10-08/hour=01/")
    assert staged.endswith(".ndjson")

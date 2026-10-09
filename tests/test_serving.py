"""資料快照的單元測試：格式整理與 SQL 範本（不需要連 BigQuery）。"""

import json
import re
from datetime import UTC, datetime

from serving.snapshot import build_snapshot, render_sql, to_json

GENERATED_AT = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


def row(**overrides):
    base = {
        "station_uid": "TXG500601001",
        "station_name": "YouBike2.0_臺中火車站",
        "lat": 24.1374123,
        "lng": 120.6856678,
        "bikes_available": 5,
        "docks_available": 15,
        "in_service": True,
        "forecast_for": None,
        "predicted_bikes_available": None,
    }
    return {**base, **overrides}


def test_snapshot_uses_short_keys_and_strips_name_prefix():
    snapshot = build_snapshot([row()], GENERATED_AT)

    assert snapshot["generated_at"] == "2026-10-08T12:00:00Z"
    assert snapshot["stations"] == [
        {
            "id": "TXG500601001",
            "name": "臺中火車站",
            "lat": 24.13741,
            "lng": 120.68567,
            "bikes": 5,
            "docks": 15,
            "in_service": True,
        }
    ]


def test_forecast_is_included_only_when_present():
    forecast_for = datetime(2026, 10, 8, 13, 0, 0, tzinfo=UTC)
    with_forecast, without = build_snapshot(
        [row(forecast_for=forecast_for, predicted_bikes_available=3.24), row(station_uid="B")],
        GENERATED_AT,
    )["stations"]

    assert with_forecast["forecast"] == {"at": "2026-10-08T13:00:00Z", "bikes": 3.2}
    # 沒有預測的站點不輸出這個欄位，網頁以「有沒有這個欄位」判斷
    assert "forecast" not in without


def test_json_keeps_chinese_readable_and_compact():
    text = to_json(build_snapshot([row()], GENERATED_AT))

    assert "臺中火車站" in text
    assert ", " not in text and ": " not in text
    assert json.loads(text)["stations"][0]["bikes"] == 5


def test_sql_reads_tables_from_the_configured_datasets():
    sql = render_sql("my-project", "youbike_raw", "analytics", include_forecasts=True)

    assert "`my-project.youbike_raw.bike_availability`" in sql
    assert "`my-project.analytics_marts.dim_bike_station`" in sql
    assert "`my-project.analytics_ml.station_forecasts`" in sql
    assert not re.search(r"[{}]", sql)


def test_sql_without_forecast_table_does_not_reference_it():
    # 模型還沒訓練過時預測表不存在，查詢不能去讀它
    sql = render_sql("my-project", "youbike_raw", "youbike", include_forecasts=False)

    assert "station_forecasts" not in sql
    assert not re.search(r"[{}]", sql)

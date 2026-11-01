"""把站點名稱同步到 PostgreSQL，讓儀表板顯示站名而不是站點代碼。

串流的訊息只帶站點代碼；站名是很少變動的參考資料，每天同步一次即可，不必跟著每則訊息走。
資料取自批次擷取每天存進 GCS 的站點檔案，不另外呼叫 TDX。
"""

from __future__ import annotations

import json
import logging
import signal
import threading
from collections.abc import Iterable, Mapping
from typing import Any

from ingestion.config import Settings
from ingestion.transform import display_station_name, utc_now
from streaming import lake
from streaming.config import StreamSettings

logger = logging.getLogger(__name__)

RETRY_SECONDS = 300


def station_rows(records: Iterable[Mapping[str, Any]]) -> list[tuple]:
    """清洗後的站點資料 → 寫入 stations 表的列，順序同 sink.STATION_COLUMNS。"""
    return [
        (
            record["station_uid"],
            display_station_name(record.get("station_name")),
            None if record.get("lat") is None else float(record["lat"]),
            None if record.get("lng") is None else float(record["lng"]),
            None if record.get("capacity") is None else int(record["capacity"]),
        )
        for record in records
        if record.get("station_uid")
    ]


def sync(storage_client, settings: Settings, stream: StreamSettings) -> int:
    from streaming import sink  # 用到資料庫時才載入驅動程式，單元測試不需要安裝

    blob = lake.latest_staged(storage_client, settings.gcs_bucket, "bike_stations", settings.city, utc_now())
    if blob is None:
        raise RuntimeError("GCS 上還沒有站點資料，等批次擷取執行後再試")
    rows = station_rows(json.loads(line) for line in blob.download_as_text().splitlines() if line)
    sink.ensure_schema(stream)
    sink.upsert_stations(stream, rows)
    return len(rows)


def main() -> None:
    from google.cloud import storage

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = Settings.from_env()
    stream = StreamSettings.from_env()
    storage_client = storage.Client(project=settings.gcp_project_id)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    while not stop.is_set():
        try:
            logger.info("已同步 %d 個站點", sync(storage_client, settings, stream))
            wait_seconds = stream.stations_refresh_hours * 3600
        except Exception:
            # 資料庫或 GCS 暫時無法使用時，過幾分鐘再試，不必等到明天
            logger.exception("站點同步失敗，%d 秒後重試", RETRY_SECONDS)
            wait_seconds = RETRY_SECONDS
        stop.wait(wait_seconds)


if __name__ == "__main__":
    main()

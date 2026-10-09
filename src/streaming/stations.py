"""把站點名稱同步到 PostgreSQL，讓儀表板顯示站名而不是站點代碼。

串流的訊息只帶站點代碼；站名是很少變動的參考資料，每天同步一次即可，不必跟著每則訊息走。
"""

from __future__ import annotations

import logging
import signal
import threading

import pandas as pd

from ingestion.config import Settings
from ingestion.tdx_client import TDXClient
from ingestion.transform import display_station_name, normalize_stations, utc_now
from streaming.config import StreamSettings

logger = logging.getLogger(__name__)

RETRY_SECONDS = 300


def station_rows(df: pd.DataFrame) -> list[tuple]:
    """清洗後的站點資料 → 寫入 stations 表的列，順序同 sink.STATION_COLUMNS。"""
    return [
        (
            row.station_uid,
            display_station_name(row.station_name),
            None if pd.isna(row.lat) else float(row.lat),
            None if pd.isna(row.lng) else float(row.lng),
            None if pd.isna(row.capacity) else int(row.capacity),
        )
        for row in df.itertuples(index=False)
    ]


def sync(client: TDXClient, city: str, stream: StreamSettings) -> int:
    from streaming import sink  # 用到資料庫時才載入驅動程式，單元測試不需要安裝

    df = normalize_stations(client.get_bike_stations(city), city, utc_now())
    rows = station_rows(df)
    sink.ensure_schema(stream)
    sink.upsert_stations(stream, rows)
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = Settings.from_env(require_gcp=False)
    stream = StreamSettings.from_env()
    client = TDXClient(settings.tdx_client_id, settings.tdx_client_secret)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    while not stop.is_set():
        try:
            logger.info("已同步 %d 個站點", sync(client, settings.city, stream))
            wait_seconds = stream.stations_refresh_hours * 3600
        except Exception:
            # 資料庫還沒準備好或 API 暫時失敗時，過幾分鐘再試，不必等到明天
            logger.exception("站點同步失敗，%d 秒後重試", RETRY_SECONDS)
            wait_seconds = RETRY_SECONDS
        stop.wait(wait_seconds)


if __name__ == "__main__":
    main()

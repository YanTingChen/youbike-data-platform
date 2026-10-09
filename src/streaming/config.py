"""串流設定：全部從環境變數讀取，預設值對應 docker-compose 的 streaming profile。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, "").strip() or default)


@dataclass(frozen=True)
class StreamSettings:
    kafka_bootstrap_servers: str
    kafka_topic: str
    # Producer 輪詢 TDX 的間隔。來源約每分鐘整批更新一次，抓得更快只會拿到重複資料
    poll_interval_seconds: int
    # 視窗長度與 watermark（可容忍的事件時間延遲）；視窗結果在「視窗結束 + watermark」後才會輸出
    window_minutes: int
    watermark_minutes: int
    trigger_seconds: int
    # 站點名稱多久重新同步一次
    stations_refresh_hours: int
    checkpoint_dir: str
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str

    @classmethod
    def from_env(cls) -> StreamSettings:
        return cls(
            kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
            kafka_topic=os.environ.get("KAFKA_TOPIC", "youbike.bike_availability"),
            poll_interval_seconds=_int("STREAM_POLL_INTERVAL_SECONDS", 60),
            window_minutes=_int("STREAM_WINDOW_MINUTES", 10),
            watermark_minutes=_int("STREAM_WATERMARK_MINUTES", 10),
            trigger_seconds=_int("STREAM_TRIGGER_SECONDS", 30),
            stations_refresh_hours=_int("STREAM_STATIONS_REFRESH_HOURS", 24),
            checkpoint_dir=os.environ.get("STREAM_CHECKPOINT_DIR", "/checkpoints"),
            pg_host=os.environ.get("STREAM_PG_HOST", "postgres"),
            pg_port=_int("STREAM_PG_PORT", 5432),
            pg_user=os.environ.get("STREAM_PG_USER", "airflow"),
            pg_password=os.environ.get("STREAM_PG_PASSWORD", ""),
            pg_database=os.environ.get("STREAM_PG_DATABASE", "youbike_streaming"),
        )

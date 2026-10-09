"""確認 Kafka 寫入後才更新已送紀錄；重啟後由下游去重。"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from typing import NamedTuple

import pandas as pd

from ingestion.config import Settings
from ingestion.tdx_client import TDXClient
from ingestion.transform import normalize_availability, to_ndjson, utc_now
from streaming.config import StreamSettings
from streaming.metrics import ProducerMetrics, start_metrics_server

logger = logging.getLogger(__name__)


class Message(NamedTuple):
    key: str  # station_uid
    value: bytes  # JSON
    source_updated_at: str


def select_changed(df: pd.DataFrame, seen: dict[str, str]) -> list[Message]:
    """從清洗後的車況挑出來源有更新的站點，轉成 Kafka 訊息。沒有來源更新時間的列無法定事件時間，略過。"""
    messages = []
    for line in to_ndjson(df).splitlines():
        record = json.loads(line)
        uid, updated_at = record["station_uid"], record["source_updated_at"]
        # 時間是固定格式的 UTC ISO 字串，可以直接比字串
        if updated_at is None or updated_at <= seen.get(uid, ""):
            continue
        messages.append(Message(uid, line.encode("utf-8"), updated_at))
    return messages


def publish(producer, topic: str, messages: list[Message], seen: dict[str, str]) -> int:
    """送出訊息並等待 Kafka 確認；確認成功的才記進 seen。回傳確認成功的則數。"""
    delivered = 0

    def on_delivery(message: Message):
        def callback(err, _msg) -> None:
            nonlocal delivered
            if err is not None:
                logger.error("送出失敗 %s：%s", message.key, err)
            else:
                seen[message.key] = message.source_updated_at
                delivered += 1

        return callback

    for message in messages:
        producer.produce(topic, key=message.key, value=message.value, on_delivery=on_delivery(message))
        producer.poll(0)  # 觸發已完成的 callback，避免內部佇列堆積
    producer.flush()
    return delivered


def main() -> None:
    from confluent_kafka import Producer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = Settings.from_env(require_gcp=False)
    stream = StreamSettings.from_env()

    client = TDXClient(settings.tdx_client_id, settings.tdx_client_secret)
    producer = Producer(
        {
            "bootstrap.servers": stream.kafka_bootstrap_servers,
            "client.id": "youbike-producer",
            # 冪等 Producer：重試不會在 Kafka 內產生重複訊息，也不會打亂同一 partition 的順序
            "enable.idempotence": True,
            "compression.type": "lz4",
        }
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    start_metrics_server()
    metrics = ProducerMetrics()
    seen: dict[str, str] = {}
    logger.info("開始輪詢：每 %d 秒，topic=%s", stream.poll_interval_seconds, stream.kafka_topic)
    while not stop.is_set():
        started = time.monotonic()
        try:
            records = client.get_bike_availability(settings.city)
            df = normalize_availability(records, settings.city, utc_now())
            messages = select_changed(df, seen)
            delivered = publish(producer, stream.kafka_topic, messages, seen)
            logger.info("API 回傳 %d 站，送出 %d 則有更新的訊息", len(df), delivered)

            metrics.stations.set(len(df))
            metrics.messages_sent.inc(delivered)
            metrics.delivery_failures.inc(len(messages) - delivered)
            if df["source_updated_at"].notna().any():
                metrics.source_updated.set(df["source_updated_at"].max().timestamp())
            if delivered < len(messages):
                raise RuntimeError(f"{len(messages) - delivered} 則訊息未能寫入 Kafka")
            metrics.polls.labels("success").inc()
            metrics.last_success.set_to_current_time()
        except Exception:
            metrics.polls.labels("failure").inc()
            logger.exception("本輪輪詢失敗，下一輪重試")
        metrics.poll_duration.set(time.monotonic() - started)
        stop.wait(max(0.0, stream.poll_interval_seconds - (time.monotonic() - started)))

    producer.flush()
    logger.info("已停止")


if __name__ == "__main__":
    main()

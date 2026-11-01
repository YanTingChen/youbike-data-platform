"""把批次擷取存進 GCS 的最新車況送進 Kafka。

不直接呼叫 TDX：整個平台只由批次擷取呼叫 API，免費額度才夠用。
確認 Kafka 寫入後才更新已送紀錄；重啟後會重送最新一份，由下游去重。
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

from ingestion.config import Settings
from ingestion.transform import utc_now
from streaming import lake
from streaming.config import StreamSettings
from streaming.metrics import ProducerMetrics, start_metrics_server

logger = logging.getLogger(__name__)


class Message(NamedTuple):
    key: str  # station_uid
    value: bytes  # JSON
    source_updated_at: str


def select_changed(lines: Iterable[str], seen: dict[str, str]) -> list[Message]:
    """從清洗後的車況（NDJSON，一行一站）挑出來源有更新的站點，轉成 Kafka 訊息。

    沒有來源更新時間的列無法定事件時間，略過。
    """
    messages = []
    for line in lines:
        if not line:
            continue
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
    from google.cloud import storage

    settings = Settings.from_env()
    stream = StreamSettings.from_env()

    storage_client = storage.Client(project=settings.gcp_project_id)
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
    last_file = None  # 已經送完的最新檔案，沒有新檔案時不重複讀取
    logger.info("開始檢查 GCS：每 %d 秒，topic=%s", stream.poll_interval_seconds, stream.kafka_topic)
    while not stop.is_set():
        started = time.monotonic()
        try:
            blob = lake.latest_staged(
                storage_client, settings.gcs_bucket, "bike_availability", settings.city, utc_now()
            )
            if blob is not None and blob.name != last_file:
                lines = blob.download_as_text().splitlines()
                messages = select_changed(lines, seen)
                delivered = publish(producer, stream.kafka_topic, messages, seen)
                logger.info(
                    "%s：%d 站，送出 %d 則有更新的訊息", blob.name.rsplit("/", 1)[-1], len(lines), delivered
                )

                metrics.stations.set(len(lines))
                metrics.messages_sent.inc(delivered)
                metrics.delivery_failures.inc(len(messages) - delivered)
                if messages:
                    newest = max(message.source_updated_at for message in messages)
                    metrics.source_updated.set(datetime.fromisoformat(newest).timestamp())
                if delivered < len(messages):
                    raise RuntimeError(f"{len(messages) - delivered} 則訊息未能寫入 Kafka")
                last_file = blob.name
            metrics.polls.labels("success").inc()
            metrics.last_success.set_to_current_time()
        except Exception:
            metrics.polls.labels("failure").inc()
            logger.exception("本輪處理失敗，下一輪重試")
        metrics.poll_duration.set(time.monotonic() - started)
        stop.wait(max(0.0, stream.poll_interval_seconds - (time.monotonic() - started)))

    producer.flush()
    logger.info("已停止")


if __name__ == "__main__":
    main()

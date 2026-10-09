"""Prometheus 指標：Producer 與 Spark 串流各自在容器內開一個 /metrics 端點給 Prometheus 抓取。

命名慣例：youbike_<元件>_<量>_<單位>；時間點一律用 Unix 秒，
「多久沒更新」交給查詢端用 time() - 指標 計算，程式停住時數值才會持續變大而被告警抓到。

指標包在類別裡、由各行程自己建立，而不是放在模組層級：
模組層級的指標一 import 就會註冊，Spark 行程會連 Producer 的指標一起以 0 暴露出去，造成告警誤判。
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Gauge, start_http_server


class ProducerMetrics:
    def __init__(self) -> None:
        self.polls = Counter("youbike_producer_polls_total", "TDX 輪詢次數", ["result"])
        self.messages_sent = Counter("youbike_producer_messages_sent_total", "Kafka 確認寫入的訊息數")
        self.delivery_failures = Counter("youbike_producer_delivery_failures_total", "Kafka 寫入失敗的訊息數")
        self.last_success = Gauge(
            "youbike_producer_last_success_timestamp_seconds", "最近一次輪詢並送出成功的時間"
        )
        self.stations = Gauge("youbike_producer_stations", "最近一次 API 回傳的站點數")
        self.poll_duration = Gauge("youbike_producer_poll_duration_seconds", "最近一次輪詢到送出完成的耗時")
        self.source_updated = Gauge(
            "youbike_producer_source_updated_timestamp_seconds", "最近一次 API 回傳資料中最新的來源更新時間"
        )


class StreamMetrics:
    """Spark Structured Streaming 的指標，每條查詢一組，以 query 標籤區分。"""

    def __init__(self) -> None:
        self.input_rows = Gauge(
            "youbike_stream_batch_input_rows", "最近一個 micro-batch 讀入的列數", ["query"]
        )
        self.batch_duration = Gauge(
            "youbike_stream_batch_duration_seconds", "最近一個 micro-batch 的處理耗時", ["query"]
        )
        self.last_progress = Gauge(
            "youbike_stream_last_progress_timestamp_seconds",
            "查詢最近一次回報進度（含閒置）的時間",
            ["query"],
        )
        self.max_event_time = Gauge(
            "youbike_stream_max_event_timestamp_seconds", "已處理資料中最新的事件時間", ["query"]
        )
        self.watermark = Gauge("youbike_stream_watermark_timestamp_seconds", "目前的 watermark", ["query"])
        self.kafka_lag = Gauge(
            "youbike_stream_kafka_offsets_behind_latest",
            "落後 Kafka 最新 offset 最多的 partition 差幾則",
            ["query"],
        )
        self.rows_written = Counter("youbike_stream_rows_written_total", "寫入 PostgreSQL 的列數", ["query"])
        self.last_write = Gauge(
            "youbike_stream_last_write_timestamp_seconds", "最近一次寫入 PostgreSQL 的時間", ["query"]
        )


def start_metrics_server() -> None:
    start_http_server(int(os.environ.get("STREAM_METRICS_PORT", "8000")))

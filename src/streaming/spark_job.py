"""Spark Structured Streaming：Kafka 即時車況 → 視窗聚合與空站／滿站偵測 → PostgreSQL。

用法（容器內）：python -m streaming.spark_job

同一個來源開兩條查詢，各有自己的 checkpoint，重啟後從上次的 offset 與狀態接續：

1. window_stats：每站、每個視窗的可借車數統計
   - 事件時間用 source_updated_at（來源更新時間），不是我們收到訊息的時間
   - watermark：超過容忍延遲的遲到資料直接丟棄，Spark 才能關閉舊視窗、釋放狀態
   - dropDuplicatesWithinWatermark：Producer 是至少一次，重送的訊息在這裡去重
   - append 模式：視窗在「結束時間 + watermark」之後定案才輸出一次
2. status_events：以 applyInPandasWithState 為每個站點保存目前狀態，只在狀態改變時輸出事件

以 local 模式執行：全台中約 1,800 站、每分鐘一批，單機就綽綽有餘，不需要叢集。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pyspark
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQueryListener
from pyspark.sql.streaming.state import GroupState, GroupStateTimeout
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType, TimestampType

from streaming import sink
from streaming.config import StreamSettings
from streaming.detection import Observation, StationState, detect_transitions
from streaming.metrics import StreamMetrics, start_metrics_server

logger = logging.getLogger(__name__)

# Kafka 連接器版本必須與 Spark 一致
KAFKA_PACKAGE = f"org.apache.spark:spark-sql-kafka-0-10_2.13:{pyspark.__version__}"

# Kafka 訊息（JSON）的欄位，與 Producer 送出的一致；只列出串流用得到的欄位
MESSAGE_SCHEMA = StructType(
    [
        StructField("station_uid", StringType()),
        StructField("service_status", IntegerType()),
        StructField("bikes_available", IntegerType()),
        StructField("docks_available", IntegerType()),
        StructField("source_updated_at", TimestampType()),
    ]
)

STATUS_EVENT_SCHEMA = StructType(
    [
        StructField("station_uid", StringType()),
        StructField("status", StringType()),
        StructField("previous_status", StringType()),
        StructField("changed_at", TimestampType()),
        StructField("previous_duration_seconds", LongType()),
        StructField("bikes_available", IntegerType()),
        StructField("docks_available", IntegerType()),
    ]
)

# 每個站點保存的狀態；時間以 epoch 微秒存成整數，避免時區轉換的歧義
STATION_STATE_SCHEMA = StructType(
    [
        StructField("status", StringType()),
        StructField("since_us", LongType()),
        StructField("last_seen_us", LongType()),
    ]
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MICROSECOND = timedelta(microseconds=1)


def _to_micros(value: datetime) -> int:
    return (value - EPOCH) // MICROSECOND


def _from_micros(value: int) -> datetime:
    return EPOCH + value * MICROSECOND


def _as_utc(value: pd.Timestamp) -> datetime:
    # Spark 交給 pandas 的時間不帶時區，值是 session 時區（已設為 UTC）
    ts = value if value.tzinfo else value.tz_localize(UTC)
    return ts.to_pydatetime()


def detect_station_events(
    key: tuple, pdfs: Iterator[pd.DataFrame], state: GroupState
) -> Iterator[pd.DataFrame]:
    """applyInPandasWithState 的處理函式：一個站點、一個 micro-batch 呼叫一次。"""
    (station_uid,) = key
    previous = None
    if state.exists:
        status, since_us, last_seen_us = state.get
        previous = StationState(status, _from_micros(since_us), _from_micros(last_seen_us))

    observations = [
        Observation(
            updated_at=_as_utc(row.source_updated_at),
            bikes_available=int(row.bikes_available),
            docks_available=int(row.docks_available),
            service_status=None if pd.isna(row.service_status) else int(row.service_status),
        )
        for pdf in pdfs
        for row in pdf.itertuples(index=False)
    ]
    current, events = detect_transitions(station_uid, previous, observations)
    if current is not None:
        state.update((current.status, _to_micros(current.since), _to_micros(current.last_seen)))

    if events:
        out = pd.DataFrame([vars(e) for e in events], columns=STATUS_EVENT_SCHEMA.names)
        out["previous_duration_seconds"] = out["previous_duration_seconds"].astype("Int64")
        yield out


class MetricsListener(StreamingQueryListener):
    """把每條查詢的進度轉成 Prometheus 指標。Spark 在每個 micro-batch 結束後呼叫 onQueryProgress。"""

    def __init__(self, metrics: StreamMetrics) -> None:
        super().__init__()
        self._metrics = metrics
        self._names: dict[str, str] = {}  # 查詢 id → 名稱（idle 事件只帶 id）

    def onQueryStarted(self, event) -> None:
        self._names[str(event.id)] = event.name

    def onQueryProgress(self, event) -> None:
        progress = event.progress
        name = progress.name
        self._metrics.last_progress.labels(name).set_to_current_time()
        self._metrics.input_rows.labels(name).set(progress.numInputRows)
        self._metrics.batch_duration.labels(name).set(progress.batchDuration / 1000)

        # eventTime 只在該批有資料時才有 max；watermark 在第一批之後才有
        event_time = progress.eventTime or {}
        if "max" in event_time:
            self._metrics.max_event_time.labels(name).set(_epoch_seconds(event_time["max"]))
        if "watermark" in event_time:
            self._metrics.watermark.labels(name).set(_epoch_seconds(event_time["watermark"]))

        lags = [
            float(source.metrics["maxOffsetsBehindLatest"])
            for source in progress.sources
            if "maxOffsetsBehindLatest" in (source.metrics or {})
        ]
        if lags:
            self._metrics.kafka_lag.labels(name).set(max(lags))

    def onQueryIdle(self, event) -> None:
        # 沒有新資料時 Spark 不送 progress 只送 idle；也算查詢還活著
        name = self._names.get(str(event.id))
        if name:
            self._metrics.last_progress.labels(name).set_to_current_time()

    def onQueryTerminated(self, event) -> None:
        pass


def _epoch_seconds(iso_timestamp: str) -> float:
    return datetime.fromisoformat(iso_timestamp).timestamp()


def read_observations(spark: SparkSession, settings: StreamSettings) -> DataFrame:
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka_bootstrap_servers)
        .option("subscribe", settings.kafka_topic)
        .option("startingOffsets", "earliest")
        # 串流停太久、Kafka 已依保留期限刪掉舊訊息時，從現有最早的訊息繼續，而不是讓查詢失敗
        .option("failOnDataLoss", "false")
        .load()
    )
    return (
        raw.select(F.from_json(F.col("value").cast("string"), MESSAGE_SCHEMA).alias("r"))
        .select("r.*")
        .where(
            F.col("station_uid").isNotNull()
            & F.col("source_updated_at").isNotNull()
            & F.col("bikes_available").isNotNull()
            & F.col("docks_available").isNotNull()
        )
        .withWatermark("source_updated_at", f"{settings.watermark_minutes} minutes")
    )


def build_window_stats(observations: DataFrame, settings: StreamSettings) -> DataFrame:
    return (
        observations.dropDuplicatesWithinWatermark(["station_uid", "source_updated_at"])
        .where(F.col("service_status") == 1)  # 與 mart_station_hourly 一致，只統計營運中的站點
        .groupBy(F.window("source_updated_at", f"{settings.window_minutes} minutes"), "station_uid")
        .agg(
            F.count("*").cast("int").alias("observations"),
            F.round(F.avg("bikes_available"), 2).alias("avg_bikes_available"),
            F.min("bikes_available").alias("min_bikes_available"),
            F.max("bikes_available").alias("max_bikes_available"),
            F.round(F.avg("docks_available"), 2).alias("avg_docks_available"),
            F.count(F.when(F.col("bikes_available") == 0, 1)).cast("int").alias("empty_observations"),
            F.count(F.when(F.col("docks_available") == 0, 1)).cast("int").alias("full_observations"),
        )
        .select(
            "station_uid",
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            *sink.WINDOW_STATS_COLUMNS[3:],
        )
    )


def build_status_events(observations: DataFrame) -> DataFrame:
    return observations.groupBy("station_uid").applyInPandasWithState(
        detect_station_events,
        STATUS_EVENT_SCHEMA,
        STATION_STATE_SCHEMA,
        "append",
        GroupStateTimeout.NoTimeout,
    )


def start_query(
    df: DataFrame,
    name: str,
    columns: tuple[str, ...],
    write,
    settings: StreamSettings,
    metrics: StreamMetrics,
):
    def write_batch(batch_df: DataFrame, batch_id: int) -> None:
        # 每批最多幾千列，直接收回 driver 寫入即可
        rows = [tuple(row) for row in batch_df.select(*columns).collect()]
        write(settings, rows)
        if rows:
            logger.info("%s：批次 %d 寫入 %d 列", name, batch_id, len(rows))
            metrics.rows_written.labels(name).inc(len(rows))
            metrics.last_write.labels(name).set_to_current_time()

    # 先把計數器建成 0：Prometheus 的 increase() 需要看到起點，否則第一次寫入的量會算不到
    metrics.rows_written.labels(name)

    return (
        df.writeStream.queryName(name)
        .foreachBatch(write_batch)
        .option("checkpointLocation", f"{settings.checkpoint_dir}/{name}")
        .trigger(processingTime=f"{settings.trigger_seconds} seconds")
        .start()
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    logging.getLogger("py4j").setLevel(logging.WARNING)  # 每個 micro-batch 都會印，太吵
    settings = StreamSettings.from_env()
    sink.ensure_schema(settings)

    spark = (
        SparkSession.builder.appName("youbike-streaming")
        .master("local[2]")
        .config("spark.jars.packages", KAFKA_PACKAGE)
        .config("spark.driver.memory", "1g")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.session.timeZone", "UTC")
        # 預設 200 個 shuffle partition 對這個資料量太多，每個都要維護一份狀態檔
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    start_metrics_server()
    metrics = StreamMetrics()
    spark.streams.addListener(MetricsListener(metrics))

    observations = read_observations(spark, settings)
    start_query(
        build_window_stats(observations, settings),
        "window_stats",
        sink.WINDOW_STATS_COLUMNS,
        sink.upsert_window_stats,
        settings,
        metrics,
    )
    start_query(
        build_status_events(observations),
        "status_events",
        sink.STATUS_EVENT_COLUMNS,
        sink.insert_status_events,
        settings,
        metrics,
    )
    logger.info(
        "串流已啟動：視窗 %d 分鐘、watermark %d 分鐘", settings.window_minutes, settings.watermark_minutes
    )
    # 任一條查詢失敗就結束行程，交給容器重啟後從 checkpoint 接續
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()

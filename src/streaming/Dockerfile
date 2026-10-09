# 串流映像：Kafka Producer 與 Spark Structured Streaming 共用
# 以 Python 映像為基礎加裝 JRE，PySpark 以 local 模式執行，不需要另外架 Spark 叢集
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
 && rm -rf /var/lib/apt/lists/*

COPY src/streaming/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 先建好 checkpoint 目錄並交給一般使用者，掛上 named volume 時才會沿用這個擁有者
RUN useradd --create-home app && mkdir /checkpoints && chown app /checkpoints
USER app
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 TZ=UTC

# 建置時先把 Kafka 連接器下載進 ivy 快取，容器啟動時就不必再連 Maven
RUN python -c "import pyspark; from pyspark.sql import SparkSession; \
SparkSession.builder.master('local[1]') \
.config('spark.jars.packages', f'org.apache.spark:spark-sql-kafka-0-10_2.13:{pyspark.__version__}') \
.getOrCreate().stop()"

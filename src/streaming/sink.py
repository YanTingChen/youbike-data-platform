"""以主鍵與 ON CONFLICT 保持批次重試的冪等性。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from streaming.config import StreamSettings

DDL = (Path(__file__).parent / "sql" / "schema.sql").read_text(encoding="utf-8")

WINDOW_STATS_COLUMNS = (
    "station_uid",
    "window_start",
    "window_end",
    "observations",
    "avg_bikes_available",
    "min_bikes_available",
    "max_bikes_available",
    "avg_docks_available",
    "empty_observations",
    "full_observations",
)
STATUS_EVENT_COLUMNS = (
    "station_uid",
    "status",
    "previous_status",
    "changed_at",
    "previous_duration_seconds",
    "bikes_available",
    "docks_available",
)

STATION_COLUMNS = ("station_uid", "station_name", "lat", "lng", "capacity")

UPSERT_STATIONS = f"""
insert into stations ({", ".join(STATION_COLUMNS)}) values %s
on conflict (station_uid) do update set
    {", ".join(f"{c} = excluded.{c}" for c in STATION_COLUMNS[1:])},
    updated_at = now()
"""
UPSERT_WINDOW_STATS = f"""
insert into station_window_stats ({", ".join(WINDOW_STATS_COLUMNS)}) values %s
on conflict (station_uid, window_start) do update set
    {", ".join(f"{c} = excluded.{c}" for c in WINDOW_STATS_COLUMNS[2:])},
    updated_at = now()
"""
INSERT_STATUS_EVENTS = f"""
insert into station_status_events ({", ".join(STATUS_EVENT_COLUMNS)}) values %s
on conflict (station_uid, changed_at) do nothing
"""


def _connect(settings: StreamSettings, database: str):
    # 連線時區固定 UTC：Spark 收集回來的時間不帶時區，值是 UTC
    return psycopg2.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=database,
        options="-c timezone=UTC",
    )


def ensure_schema(settings: StreamSettings) -> None:
    """建立串流專用資料庫（與 Airflow 的中繼資料庫分開）與資料表，已存在則略過。"""
    admin = _connect(settings, "postgres")
    try:
        admin.autocommit = True  # create database 不能在交易內執行
        with admin.cursor() as cur:
            cur.execute("select 1 from pg_database where datname = %s", (settings.pg_database,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("create database {}").format(sql.Identifier(settings.pg_database)))
    finally:
        admin.close()

    conn = _connect(settings, settings.pg_database)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
    finally:
        conn.close()


def _write(settings: StreamSettings, statement: str, rows: Sequence[tuple]) -> None:
    if not rows:
        return
    conn = _connect(settings, settings.pg_database)
    try:
        with conn, conn.cursor() as cur:  # with conn：成功 commit、例外 rollback
            execute_values(cur, statement, rows, page_size=1000)
    finally:
        conn.close()


def upsert_window_stats(settings: StreamSettings, rows: Sequence[tuple]) -> None:
    _write(settings, UPSERT_WINDOW_STATS, rows)


def insert_status_events(settings: StreamSettings, rows: Sequence[tuple]) -> None:
    _write(settings, INSERT_STATUS_EVENTS, rows)


def upsert_stations(settings: StreamSettings, rows: Sequence[tuple]) -> None:
    _write(settings, UPSERT_STATIONS, rows)

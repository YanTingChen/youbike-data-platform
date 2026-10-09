"""只輸出狀態轉換，避免同一個空站或滿站重複產生事件。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

NORMAL = "normal"
EMPTY = "empty"  # 無車可借
FULL = "full"  # 無位可還
OUT_OF_SERVICE = "out_of_service"


def classify(bikes_available: int, docks_available: int, service_status: int | None) -> str:
    """與 dbt 的 is_in_service 定義一致：service_status = 1 才算營運中。"""
    if service_status != 1:
        return OUT_OF_SERVICE
    if bikes_available == 0:
        return EMPTY
    if docks_available == 0:
        return FULL
    return NORMAL


@dataclass(frozen=True)
class Observation:
    updated_at: datetime  # 來源更新時間（事件時間）
    bikes_available: int
    docks_available: int
    service_status: int | None


@dataclass(frozen=True)
class StationState:
    status: str
    since: datetime  # 進入目前狀態的時間
    last_seen: datetime  # 已處理過的最新事件時間


@dataclass(frozen=True)
class StatusEvent:
    station_uid: str
    status: str
    previous_status: str | None
    changed_at: datetime
    previous_duration_seconds: int | None  # 前一個狀態持續了多久
    bikes_available: int
    docks_available: int


def detect_transitions(
    station_uid: str, state: StationState | None, observations: Iterable[Observation]
) -> tuple[StationState | None, list[StatusEvent]]:
    """依事件時間處理一個站點的一批觀測，回傳 (新狀態, 狀態轉換事件)。

    - 事件時間不晚於 last_seen 的觀測直接略過：重複送達（Kafka 至少一次）與亂序的舊資料都不會造成誤報
    - 站點第一次出現時，只有非 normal 才產生事件，避免啟動時每個站都寫一筆 normal
    """
    events: list[StatusEvent] = []
    for obs in sorted(observations, key=lambda o: o.updated_at):
        if state is not None and obs.updated_at <= state.last_seen:
            continue

        status = classify(obs.bikes_available, obs.docks_available, obs.service_status)
        if state is not None and status == state.status:
            state = StationState(state.status, state.since, obs.updated_at)
            continue

        if state is not None or status != NORMAL:
            events.append(
                StatusEvent(
                    station_uid=station_uid,
                    status=status,
                    previous_status=state.status if state else None,
                    changed_at=obs.updated_at,
                    previous_duration_seconds=(
                        int((obs.updated_at - state.since).total_seconds()) if state else None
                    ),
                    bikes_available=obs.bikes_available,
                    docks_available=obs.docks_available,
                )
            )
        state = StationState(status, obs.updated_at, obs.updated_at)

    return state, events

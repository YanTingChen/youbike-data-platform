"""串流邏輯的單元測試：狀態轉換偵測與 Producer 的訊息挑選（不需要 Kafka 或 Spark）。"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ingestion.transform import normalize_availability
from streaming.detection import (
    EMPTY,
    FULL,
    NORMAL,
    OUT_OF_SERVICE,
    Observation,
    StationState,
    classify,
    detect_transitions,
)
from streaming.producer import publish, select_changed

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 8, 4, 0, 0, tzinfo=UTC)


def obs(minute: int, bikes: int, docks: int, status: int | None = 1) -> Observation:
    return Observation(T0 + timedelta(minutes=minute), bikes, docks, status)


def test_classify():
    assert classify(3, 10, 1) == NORMAL
    assert classify(0, 13, 1) == EMPTY
    assert classify(13, 0, 1) == FULL
    # 停止營運的站點不算空站或滿站
    assert classify(0, 0, 0) == OUT_OF_SERVICE
    assert classify(5, 5, None) == OUT_OF_SERVICE


def test_first_observation_emits_only_when_not_normal():
    state, events = detect_transitions("A", None, [obs(0, 5, 5)])
    assert events == []
    assert state == StationState(NORMAL, T0, T0)

    state, events = detect_transitions("B", None, [obs(0, 0, 10)])
    assert [(e.status, e.previous_status, e.previous_duration_seconds) for e in events] == [
        (EMPTY, None, None)
    ]


def test_emits_once_per_transition_with_previous_duration():
    state, events = detect_transitions(
        "A", None, [obs(0, 2, 8), obs(1, 0, 10), obs(2, 0, 10), obs(3, 0, 10), obs(4, 1, 9)]
    )

    assert [(e.status, e.previous_status, e.previous_duration_seconds) for e in events] == [
        (EMPTY, NORMAL, 60),
        (NORMAL, EMPTY, 180),  # 空站持續了 3 分鐘
    ]
    assert events[0].changed_at == T0 + timedelta(minutes=1)
    assert state == StationState(NORMAL, T0 + timedelta(minutes=4), T0 + timedelta(minutes=4))


def test_state_carries_across_batches():
    state, _ = detect_transitions("A", None, [obs(0, 0, 10)])
    # 下一個 micro-batch 仍是空站：不重複告警
    state, events = detect_transitions("A", state, [obs(1, 0, 10)])
    assert events == []
    assert state.since == T0
    assert state.last_seen == T0 + timedelta(minutes=1)

    _, events = detect_transitions("A", state, [obs(5, 10, 0)])
    assert [(e.status, e.previous_status, e.previous_duration_seconds) for e in events] == [
        (FULL, EMPTY, 300)
    ]


def test_duplicates_and_out_of_order_observations_are_ignored():
    state, _ = detect_transitions("A", None, [obs(5, 4, 6)])
    # 重複送達的同一筆，以及比已處理資料更舊的空站紀錄，都不應該產生事件
    new_state, events = detect_transitions("A", state, [obs(5, 4, 6), obs(2, 0, 10)])
    assert events == []
    assert new_state == state


def test_observations_within_a_batch_are_processed_in_event_time_order():
    _, events = detect_transitions("A", None, [obs(2, 3, 7), obs(1, 0, 10), obs(0, 3, 7)])
    assert [(e.status, e.changed_at) for e in events] == [
        (EMPTY, T0 + timedelta(minutes=1)),
        (NORMAL, T0 + timedelta(minutes=2)),
    ]


def availability_frame():
    records = json.loads((FIXTURES / "tdx_bike_availability_sample.json").read_text(encoding="utf-8"))
    return normalize_availability(records, "Taichung", T0)


def test_select_changed_builds_keyed_json_messages():
    messages = select_changed(availability_frame(), seen={})

    assert [m.key for m in messages] == ["TXG500601001", "TXG500601002"]
    payload = json.loads(messages[0].value)
    assert payload["bikes_available"] == 5
    assert payload["source_updated_at"] == messages[0].source_updated_at == "2026-10-07T11:41:02.000000Z"


def test_select_changed_skips_stations_without_a_newer_source_update():
    seen = {
        "TXG500601001": "2026-10-07T11:41:02.000000Z",  # 與來源相同：略過
        "TXG500601002": "2026-10-07T11:39:30.000000Z",  # 來源較新：送出
    }
    assert [m.key for m in select_changed(availability_frame(), seen)] == ["TXG500601002"]


class FakeProducer:
    """模擬 confluent_kafka.Producer：指定的 key 會回報送出失敗。"""

    def __init__(self, fail_keys=()):
        self.fail_keys = set(fail_keys)
        self.sent = []
        self._callbacks = []

    def produce(self, topic, key, value, on_delivery):
        self.sent.append((topic, key))
        error = "broker down" if key in self.fail_keys else None
        self._callbacks.append(lambda: on_delivery(error, None))

    def poll(self, _timeout):
        return 0

    def flush(self):
        for callback in self._callbacks:
            callback()
        self._callbacks.clear()


def test_publish_marks_seen_only_after_delivery_succeeds():
    messages = select_changed(availability_frame(), seen={})
    producer = FakeProducer(fail_keys={"TXG500601002"})
    seen: dict[str, str] = {}

    delivered = publish(producer, "topic", messages, seen)

    assert delivered == 1
    assert producer.sent == [("topic", "TXG500601001"), ("topic", "TXG500601002")]
    # 送失敗的站點沒有記進 seen，下一輪會再送一次
    assert seen == {"TXG500601001": "2026-10-07T11:41:02.000000Z"}


def test_station_rows_use_display_names_and_plain_python_types():
    from ingestion.transform import normalize_stations
    from streaming.stations import station_rows

    records = json.loads((FIXTURES / "tdx_bike_stations_sample.json").read_text(encoding="utf-8"))
    rows = station_rows(normalize_stations(records, "Taichung", T0))

    uid, name, lat, lng, capacity = rows[0]
    # 來源站名的「YouBike2.0_」前綴不顯示在儀表板上
    assert name == "臺中火車站"
    assert (type(lat), type(lng), type(capacity)) == (float, float, int)
    assert capacity == 20

import assert from "node:assert/strict";
import { test } from "node:test";

import { estimateBikes, haversineMeters, recommend } from "../js/recommend.js";

const NOW = Date.parse("2026-10-08T12:00:00Z");
const IN_ONE_HOUR = NOW + 60 * 60000;

// 沿著同一條經線由南往北排列的站點，緯度差 0.001 度約 111 公尺
function station(id, latOffset, bikes, docks, extra = {}) {
  return { id, name: id, lat: 24.15 + latOffset, lng: 120.65, bikes, docks, inService: true, ...extra };
}
const ORIGIN = { lat: 24.15, lng: 120.65 };
const DESTINATION = { lat: 24.17, lng: 120.65 }; // 往北約 2.2 公里

test("haversine 距離：緯度差 0.01 度約 1.11 公里", () => {
  const meters = haversineMeters({ lat: 24.15, lng: 120.65 }, { lat: 24.16, lng: 120.65 });
  assert.ok(Math.abs(meters - 1112) < 5, `實際 ${meters}`);
});

test("沒有預測的站點：假設車數不變", () => {
  assert.deepEqual(estimateBikes(station("A", 0, 7, 3), 30, NOW), { bikes: 7, forecasted: false });
});

test("有預測的站點：在現在與預測之間線性內插", () => {
  const s = station("A", 0, 10, 10, { forecast: { at: IN_ONE_HOUR, bikes: 4 } });

  assert.equal(estimateBikes(s, 0, NOW).bikes, 10);
  assert.equal(estimateBikes(s, 30, NOW).bikes, 7); // 走到一半，減少一半
  assert.equal(estimateBikes(s, 60, NOW).bikes, 4);
  assert.equal(estimateBikes(s, 90, NOW).bikes, 4); // 超過預測時間就用預測值，不外插
});

test("預測值夾在 0 與總車位數之間", () => {
  const s = station("A", 0, 2, 8, { forecast: { at: IN_ONE_HOUR, bikes: 15 } });
  assert.equal(estimateBikes(s, 60, NOW).bikes, 10);
});

test("預測已經過期（快照比預測時間還晚）：不使用", () => {
  const s = station("A", 0, 10, 10, { forecast: { at: NOW - 60000, bikes: 0 } });
  assert.deepEqual(estimateBikes(s, 30, NOW), { bikes: 10, forecasted: false });
});

test("選離出發地與目的地最近、且有車有空位的站", () => {
  const stations = [
    station("near-origin", 0.001, 8, 8),
    station("far-origin", 0.004, 8, 8),
    station("near-destination", 0.019, 8, 8),
    station("far-destination", 0.015, 8, 8),
  ];
  const { options } = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.equal(options[0].rent.id, "near-origin");
  assert.equal(options[0].ret.id, "near-destination");
  assert.equal(options[0].fewBikes, false);
  assert.ok(options[0].totalMinutes > 10 && options[0].totalMinutes < 25);
});

test("最近的站沒有車時，改推薦下一個有車的站", () => {
  const stations = [
    station("empty", 0.001, 0, 16),
    station("has-bikes", 0.003, 6, 10),
    station("destination", 0.019, 8, 8),
  ];
  const { options } = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.equal(options[0].rent.id, "has-bikes");
  assert.ok(options.every((option) => option.rent.id !== "empty"));
});

test("目前有空位、但預測抵達時會滿站的還車站會被排除", () => {
  // 現在有 5 個空位，但預測 20 分鐘後車數等於總車位數（滿站）
  const fillingUp = station("filling-up", 0.02, 15, 5, {
    forecast: { at: NOW + 10 * 60000, bikes: 20 },
  });
  const stations = [station("origin", 0.001, 8, 8), fillingUp, station("alternative", 0.017, 8, 8)];
  const { options } = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.equal(options[0].ret.id, "alternative");
  assert.ok(options.every((option) => option.ret.id !== "filling-up"));
});

test("車很少的站排在後面，並標示風險", () => {
  const stations = [
    station("one-bike", 0.001, 1, 15), // 最近，但只剩 1 台
    station("plenty", 0.002, 9, 7), // 多走約 110 公尺
    station("destination", 0.019, 8, 8),
  ];
  const { options } = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.equal(options[0].rent.id, "plenty");
  const risky = options.find((option) => option.rent.id === "one-bike");
  assert.equal(risky.fewBikes, true);
});

test("停止營運的站點不會被推薦", () => {
  const stations = [
    station("closed", 0.001, 8, 8, { inService: false }),
    station("open", 0.003, 8, 8),
    station("destination", 0.019, 8, 8),
  ];
  const { options } = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.ok(options.every((option) => option.rent.id !== "closed" && option.ret.id !== "closed"));
});

test("附近完全沒有車時回傳空的建議，並附上步行時間", () => {
  const stations = [station("empty-1", 0.001, 0, 16), station("empty-2", 0.019, 0, 16)];
  const result = recommend(stations, ORIGIN, DESTINATION, NOW);

  assert.deepEqual(result.options, []);
  assert.ok(result.walkOnlyMinutes > 30);
});

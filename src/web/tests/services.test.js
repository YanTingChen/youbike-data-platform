// 外部服務相關的純邏輯測試：站名比對、地點名稱整理、路段時間的記錄。不會發出任何網路請求
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatPlace, matchStations } from "../js/places.js";
import { recommend, straightLineTravel } from "../js/recommend.js";
import { forgetLegs, knownTravel, missingLegs, parseRoute, storeLeg } from "../js/routing.js";

const NOW = Date.parse("2026-10-08T12:00:00Z");

function station(id, lat, lng, extra = {}) {
  return { id, name: id, lat, lng, bikes: 8, docks: 8, inService: true, ...extra };
}

test("站名比對：開頭符合的排在前面，並限制筆數", () => {
  const stations = ["臺中火車站", "新烏日火車站", "火車站前廣場", "逢甲大學"].map((name) => ({ name }));

  assert.deepEqual(
    matchStations(stations, "火車站").map((s) => s.name),
    ["火車站前廣場", "臺中火車站", "新烏日火車站"],
  );
  assert.equal(matchStations(stations, "站", 2).length, 2);
  assert.deepEqual(matchStations(stations, "  "), []);
});

test("站名比對不分大小寫", () => {
  const stations = [{ name: "SOGO 百貨" }];
  assert.equal(matchStations(stations, "sogo").length, 1);
});

test("地點名稱：拆成主要名稱與補充說明，去掉郵遞區號與國名", () => {
  const place = formatPlace({
    name: "逢甲大學",
    display_name: "逢甲大學, 文華路, 西屯區, 臺中市, 407, 臺灣",
    lat: "24.1800576",
    lon: "120.6483389",
  });

  assert.deepEqual(place, { name: "逢甲大學", detail: "文華路・西屯區・臺中市", lat: 24.1800576, lng: 120.6483389 });
});

test("地點沒有名稱時用完整名稱的第一段", () => {
  const place = formatPlace({ name: "", display_name: "文華路100號, 西屯區, 臺中市", lat: "24.18", lon: "120.65" });
  assert.equal(place.name, "文華路100號");
});

test("路線服務的回應：座標轉成 Leaflet 的順序，秒換成分鐘", () => {
  const leg = parseRoute({
    routes: [{ duration: 600, distance: 2500, geometry: { coordinates: [[120.65, 24.15], [120.66, 24.16]] } }],
  });

  assert.deepEqual(leg, { path: [[24.15, 120.65], [24.16, 120.66]], minutes: 10, meters: 2500 });
});

test("查過的路段用實際時間，沒查過的用直線估算", () => {
  forgetLegs();
  const a = { lat: 24.15, lng: 120.65 };
  const b = { lat: 24.16, lng: 120.66 };
  storeLeg("ride", a, b, { path: [], minutes: 12, meters: 3000 });

  assert.equal(knownTravel.ride(a, b), 12);
  assert.equal(knownTravel.rideMeters(a, b), 3000);
  // 反方向是另一段路（單行道、坡度都可能不同），不能沿用
  assert.equal(knownTravel.ride(b, a), straightLineTravel.ride(b, a));
  // 同樣兩點，步行與騎乘分開記錄
  assert.equal(knownTravel.walk(a, b), straightLineTravel.walk(a, b));
});

test("一組建議要三段路都查過，才算全部是實際時間", () => {
  forgetLegs();
  const origin = { lat: 24.15, lng: 120.65 };
  const destination = { lat: 24.17, lng: 120.65 };
  const option = { rent: station("rent", 24.151, 120.65), ret: station("ret", 24.169, 120.65) };
  const leg = { path: [], minutes: 1, meters: 1 };

  assert.deepEqual(
    missingLegs(option, origin, destination).map((l) => l.name),
    ["ride", "walkToRent", "walkFromReturn"], // 騎乘最長、對總時間影響最大，排第一個查
  );

  storeLeg("ride", option.rent, option.ret, leg);
  storeLeg("walk", origin, option.rent, leg);
  assert.deepEqual(missingLegs(option, origin, destination).map((l) => l.name), ["walkFromReturn"]);

  storeLeg("walk", option.ret, destination, leg);
  assert.deepEqual(missingLegs(option, origin, destination), []);
});

test("換用實際道路時間後，建議會跟著改變", () => {
  // 直線距離上 near 比較近，但實際要繞路（例如隔著鐵路），走過去反而比 far 久
  const origin = { lat: 24.15, lng: 120.65 };
  const destination = { lat: 24.17, lng: 120.65 };
  const near = station("near", 24.151, 120.65);
  const far = station("far", 24.153, 120.65);
  const end = station("end", 24.169, 120.65);
  const stations = [near, far, end];

  assert.equal(recommend(stations, origin, destination, NOW).options[0].rent.id, "near");

  const detour = {
    exact: true,
    walk: (from, to) => (to.id === "near" ? 15 : straightLineTravel.walk(from, to)),
    ride: straightLineTravel.ride,
    rideMeters: straightLineTravel.rideMeters,
  };
  const result = recommend(stations, origin, destination, NOW, detour);

  assert.equal(result.options[0].rent.id, "far");
  assert.equal(result.exact, true);
});

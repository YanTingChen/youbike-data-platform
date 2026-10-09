// 請求依序送出並保留間隔，避免超過公共路線服務的流量限制。
// 查詢失敗時保留估算；已知路段快取供重新排序使用。

import { straightLineTravel } from "./recommend.js";

const BASE_URL = "https://routing.openstreetmap.de";
const PROFILES = { walk: "routed-foot", ride: "routed-bike" };
const TIMEOUT_MS = 8000;
const MIN_INTERVAL_MS = 1100;

const coordinate = (point) => `${point.lng.toFixed(6)},${point.lat.toFixed(6)}`; // OSRM 的順序是「經度,緯度」
const legKey = (profile, from, to) =>
  `${profile}:${from.lat.toFixed(5)},${from.lng.toFixed(5)}>${to.lat.toFixed(5)},${to.lng.toFixed(5)}`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 使用者已經改了起訖點、這個請求的結果不再需要時拋出；呼叫端應該直接忽略
export class StaleRequestError extends Error {}


// 路段 → { path: [[緯度, 經度], …], minutes, meters }
const legs = new Map();

export function storeLeg(profile, from, to, leg) {
  legs.set(legKey(profile, from, to), leg);
}

export function knownLeg(profile, from, to) {
  return legs.get(legKey(profile, from, to));
}

export function forgetLegs() {
  legs.clear();
}

// 給 recommend() 用的 travel：查過的路段用實際時間，還沒查的用直線估算。
// 隨著路段一段一段查回來，重新呼叫 recommend() 就會得到越來越準確的排序
export const knownTravel = {
  exact: true,
  walk: (a, b) => knownLeg("walk", a, b)?.minutes ?? straightLineTravel.walk(a, b),
  ride: (a, b) => knownLeg("ride", a, b)?.minutes ?? straightLineTravel.ride(a, b),
  rideMeters: (a, b) => knownLeg("ride", a, b)?.meters ?? straightLineTravel.rideMeters(a, b),
};

// 一組建議由三段路組成：步行到借車站、騎乘、步行到目的地
export function optionLegs(option, origin, destination) {
  return [
    { name: "ride", profile: "ride", from: option.rent, to: option.ret },
    { name: "walkToRent", profile: "walk", from: origin, to: option.rent },
    { name: "walkFromReturn", profile: "walk", from: option.ret, to: destination },
  ];
}

// 這組建議還沒查過的路段（全部查過時回傳空陣列，代表它的時間都是實際值）
export function missingLegs(option, origin, destination) {
  return optionLegs(option, origin, destination).filter((leg) => !knownLeg(leg.profile, leg.from, leg.to));
}


let queue = Promise.resolve();
let lastRequestAt = 0;

// 把一個請求排進佇列。isStale 在真正送出前才檢查：
// 排隊期間使用者若已經換了起訖點，這個請求就不送了，不佔用頻率額度
function enqueue(url, isStale = () => false) {
  const run = queue.then(async () => {
    if (isStale()) throw new StaleRequestError();
    await sleep(Math.max(0, lastRequestAt + MIN_INTERVAL_MS - Date.now()));
    if (isStale()) throw new StaleRequestError();
    lastRequestAt = Date.now();

    const response = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) throw new Error(`路線服務回應 HTTP ${response.status}`);
    const body = await response.json();
    if (body.code !== "Ok" || !body.routes?.length) throw new Error(`路線服務回應 ${body.code}`);
    return body;
  });
  queue = run.catch(() => {}); // 一個請求失敗不影響排在後面的
  return run;
}

// 把服務的回應整理成一段路的資料。純函式，方便測試
export function parseRoute(body) {
  const route = body.routes[0];
  return {
    path: route.geometry.coordinates.map(([lng, lat]) => [lat, lng]), // GeoJSON 是 [經度, 緯度]，Leaflet 要反過來
    minutes: route.duration / 60,
    meters: route.distance,
  };
}

// 查詢一段路並記下來；已經查過就直接回傳
export async function fetchLeg(profile, from, to, isStale) {
  const known = knownLeg(profile, from, to);
  if (known) return known;
  const url =
    `${BASE_URL}/${PROFILES[profile]}/route/v1/driving/${coordinate(from)};${coordinate(to)}` +
    "?overview=full&geometries=geojson";
  const leg = parseRoute(await enqueue(url, isStale));
  storeLeg(profile, from, to, leg);
  return leg;
}

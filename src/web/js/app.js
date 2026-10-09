// 路線逐段查回後重新排序；未取得的路段保留估算，讓畫面仍可操作。

import { EXAMPLE_ROUTE, MAP_CENTER, MAP_ZOOM, SNAPSHOT_URLS, STALE_AFTER_MINUTES } from "./config.js";
import { matchStations, searchPlaces } from "./places.js";
import { LOW_THRESHOLD, estimateBikes, haversineMeters, recommend } from "./recommend.js";
import { StaleRequestError, fetchLeg, knownLeg, knownTravel, missingLegs, optionLegs } from "./routing.js";

const L = window.L;
const COLORS = { ok: "#2f9e44", low: "#f08c00", none: "#e03131", closed: "#adb5bd" };
const ROUTE_COLOR = "#1a73e8";
// 起訖點離最近的站點超過這個距離，就視為不在服務範圍內
const MAX_DISTANCE_TO_STATION_METERS = 3000;
// 一次建議最多向路線服務查幾段路（前三名共 9 段，重新排序後可能換進新的組合，留一點餘裕）
const MAX_LEG_REQUESTS = 12;

const state = {
  stations: [],
  snapshotTime: 0,
  origin: null,
  destination: null,
  labels: { origin: "", destination: "" }, // 輸入框裡顯示的文字
  mode: null, // 下一次點地圖要設定哪一個點：origin、destination 或 null（不設定）
  view: "bikes", // 站點顏色代表可借車數（bikes）或可還空位（docks）
  options: [],
  selected: 0,
  userSelected: false, // 使用者是否自己點選了某一組；沒有的話，重新排序後一律選第一名
  walkOnlyMinutes: undefined,
  routing: "idle", // partial 代表已達查詢上限但仍有估算路段
};

// 起訖點每變動一次就加一；非同步的結果回來時若編號已經不同，代表使用者又改了，直接丟棄
let requestId = 0;

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // 一律用 textContent：站名與地名來自外部資料，不當成 HTML
  return node;
}

const minutes = (value) => `${Math.max(1, Math.round(value))} 分`;
const kilometers = (meters) => `${(meters / 1000).toFixed(1)} 公里`;
const taipeiTime = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});


// maxBoundsViscosity: 1 讓地圖完全不能被拖出範圍（範圍在資料載入後依站點位置設定）
const map = L.map("map", { preferCanvas: true, maxBoundsViscosity: 1 }).setView(MAP_CENTER, MAP_ZOOM);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 貢獻者',
}).addTo(map);

const stationLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const stationMarkers = new Map();
const pins = { origin: null, destination: null };
let serviceArea = null;

// 把地圖限制在有站點的範圍：不能拖出去，縮小時最多剛好看到全部站點。
// 範圍取自資料而不是寫死的座標，站點擴張時會自動跟著變大。
function restrictToServiceArea() {
  serviceArea = L.latLngBounds(state.stations.map((station) => [station.lat, station.lng])).pad(0.08);
  map.setMaxBounds(serviceArea);
  map.setMinZoom(map.getBoundsZoom(serviceArea));
}
// 視窗大小改變時（例如平板轉向），「剛好看到全部站點」的縮放層級也會不同
map.on("resize", () => serviceArea && map.setMinZoom(map.getBoundsZoom(serviceArea)));

function stationColor(station) {
  if (!station.inService) return COLORS.closed;
  const count = state.view === "bikes" ? station.bikes : station.docks;
  if (count === 0) return COLORS.none;
  return count < LOW_THRESHOLD ? COLORS.low : COLORS.ok;
}

function stationPopup(station) {
  const box = el("div");
  box.append(el("p", "popup-name", station.name));
  if (!station.inService) {
    box.append(el("p", "popup-line", "停止營運"));
    return box;
  }
  box.append(el("p", "popup-line", `可借 ${station.bikes} 台・可還 ${station.docks} 位`));
  const inOneHour = estimateBikes(station, 60, state.snapshotTime);
  if (inOneHour.forecasted) {
    const time = taipeiTime.format(station.forecast.at).split(" ").pop();
    box.append(el("p", "popup-line", `預測 ${time} 約可借 ${Math.round(inOneHour.bikes)} 台`));
  }
  return box;
}

function drawStations() {
  stationLayer.clearLayers();
  stationMarkers.clear();
  for (const station of state.stations) {
    const marker = L.circleMarker([station.lat, station.lng], {
      radius: 5,
      weight: 1,
      color: "#ffffff",
      fillColor: stationColor(station),
      fillOpacity: 0.9,
    });
    // 正在選起訖點時，點到站點等於選那個位置；其餘時候才顯示站點資訊
    marker.on("click", () => {
      if (!state.mode) marker.bindPopup(stationPopup(station)).openPopup();
    });
    marker.addTo(stationLayer);
    stationMarkers.set(station.id, marker);
  }
}

function recolorStations() {
  for (const station of state.stations) {
    stationMarkers.get(station.id).setStyle({ fillColor: stationColor(station) });
  }
}

function nearestStation(point) {
  let nearest = null;
  let best = Infinity;
  for (const station of state.stations) {
    const meters = haversineMeters(point, station);
    if (meters < best) {
      best = meters;
      nearest = station;
    }
  }
  return { station: nearest, meters: best };
}

// 從地圖選的點沒有名字，用最近的站點來描述它
function describePoint(point) {
  const { station, meters } = nearestStation(point);
  if (!station) return "已選擇的位置";
  return meters < 60 ? station.name : `${station.name} 附近`;
}

// 設定（或清除）出發地／目的地。label 是輸入框要顯示的文字，沒給就用最近的站點描述
function setPoint(kind, point, label) {
  state[kind] = point;
  state.labels[kind] = point ? (label ?? describePoint(point)) : "";
  if (pins[kind]) pins[kind].remove();
  pins[kind] = null;
  if (!point) return;

  const marker = L.marker([point.lat, point.lng], {
    draggable: true,
    zIndexOffset: 1000,
    icon: L.divIcon({
      className: "",
      html: `<div class="map-pin pin-${kind}">${kind === "origin" ? "起" : "終"}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    }),
  });
  marker.on("dragend", () => {
    const { lat, lng } = marker.getLatLng();
    state[kind] = { lat, lng };
    state.labels[kind] = describePoint(state[kind]);
    update();
  });
  pins[kind] = marker.addTo(map);
}

// 畫出選中的那一組路線，共三段：步行到借車站、騎乘、步行到目的地。
// 已經查到實際路徑的路段沿著道路畫；還沒查到（或查不到）的先畫直線示意，並畫得淡一點
function drawRoute() {
  routeLayer.clearLayers();
  const option = state.options[state.selected];
  if (!option) return;

  // 步行畫虛線、騎乘畫實線
  const styles = { ride: { weight: 5 }, walkToRent: { weight: 4, dashArray: "2 9" }, walkFromReturn: { weight: 4, dashArray: "2 9" } };
  for (const leg of optionLegs(option, state.origin, state.destination)) {
    const known = knownLeg(leg.profile, leg.from, leg.to);
    const straight = [
      [leg.from.lat, leg.from.lng],
      [leg.to.lat, leg.to.lng],
    ];
    L.polyline(known?.path ?? straight, { color: ROUTE_COLOR, opacity: known ? 0.9 : 0.4, ...styles[leg.name] }).addTo(
      routeLayer,
    );
  }

  for (const [station, label] of [
    [option.rent, "借車"],
    [option.ret, "還車"],
  ]) {
    L.circleMarker([station.lat, station.lng], { radius: 9, weight: 3, color: ROUTE_COLOR, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(label, { permanent: true, direction: "top", offset: [0, -8], className: "station-label" })
      .addTo(routeLayer);
  }
}


function stopRow(kind, name, detail, warning) {
  const row = el("div", "stop");
  row.append(el("span", "stop-kind", kind), el("span", "stop-name", name));
  const line = el("span", "stop-detail", detail);
  if (warning) line.append(el("span", "warn", `・${warning}`));
  row.append(line);
  return row;
}

function optionCard(option, index) {
  const card = el("button", `option${index === state.selected ? " selected" : ""}`);
  card.type = "button";

  // 三段路都查到實際路徑之前，這一組的時間還含有直線估算的成分
  const estimated = missingLegs(option, state.origin, state.destination).length > 0;
  const head = el("div", "option-head");
  const rank = el("span", "option-rank", index === 0 ? "建議路線" : `替代路線 ${index}`);
  if (estimated) rank.append(el("span", "estimate-tag", "估算"));
  head.append(rank, el("span", "option-total", `約 ${minutes(option.totalMinutes)}鐘`));

  const bikes = Math.floor(option.bikesAtPickup);
  const docks = Math.floor(option.docksAtArrival);
  const docksText = option.docksForecasted ? `預測抵達時約 ${docks} 個空位` : `目前 ${docks} 個空位`;

  card.append(
    head,
    stopRow("借車", option.rent.name, `可借 ${bikes} 台`, option.fewBikes ? "車輛偏少" : ""),
    stopRow("還車", option.ret.name, docksText, option.fewDocks ? "空位偏少" : ""),
    el(
      "div",
      "legs",
      `步行 ${minutes(option.walkToRent)} → 騎乘 ${minutes(option.ride)}（${kilometers(option.rideMeters)}）` +
        ` → 步行 ${minutes(option.walkFromReturn)}`,
    ),
  );
  card.addEventListener("click", () => {
    state.selected = index;
    state.userSelected = true;
    renderResults();
    drawRoute();
  });
  return card;
}

function renderResults() {
  const results = $("results");
  results.replaceChildren();
  if (!state.origin || !state.destination) return;

  for (const point of [state.origin, state.destination]) {
    if (nearestStation(point).meters > MAX_DISTANCE_TO_STATION_METERS) {
      results.append(el("p", "message", "選擇的位置附近沒有 YouBike 站點，請選在站點分布的範圍內。"));
      return;
    }
  }
  if (state.options.length === 0) {
    results.append(el("p", "message", "附近的站點目前沒有可借的車或可還的空位，請換個位置試試。"));
    return;
  }

  const status = {
    loading: ["route-status", "正在依實際道路計算，路線與時間會逐段更新…"],
    exact: ["route-status", "時間與路線依實際道路計算。"],
    partial: ["route-status", "已更新部分道路路線，標示「估算」的路段仍以直線距離計算。"],
    fallback: ["route-status fallback", "路線服務暫時無法使用，標示「估算」的時間以直線距離計算，淡色的直線僅為示意。"],
  }[state.routing];
  if (status) results.append(el("p", ...status));

  state.options.forEach((option, index) => results.append(optionCard(option, index)));

  // 短距離時騎車不一定比較快，誠實地告訴使用者
  const best = state.options[0].totalMinutes;
  if (state.walkOnlyMinutes !== undefined && state.walkOnlyMinutes <= best + 2) {
    results.append(el("p", "message", `這段路直接步行約 ${minutes(state.walkOnlyMinutes)}鐘，和騎車差不多。`));
  }
}

function renderPicker() {
  for (const row of document.querySelectorAll(".picker-row")) {
    const kind = row.dataset.kind;
    row.classList.toggle("active", state.mode === kind);
    const input = row.querySelector("input");
    // 使用者正在打字的那一格不要被覆蓋
    if (document.activeElement !== input) input.value = state.labels[kind];
  }
  document.body.classList.toggle("picking", Boolean(state.mode));

  const hints = { origin: "請在地圖上點選出發地。", destination: "請在地圖上點選目的地。" };
  let hint = hints[state.mode] ?? "";
  if (!hint && !state.origin && !state.destination) hint = "輸入出發地與目的地，或按「地圖選點」直接在地圖上點。";
  if (!hint && state.origin && state.destination) hint = "可以拖曳地圖上的起訖點來調整。";
  $("hint").textContent = hint;
}

// 依目前已知的路段時間重新計算建議。已經查過的路段用實際時間，其餘用直線估算
function rerank() {
  const previous = state.options[state.selected];
  const result = recommend(state.stations, state.origin, state.destination, state.snapshotTime, knownTravel);
  state.options = result.options;
  state.walkOnlyMinutes = result.walkOnlyMinutes;

  // 使用者自己選過的那一組，重新排序後仍然保持選取；沒選過就跟著第一名
  const same = (option) => option.rent.id === previous?.rent.id && option.ret.id === previous?.ret.id;
  const index = state.userSelected ? state.options.findIndex(same) : -1;
  state.selected = Math.max(index, 0);
}

// 逐段查詢實際路徑。每次挑「選中的那一組」還缺的路段優先查，其次是其他組
async function refineWithRealRoutes(id) {
  const isStale = () => id !== requestId;
  for (let requests = 0; requests < MAX_LEG_REQUESTS; requests++) {
    const byPriority = [state.options[state.selected], ...state.options].filter(Boolean);
    const next = byPriority.flatMap((option) => missingLegs(option, state.origin, state.destination))[0];
    if (!next) break;
    try {
      await fetchLeg(next.profile, next.from, next.to, isStale);
    } catch (error) {
      if (error instanceof StaleRequestError || isStale()) return;
      console.warn("路線服務無法使用，其餘路段保留直線估算", error);
      state.routing = "fallback";
      renderResults();
      return;
    }
    if (isStale()) return;
    rerank();
    renderResults();
    drawRoute();
  }
  const complete = state.options.every(
    (option) => missingLegs(option, state.origin, state.destination).length === 0,
  );
  state.routing = complete ? "exact" : "partial";
  renderResults();
}

// 起訖點改變時使舊請求失效，避免覆蓋新的建議。
async function update() {
  const id = ++requestId;
  state.options = [];
  state.walkOnlyMinutes = undefined;
  state.selected = 0;
  state.userSelected = false;
  state.routing = "idle";

  if (state.origin && state.destination) {
    rerank();
    if (state.options.length > 0) state.routing = "loading";
  }
  renderPicker();
  renderResults();
  drawRoute();
  if (state.routing === "loading") await refineWithRealRoutes(id);
}

function fitToRoute() {
  const points = [state.origin, state.destination].filter(Boolean).map((p) => [p.lat, p.lng]);
  if (points.length === 2) map.fitBounds(points, { padding: [60, 60] });
  else if (points.length === 1) map.setView(points[0], Math.max(map.getZoom(), 15));
}


// 讓一個輸入框具備「打字時列出符合的站點、按 Enter 或選『搜尋地點』時查詢地標與地址」的行為
function setupPlaceInput(row) {
  const kind = row.dataset.kind;
  const input = row.querySelector("input");
  const list = row.querySelector(".suggestions");
  let items = []; // 目前清單上可以選的項目：{ label, detail, tag, choose }
  let highlighted = -1;

  const close = () => {
    list.hidden = true;
    items = [];
    highlighted = -1;
  };

  function show(nextItems, note) {
    items = nextItems;
    highlighted = -1;
    list.replaceChildren();
    items.forEach((item, index) => {
      const li = el("li");
      li.append(el("span", "suggestion-tag", item.tag), el("span", "", item.label));
      if (item.detail) li.append(el("span", "suggestion-detail", item.detail));
      // mousedown 而不是 click：要搶在輸入框失去焦點（清單被關掉）之前
      li.addEventListener("mousedown", (event) => {
        event.preventDefault();
        item.choose();
      });
      li.dataset.index = index;
      list.append(li);
    });
    if (note) list.append(el("li", "static", note));
    list.hidden = items.length === 0 && !note;
  }

  function choosePlace(point, label) {
    setPoint(kind, point, label);
    // 選完出發地而目的地還空著，就接著把游標移到目的地
    state.mode = null;
    close();
    input.blur();
    update();
    fitToRoute();
    if (kind === "origin" && !state.destination) $("destination-input").focus();
  }

  async function search(query) {
    show([], "搜尋中…");
    try {
      const places = await searchPlaces(query, serviceArea);
      // 等待期間使用者已經改了輸入或離開這一格，結果就不顯示了
      if (input.value.trim() !== query || document.activeElement !== input) return;
      show(
        places.map((place) => ({
          tag: "地點",
          label: place.name,
          detail: place.detail,
          choose: () => choosePlace({ lat: place.lat, lng: place.lng }, place.name),
        })),
        places.length === 0 ? `在台中找不到「${query}」，可以換個關鍵字或改用地圖選點。` : "",
      );
    } catch (error) {
      console.warn("地點搜尋失敗", error);
      show([], "地點搜尋暫時無法使用，請輸入站名或改用地圖選點。");
    }
  }

  function suggest() {
    const query = input.value.trim();
    if (!query) return close();
    const stations = matchStations(state.stations, query).map((station) => ({
      tag: "站點",
      label: station.name,
      detail: station.inService ? `可借 ${station.bikes} 台・可還 ${station.docks} 位` : "停止營運",
      choose: () => choosePlace({ lat: station.lat, lng: station.lng }, station.name),
    }));
    show([...stations, { tag: "搜尋", label: `搜尋地標或地址「${query}」`, choose: () => search(query) }]);
  }

  input.addEventListener("input", suggest);
  input.addEventListener("focus", () => {
    input.select();
    suggest();
  });
  input.addEventListener("blur", () => {
    close();
    input.value = state.labels[kind]; // 沒有選任何項目就還原成目前的設定
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") return input.blur();
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (items.length === 0) return;
      event.preventDefault();
      highlighted = (highlighted + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      [...list.children].forEach((li, index) => li.classList.toggle("highlighted", index === highlighted));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const query = input.value.trim();
      if (highlighted >= 0) items[highlighted].choose();
      else if (query) search(query); // 沒有特別選就直接搜尋地點
    }
  });
}


map.on("click", (event) => {
  if (!state.mode) return;
  const kind = state.mode;
  setPoint(kind, { lat: event.latlng.lat, lng: event.latlng.lng });
  // 選完出發地自動接著選目的地；兩個都有了就結束選取
  state.mode = kind === "origin" && !state.destination ? "destination" : null;
  update();
});

for (const row of document.querySelectorAll(".picker-row")) {
  setupPlaceInput(row);
  const button = row.querySelector(".pick-on-map");
  button.addEventListener("click", () => {
    state.mode = state.mode === button.dataset.mode ? null : button.dataset.mode;
    renderPicker();
  });
}

for (const button of document.querySelectorAll(".segmented button")) {
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    for (const other of document.querySelectorAll(".segmented button")) {
      other.classList.toggle("active", other === button);
    }
    recolorStations();
  });
}

function useExample() {
  setPoint("origin", { ...EXAMPLE_ROUTE.origin }, EXAMPLE_ROUTE.origin.label);
  setPoint("destination", { ...EXAMPLE_ROUTE.destination }, EXAMPLE_ROUTE.destination.label);
  state.mode = null;
  update();
  fitToRoute();
}

$("use-example").addEventListener("click", useExample);

$("use-location").addEventListener("click", () => {
  if (!navigator.geolocation) {
    $("hint").textContent = "這個瀏覽器不支援定位。";
    return;
  }
  $("hint").textContent = "正在取得位置…";
  navigator.geolocation.getCurrentPosition(
    (position) => {
      setPoint("origin", { lat: position.coords.latitude, lng: position.coords.longitude }, "我的位置");
      state.mode = null;
      update();
      fitToRoute();
    },
    () => {
      $("hint").textContent = "無法取得位置，請改用輸入或地圖選點。";
    },
    { enableHighAccuracy: true, timeout: 10000 },
  );
});

$("swap").addEventListener("click", () => {
  const { origin, destination } = state;
  const labels = { ...state.labels };
  setPoint("origin", destination, labels.destination);
  setPoint("destination", origin, labels.origin);
  update();
});

$("clear").addEventListener("click", () => {
  setPoint("origin", null);
  setPoint("destination", null);
  state.mode = null;
  update();
});


// 依序嘗試每個來源，回傳第一份讀得到的快照
async function fetchSnapshot() {
  let lastError;
  for (const url of SNAPSHOT_URLS) {
    try {
      // cache: "no-cache"：每次都向伺服器確認有沒有新的快照
      const response = await fetch(url, { cache: "no-cache", signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.warn(`無法讀取 ${url}，改試下一個來源`, error);
      lastError = error;
    }
  }
  throw lastError;
}

async function loadSnapshot() {
  const snapshot = await fetchSnapshot();

  state.snapshotTime = Date.parse(snapshot.generated_at);
  state.stations = snapshot.stations.map((station) => ({
    id: station.id,
    name: station.name,
    lat: station.lat,
    lng: station.lng,
    bikes: station.bikes,
    docks: station.docks,
    inService: station.in_service,
    forecast: station.forecast ? { at: Date.parse(station.forecast.at), bikes: station.forecast.bikes } : null,
  }));
}

function renderDataTime() {
  const formatted = taipeiTime.format(state.snapshotTime);
  $("data-time").textContent = `資料時間 ${formatted}`;

  const ageMinutes = (Date.now() - state.snapshotTime) / 60000;
  if (ageMinutes > STALE_AFTER_MINUTES) {
    const banner = $("stale-banner");
    banner.textContent = `目前顯示的是 ${formatted} 的資料快照，不是即時車況。建議的計算方式不變，僅供展示。`;
    banner.hidden = false;
  }
}

try {
  await loadSnapshot();
  renderDataTime();
  restrictToServiceArea();
  drawStations();
  update();
  // 網址加上 ?demo=1 會直接載入範例路線，方便展示
  if (new URLSearchParams(location.search).has("demo")) useExample();
} catch (error) {
  console.error(error);
  $("data-time").textContent = "資料載入失敗";
  $("hint").textContent = "無法載入站點資料，請稍後重新整理。";
}

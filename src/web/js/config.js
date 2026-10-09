// 資料快照依序嘗試：先讀資料平台每 10 分鐘更新一次的那一份；
// 讀不到（平台已停機）就用隨網頁一起發布的最後一份，畫面上會標示資料時間
export const SNAPSHOT_URLS = [
  "https://storage.googleapis.com/youbike-taichung-snapshot/snapshot.json",
  "data/snapshot.json",
];

// 快照超過這個時間沒更新，就提示使用者看到的是歷史資料
export const STALE_AFTER_MINUTES = 30;

export const MAP_CENTER = [24.1505, 120.6635];
export const MAP_ZOOM = 13;

// 「範例路線」按鈕使用的起訖點
export const EXAMPLE_ROUTE = {
  origin: { lat: 24.1369, lng: 120.685, label: "臺中火車站" },
  destination: { lat: 24.179, lng: 120.6466, label: "逢甲大學" },
};

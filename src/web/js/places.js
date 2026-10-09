// 打字時只比對本機站點；明確搜尋才呼叫地理編碼服務，避免高頻請求。

const NOMINATIM_URL = "https://nominatim.openstreetmap.org/search";
const TIMEOUT_MS = 8000;

// 依名稱比對站點。開頭符合的排在包含的前面。純函式，方便測試。
export function matchStations(stations, query, limit = 5) {
  const text = query.trim().toLowerCase();
  if (!text) return [];
  const matches = [];
  for (const station of stations) {
    const position = station.name.toLowerCase().indexOf(text);
    if (position >= 0) matches.push({ station, position });
  }
  return matches
    .sort((a, b) => a.position - b.position || a.station.name.length - b.station.name.length)
    .slice(0, limit)
    .map((match) => match.station);
}

// Nominatim 的完整名稱像「逢甲大學, 文華路, 西屯區, 臺中市, 407, 臺灣」，拆成主要名稱與補充說明
export function formatPlace(result) {
  const parts = String(result.display_name ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const name = result.name || parts[0] || "未命名地點";
  const detail = parts
    .filter((part) => part !== name && !/^\d+$/.test(part) && part !== "臺灣")
    .slice(0, 3)
    .join("・");
  return { name, detail, lat: Number(result.lat), lng: Number(result.lon) };
}

// 在指定範圍（Leaflet 的 LatLngBounds）內搜尋地點
export async function searchPlaces(query, bounds) {
  const params = new URLSearchParams({
    format: "jsonv2",
    q: query,
    countrycodes: "tw",
    // 左上到右下：西,北,東,南。bounded=1 表示只回傳範圍內的結果
    viewbox: [bounds.getWest(), bounds.getNorth(), bounds.getEast(), bounds.getSouth()].join(","),
    bounded: "1",
    limit: "5",
    "accept-language": "zh-TW",
  });
  const response = await fetch(`${NOMINATIM_URL}?${params}`, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!response.ok) throw new Error(`地點搜尋回應 HTTP ${response.status}`);
  return (await response.json()).map(formatPlace);
}

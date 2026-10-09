// 以附近站點列舉借還車組合，依總時間與撲空風險排序。
// 抵達前的車況在快照與預測間內插；無預測時沿用快照。

export const DETOUR_FACTOR = 1.3;
export const WALK_METERS_PER_MINUTE = 75; // 4.5 km/h
export const BIKE_METERS_PER_MINUTE = 250; // 15 km/h，市區含停等

// 少於這個數量就提醒使用者有撲空的風險
export const LOW_THRESHOLD = 3;
// 出發地與目的地各考慮最近的幾個站
export const CANDIDATE_STATIONS = 6;
// 車或空位偏少的組合在排序時加上的懲罰（分鐘）：寧可多走一點，也不要到了才發現沒車
const RISK_PENALTY_MINUTES = 4;

const EARTH_RADIUS_METERS = 6371000;

export function haversineMeters(a, b) {
  const toRadians = (degrees) => (degrees * Math.PI) / 180;
  const dLat = toRadians(b.lat - a.lat);
  const dLng = toRadians(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRadians(a.lat)) * Math.cos(toRadians(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(h));
}

// 沒有路線服務時的備援：以直線距離估算
export const straightLineTravel = {
  exact: false,
  walk: (a, b) => (haversineMeters(a, b) * DETOUR_FACTOR) / WALK_METERS_PER_MINUTE,
  ride: (a, b) => (haversineMeters(a, b) * DETOUR_FACTOR) / BIKE_METERS_PER_MINUTE,
  rideMeters: (a, b) => haversineMeters(a, b) * DETOUR_FACTOR,
};

// 估計 minutesAhead 分鐘後某站的可借車數。snapshotTime 是資料的時間（毫秒），
// 一律以它為「現在」而不是瀏覽器的時間：快照過期時，整套計算仍然前後一致。
export function estimateBikes(station, minutesAhead, snapshotTime) {
  const capacity = station.bikes + station.docks;
  const forecast = station.forecast;
  const horizonMinutes = forecast ? (forecast.at - snapshotTime) / 60000 : 0;
  if (!forecast || horizonMinutes <= 0) {
    return { bikes: station.bikes, forecasted: false };
  }
  const progress = Math.min(Math.max(minutesAhead / horizonMinutes, 0), 1);
  const bikes = station.bikes + (forecast.bikes - station.bikes) * progress;
  return { bikes: Math.min(Math.max(bikes, 0), capacity), forecasted: progress > 0 };
}

function nearestStations(stations, point, count) {
  return stations
    .map((station) => ({ station, meters: haversineMeters(point, station) }))
    .sort((a, b) => a.meters - b.meters)
    .slice(0, count)
    .map((entry) => entry.station);
}

// 候選站點：出發地與目的地附近、營運中的站。以直線距離挑選；
// 獨立成一個函式，是因為畫面程式要先知道候選站點，才能向路線服務查詢它們之間的實際時間。
export function pickCandidates(stations, origin, destination) {
  const inService = stations.filter((station) => station.inService);
  return {
    rentCandidates: nearestStations(inService, origin, CANDIDATE_STATIONS),
    returnCandidates: nearestStations(inService, destination, CANDIDATE_STATIONS),
  };
}

// 回傳 { options, walkOnlyMinutes, exact }。options 依建議順序排列，每個元素是一組借車站＋還車站。
export function recommend(stations, origin, destination, snapshotTime, travel = straightLineTravel) {
  const { rentCandidates, returnCandidates } = pickCandidates(stations, origin, destination);

  const options = [];
  for (const rent of rentCandidates) {
    const walkToRent = travel.walk(origin, rent);
    const pickup = estimateBikes(rent, walkToRent, snapshotTime);
    if (Math.floor(pickup.bikes) < 1) continue;

    for (const ret of returnCandidates) {
      if (ret.id === rent.id) continue;
      const ride = travel.ride(rent, ret);
      const arrival = estimateBikes(ret, walkToRent + ride, snapshotTime);
      const docksAtArrival = ret.bikes + ret.docks - arrival.bikes;
      if (Math.floor(docksAtArrival) < 1) continue;

      const walkFromReturn = travel.walk(ret, destination);
      const fewBikes = pickup.bikes < LOW_THRESHOLD;
      const fewDocks = docksAtArrival < LOW_THRESHOLD;
      const totalMinutes = walkToRent + ride + walkFromReturn;
      options.push({
        rent,
        ret,
        walkToRent,
        ride,
        rideMeters: travel.rideMeters(rent, ret),
        walkFromReturn,
        totalMinutes,
        bikesAtPickup: pickup.bikes,
        docksAtArrival,
        docksForecasted: arrival.forecasted,
        fewBikes,
        fewDocks,
        score: totalMinutes + RISK_PENALTY_MINUTES * (fewBikes + fewDocks),
      });
    }
  }

  options.sort((a, b) => a.score - b.score);
  return {
    options: options.slice(0, 3),
    walkOnlyMinutes: travel.walk(origin, destination),
    exact: travel.exact,
  };
}

-- 熱門站點：近 7 天車輛流動量（每 10 分鐘可借車數變化的絕對值加總）最高的站點
--
-- 預測只做熱門站點：流動量低的站點車數幾乎不變，「1 小時後等於現在」就已經很準，預測沒有價值；
-- 訓練資料也因此小一個數量級，壓低 BigQuery ML 的訓練費用。

select
    station_uid,
    sum(abs(bikes_change_10m)) as bikes_moved_7d,
    count(*) as observations,
    row_number() over (order by sum(abs(bikes_change_10m)) desc, station_uid) as popularity_rank
from {{ ref('ml_station_features') }}
where feature_ts >= timestamp_sub(current_timestamp(), interval 7 day)
  and bikes_change_10m is not null
group by station_uid
qualify popularity_rank <= {{ var('ml_popular_station_count') }}

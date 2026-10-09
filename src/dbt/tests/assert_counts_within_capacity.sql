-- 可借＋可還不應超過總車位數（以警告呈現：站點擴充時車位數可能暫時不同步）
{{ config(severity='warn') }}

select f.station_uid, f.source_updated_at, f.bikes_available, f.docks_available, d.capacity
from {{ ref('fct_bike_availability') }} as f
join {{ ref('dim_bike_station') }} as d
  on f.station_uid = d.station_uid
 and f.source_updated_at >= d.valid_from
 and (d.valid_to is null or f.source_updated_at < d.valid_to)
where f.source_updated_at >= timestamp_sub(current_timestamp(), interval 1 day)
  and f.bikes_available + f.docks_available > d.capacity

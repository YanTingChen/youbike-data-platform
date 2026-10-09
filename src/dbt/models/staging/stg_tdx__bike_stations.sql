-- 站點 staging：取每個站點最近一次擷取的資料，供 snapshot 比對變動
-- 只看最近 3 天的分區，避免每次掃描整張歷史表

select
    station_uid,
    station_id,
    authority_id,
    station_name,
    station_name_en,
    address,
    address_en,
    lat,
    lng,
    capacity,
    service_type,
    city,
    ingested_at
from {{ source('tdx_raw', 'bike_stations') }}
where ingested_at >= timestamp_sub(current_timestamp(), interval 3 day)
  and station_uid is not null
qualify row_number() over (partition by station_uid order by ingested_at desc) = 1

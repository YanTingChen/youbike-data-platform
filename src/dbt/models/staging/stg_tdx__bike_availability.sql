-- 即時車況 staging：只做型態整理與基本過濾，不去重（去重在 fct 增量模型中處理）

select
    station_uid,
    station_id,
    service_type,
    service_status,
    service_status = 1 as is_in_service,
    bikes_available,
    docks_available,
    general_bikes_available,
    ebikes_available,
    source_updated_at,
    api_updated_at,
    city,
    ingested_at
from {{ source('tdx_raw', 'bike_availability') }}
where station_uid is not null
  and source_updated_at is not null

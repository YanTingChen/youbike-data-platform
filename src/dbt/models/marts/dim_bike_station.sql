-- 站點維度（SCD Type 2）：每個站點的每個版本一列
-- 查「現在」的站點用 is_current；查歷史時以時間落在 valid_from ~ valid_to 之間來 join

select
    to_hex(md5(concat(station_uid, '|', cast(dbt_valid_from as string)))) as station_sk,
    station_uid,
    station_id,
    station_name,
    station_name_en,
    address,
    address_en,
    lat,
    lng,
    capacity,
    service_type,
    city,
    dbt_valid_from as valid_from,
    dbt_valid_to as valid_to,
    dbt_valid_to is null as is_current
from {{ ref('snap_bike_stations') }}

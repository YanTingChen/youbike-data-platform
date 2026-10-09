-- 每站每小時的使用狀況
--
-- empty_ratio／full_ratio 是「觀測到空站／滿站的比例」，每筆觀測權重相同。

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['station_uid', 'hour_local'],
        partition_by={'field': 'local_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['station_uid']
    )
}}

with availability as (

    select
        station_uid,
        bikes_available,
        docks_available,
        datetime_trunc(datetime(source_updated_at, '{{ var("local_timezone") }}'), hour) as hour_local,
        local_date
    from {{ ref('fct_bike_availability') }}
    where is_in_service
    {% if is_incremental() %}
      -- 從整點開始回看，確保重算的每個小時都是完整的（當地時區與 UTC 差整數小時，整點對齊）
      and source_updated_at >= timestamp_trunc(
          timestamp_sub(current_timestamp(), interval {{ var('lookback_hours') }} hour), hour
      )
    {% endif %}

),

stations as (

    select station_uid, station_name, capacity, lat, lng
    from {{ ref('dim_bike_station') }}
    where is_current

)

select
    a.station_uid,
    s.station_name,
    s.capacity,
    s.lat,
    s.lng,
    a.hour_local,
    a.local_date,
    count(*) as observations,
    round(avg(a.bikes_available), 2) as avg_bikes_available,
    min(a.bikes_available) as min_bikes_available,
    round(avg(a.docks_available), 2) as avg_docks_available,
    round(safe_divide(countif(a.bikes_available = 0), count(*)), 4) as empty_ratio,
    round(safe_divide(countif(a.docks_available = 0), count(*)), 4) as full_ratio
from availability as a
left join stations as s using (station_uid)
group by 1, 2, 3, 4, 5, 6, 7

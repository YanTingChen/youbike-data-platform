-- 預測模型的特徵表：每個站點、每 10 分鐘一列
--
-- 訓練與推論讀同一張表，特徵只在這裡計算一次，避免兩邊各寫一套而產生不一致（training/serving skew）。
-- 標籤 bikes_available_at_target 是「預測時距之後」的實際可借車數：
--   剛產生的列還沒有答案（null），等時間到了，下一輪增量回看時才補上；訓練只用有標籤的列，推論用最新的列。
-- 時間對齊用「自我 join 到確切的時間桶」而不是 lag()：擷取偶爾會漏一輪，lag() 會默默拿到更早的資料。

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['station_uid', 'feature_ts'],
        partition_by={'field': 'feature_ts', 'data_type': 'timestamp', 'granularity': 'day'},
        cluster_by=['station_uid'],
        incremental_predicates=[
            "DBT_INTERNAL_DEST.feature_ts >= timestamp_sub(current_timestamp(), interval 2 day)"
        ]
    )
}}

{% set horizon = var('forecast_horizon_minutes') %}
{% set tz = var('local_timezone') %}

with bucketed as (

    select
        station_uid,
        -- 對齊到 10 分鐘的時間桶
        timestamp_seconds(600 * div(unix_seconds(source_updated_at), 600)) as bucket_ts,
        source_updated_at,
        bikes_available,
        docks_available
    from {{ ref('fct_bike_availability') }}
    where is_in_service
      and bikes_available is not null
      and docks_available is not null
    {% if is_incremental() %}
      -- 比要重算的範圍多讀 2 小時：最早的那幾列也需要 60 分鐘前的資料來算變化量
      and source_updated_at >= timestamp_sub(
          current_timestamp(), interval {{ var('lookback_hours') + 2 }} hour
      )
    {% endif %}

),

observations as (

    -- 同一個時間桶有多筆時取最新的一筆
    select station_uid, bucket_ts, bikes_available, docks_available
    from bucketed
    qualify row_number() over (partition by station_uid, bucket_ts order by source_updated_at desc) = 1

)

select
    cur.station_uid,
    cur.bucket_ts as feature_ts,
    timestamp_add(cur.bucket_ts, interval {{ horizon }} minute) as target_ts,

    cur.bikes_available,
    cur.docks_available,
    cur.bikes_available + cur.docks_available as total_docks,
    safe_divide(cur.bikes_available, cur.bikes_available + cur.docks_available) as fill_ratio,

    -- 近期趨勢：正值代表車變多
    cur.bikes_available - lag_10.bikes_available as bikes_change_10m,
    cur.bikes_available - lag_30.bikes_available as bikes_change_30m,
    cur.bikes_available - lag_60.bikes_available as bikes_change_60m,

    -- 時段與星期存成字串，讓模型當作類別而不是連續數值（23 點與 0 點其實相鄰）
    format_datetime('%H', datetime(cur.bucket_ts, '{{ tz }}')) as hour_of_day,
    format_datetime('%u', datetime(cur.bucket_ts, '{{ tz }}')) as day_of_week,  -- 1 = 週一 … 7 = 週日
    extract(dayofweek from datetime(cur.bucket_ts, '{{ tz }}')) in (1, 7) as is_weekend,

    target.bikes_available as bikes_available_at_target

from observations as cur
left join observations as lag_10
    on cur.station_uid = lag_10.station_uid
    and lag_10.bucket_ts = timestamp_sub(cur.bucket_ts, interval 10 minute)
left join observations as lag_30
    on cur.station_uid = lag_30.station_uid
    and lag_30.bucket_ts = timestamp_sub(cur.bucket_ts, interval 30 minute)
left join observations as lag_60
    on cur.station_uid = lag_60.station_uid
    and lag_60.bucket_ts = timestamp_sub(cur.bucket_ts, interval 60 minute)
left join observations as target
    on cur.station_uid = target.station_uid
    and target.bucket_ts = timestamp_add(cur.bucket_ts, interval {{ horizon }} minute)
{% if is_incremental() %}
where cur.bucket_ts >= timestamp_sub(current_timestamp(), interval {{ var('lookback_hours') }} hour)
{% endif %}

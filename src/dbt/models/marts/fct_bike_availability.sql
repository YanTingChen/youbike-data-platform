-- 車況事實表：每個站點、每次「來源更新」一列
--
-- 去重：同一站點在來源沒更新時，每 10 分鐘仍會抓到同一筆資料，
--       以 (station_uid, source_updated_at) 為唯一鍵，只保留最早抓到的那筆
-- 增量：每次只處理最近 lookback_hours 小時擷取的資料，再以 merge 寫入，重跑不會重複
-- 分區：依來源更新時間按天分區、依站點叢集；incremental_predicates 限制 merge 時目標表只掃最近 2 天

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['station_uid', 'source_updated_at'],
        partition_by={'field': 'source_updated_at', 'data_type': 'timestamp', 'granularity': 'day'},
        cluster_by=['station_uid'],
        incremental_predicates=[
            "DBT_INTERNAL_DEST.source_updated_at >= timestamp_sub(current_timestamp(), interval 2 day)"
        ],
        on_schema_change='append_new_columns'
    )
}}

with source as (

    select * from {{ ref('stg_tdx__bike_availability') }}
    {% if is_incremental() %}
    where ingested_at >= timestamp_sub(
        (select max(ingested_at) from {{ this }}),
        interval {{ var('lookback_hours') }} hour
    )
    {% endif %}

)

select
    station_uid,
    service_status,
    is_in_service,
    bikes_available,
    docks_available,
    general_bikes_available,
    ebikes_available,
    source_updated_at,
    date(source_updated_at, '{{ var("local_timezone") }}') as local_date,
    city,
    ingested_at
from source
qualify row_number() over (
    partition by station_uid, source_updated_at
    order by ingested_at
) = 1

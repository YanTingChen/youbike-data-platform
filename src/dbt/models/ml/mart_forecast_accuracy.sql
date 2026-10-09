-- 預測準確度追蹤：把已經「到期」的預測與實際值比對，每小時一列
--
-- 訓練時的評估只代表過去；模型上線後是否仍然準確，要靠持續比對實際結果才知道。
-- 同時計算基準（預測「1 小時後 = 現在」）的誤差：improvement_over_baseline > 0 模型才算有用。
--
-- 這個模型依賴預測表，而預測表要等第一次訓練與推論之後才存在，
-- 所以標上 ml_monitoring 標籤、不放進每小時的主要 dbt build，改由 youbike_ml_predict DAG 在推論後執行。

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['hour_local'],
        partition_by={'field': 'local_date', 'data_type': 'date', 'granularity': 'day'},
        tags=['ml_monitoring']
    )
}}

{% set tz = var('local_timezone') %}
-- 預測要等「預測時距」過後才有答案，所以回看範圍要再加上時距
{% set lookback_hours = var('lookback_hours') + (var('forecast_horizon_minutes') // 60) + 1 %}

with forecasts as (

    select station_uid, feature_ts, forecast_for, bikes_available_now, predicted_bikes_available
    from {{ source('ml', 'station_forecasts') }}
    {% if is_incremental() %}
    where forecast_for >= timestamp_trunc(
        timestamp_sub(current_timestamp(), interval {{ lookback_hours }} hour), hour
    )
    {% endif %}

),

actuals as (

    select station_uid, feature_ts, bikes_available_at_target
    from {{ ref('ml_station_features') }}
    where bikes_available_at_target is not null
    {% if is_incremental() %}
      and feature_ts >= timestamp_sub(current_timestamp(), interval {{ lookback_hours + 2 }} hour)
    {% endif %}

)

select
    datetime_trunc(datetime(f.forecast_for, '{{ tz }}'), hour) as hour_local,
    date(f.forecast_for, '{{ tz }}') as local_date,
    count(*) as forecasts,
    count(distinct f.station_uid) as stations,
    round(avg(abs(f.predicted_bikes_available - a.bikes_available_at_target)), 3) as mae_model,
    round(avg(abs(f.bikes_available_now - a.bikes_available_at_target)), 3) as mae_baseline,
    round(
        1 - safe_divide(
            avg(abs(f.predicted_bikes_available - a.bikes_available_at_target)),
            avg(abs(f.bikes_available_now - a.bikes_available_at_target))
        ),
        4
    ) as improvement_over_baseline
from forecasts as f
inner join actuals as a using (station_uid, feature_ts)
group by 1, 2

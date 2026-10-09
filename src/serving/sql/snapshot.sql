-- 網頁用的資料快照：每個站點一列，含位置、最新車況、以及（熱門站點才有的）1 小時後預測
--
-- 最新車況直接讀 raw 表而不是 fct：fct 每小時才由 dbt 更新一次，raw 每 10 分鐘就有新資料。
-- 只看最近 60 分鐘擷取的資料：站點超過 1 小時沒有資料就不出現在網頁上，而不是顯示過期的車數。

with latest_availability as (

    select station_uid, service_status, bikes_available, docks_available, source_updated_at
    from `{availability}`
    where ingested_at >= timestamp_sub(current_timestamp(), interval 60 minute)
      and bikes_available is not null
      and docks_available is not null
    qualify row_number() over (
        partition by station_uid order by source_updated_at desc, ingested_at desc
    ) = 1

),

latest_forecast as (

    {forecasts_query}

)

select
    s.station_uid,
    s.station_name,
    s.lat,
    s.lng,
    a.bikes_available,
    a.docks_available,
    a.service_status = 1 as in_service,
    a.source_updated_at,
    f.forecast_for,
    f.predicted_bikes_available
from `{stations}` as s
inner join latest_availability as a using (station_uid)
left join latest_forecast as f using (station_uid)
where s.is_current
  and s.lat is not null
  and s.lng is not null
order by s.station_uid

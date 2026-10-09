-- 對每個熱門站點最新的一筆特徵做預測，寫入預測表
--
-- 以 merge 寫入、(station_uid, feature_ts) 為鍵：任務重試或重跑不會產生重複的預測。
-- 只取最近 30 分鐘內的特徵：擷取停擺時寧可不產生預測，也不要拿舊資料預測出看似正常的數字。

merge `{forecasts}` as dest
using (

    select
        station_uid,
        feature_ts,
        target_ts as forecast_for,
        bikes_available as bikes_available_now,
        total_docks,
        round({clipped_prediction}, 1) as predicted_bikes_available,
        timestamp('{model_trained_at}') as model_trained_at,
        current_timestamp() as predicted_at
    from ml.predict(
        model `{model}`,
        (
            select f.*
            from `{features}` as f
            inner join `{popular_stations}` as p using (station_uid)
            where f.feature_ts >= timestamp_sub(current_timestamp(), interval 30 minute)
              and {complete_features}
            qualify row_number() over (partition by f.station_uid order by f.feature_ts desc) = 1
        )
    )

) as src
on dest.station_uid = src.station_uid
    and dest.feature_ts = src.feature_ts
    -- 讓 BigQuery 只掃描目標表最近的分區
    and dest.forecast_for >= timestamp_sub(current_timestamp(), interval 1 day)
when not matched then insert row

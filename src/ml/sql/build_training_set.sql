-- 訓練資料集：熱門站點、最近 {training_days} 天、已有標籤且特徵齊全的列
--
-- 先落成一張表再訓練，有兩個理由：
--   1. BigQuery ML 依 CREATE MODEL 掃描的資料量計費（費率比一般查詢高），先用一般查詢把資料縮小
--   2. 留下「模型到底是用哪些資料訓練的」可供事後查核
-- is_holdout：依時間切分，最後一段資料留作驗證。
-- 時間序列不能隨機切分，否則模型會在訓練時看到驗證期間前後的資料，評估結果會過度樂觀。

create or replace table `{training_set}` as

with labeled as (

    select f.*
    from `{features}` as f
    inner join `{popular_stations}` as p using (station_uid)
    where f.feature_ts >= timestamp_sub(current_timestamp(), interval {training_days} day)
      and f.{label} is not null
      and {complete_features}

),

span as (

    select
        timestamp_sub(
            max(feature_ts),
            interval cast({holdout_fraction} * timestamp_diff(max(feature_ts), min(feature_ts), second) as int64) second
        ) as holdout_from
    from labeled

)

select labeled.*, labeled.feature_ts > span.holdout_from as is_holdout
from labeled
cross join span

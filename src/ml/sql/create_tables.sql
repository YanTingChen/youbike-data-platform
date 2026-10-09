-- ML 流程自己維護的兩張表（不存在才建立）

-- 每次訓練的評估結果：模型有沒有比基準好、隨資料累積是否進步，都看這張表
create table if not exists `{evaluations}` (
    evaluated_at timestamp not null,
    training_days int64,
    train_rows int64,
    holdout_rows int64,
    holdout_from timestamp,
    mae_model float64,
    mae_baseline float64,
    rmse_model float64,
    rmse_baseline float64,
    improvement_over_baseline float64
);

-- 每小時產生的預測；欄位順序與 predict.sql 的 select 一致（merge 以 insert row 寫入）
create table if not exists `{forecasts}` (
    station_uid string not null,
    feature_ts timestamp not null,
    forecast_for timestamp not null,
    bikes_available_now int64,
    total_docks int64,
    predicted_bikes_available float64,
    model_trained_at timestamp,
    predicted_at timestamp
)
partition by date(forecast_for)
cluster by station_uid;

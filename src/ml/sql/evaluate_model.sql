-- 在驗證資料上評估候選模型，並與基準比較，結果寫入評估紀錄表
--
-- 基準（baseline）：預測「目標時間的可借車數 = 現在的可借車數」。
-- 這個不需要任何模型的猜法在短時距下相當準，模型的誤差必須比它小才有存在的價值。

insert into `{evaluations}` (
    evaluated_at, training_days, train_rows, holdout_rows, holdout_from,
    mae_model, mae_baseline, rmse_model, rmse_baseline, improvement_over_baseline
)

with predictions as (

    select
        feature_ts,
        bikes_available,
        {label} as actual,
        {clipped_prediction} as predicted
    from ml.predict(
        model `{candidate_model}`,
        (select * from `{training_set}` where is_holdout)
    )

),

metrics as (

    select
        count(*) as holdout_rows,
        min(feature_ts) as holdout_from,
        avg(abs(predicted - actual)) as mae_model,
        avg(abs(bikes_available - actual)) as mae_baseline,
        sqrt(avg(pow(predicted - actual, 2))) as rmse_model,
        sqrt(avg(pow(bikes_available - actual, 2))) as rmse_baseline
    from predictions

)

select
    current_timestamp(),
    {training_days},
    (select count(*) from `{training_set}` where not is_holdout),
    holdout_rows,
    holdout_from,
    mae_model,
    mae_baseline,
    rmse_model,
    rmse_baseline,
    1 - safe_divide(mae_model, mae_baseline)
from metrics

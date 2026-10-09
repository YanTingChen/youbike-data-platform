-- 訓練線性迴歸模型。同一份 SQL 用兩次：
--   候選模型：where_clause = 排除驗證資料 → 用來評估
--   正式模型：where_clause = 全部資料     → 評估完成後，用包含最新資料的全部資料重新訓練並上線
--
-- 選線性迴歸的理由：BigQuery ML 內建、訓練費用最低，係數可以直接解讀（ML.WEIGHTS）。


create or replace model `{model}`
options (
    model_type = 'LINEAR_REG',
    input_label_cols = ['{label}'],
    -- 驗證資料已經自己依時間切好，不讓 BigQuery ML 再隨機切一次
    data_split_method = 'NO_SPLIT',
    -- 站點是 200 個類別的特徵，資料少時容易過度擬合，加上 L2 正規化
    l2_reg = 1.0
) as

select
    {feature_columns},
    {label}
from `{training_set}`
where {where_clause}

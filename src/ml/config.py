"""ML 流程的設定與共用常數。"""

from __future__ import annotations

import os
from dataclasses import dataclass

# dbt 完成特徵表後發出的 Airflow Asset 事件名稱；推論 DAG 以它為排程，不必猜 dbt 何時跑完
FEATURES_ASSET = "youbike_ml_station_features"

LABEL = "bikes_available_at_target"

# 模型使用的特徵，訓練與推論都從 dbt 的 ml_station_features 取同樣的欄位
FEATURE_COLUMNS = (
    "station_uid",  # 類別特徵：每個站點有自己的基準值
    "bikes_available",
    "docks_available",
    "total_docks",
    "fill_ratio",
    "bikes_change_10m",
    "bikes_change_30m",
    "bikes_change_60m",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
)

# 訓練與推論都只用這些欄位齊全的列（SQL 中特徵表的別名是 f）。
# 缺值來自擷取漏了一輪或站點剛上線；讓 BigQuery ML 自動補平均值等於捏造資料，寧可不用這一列
COMPLETE_FEATURES = " and ".join(
    f"f.{column} is not null"
    for column in ("fill_ratio", "bikes_change_10m", "bikes_change_30m", "bikes_change_60m")
)

# 線性迴歸不知道車數的物理範圍，預測值要夾在 0 與總車位數之間。
# 評估與推論用同一個運算式，評估出來的誤差才等於上線後的誤差
CLIPPED_PREDICTION = f"least(greatest(predicted_{LABEL}, 0), total_docks)"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少環境變數 {name}，請參考 .env.example 設定")
    return value


@dataclass(frozen=True)
class MLSettings:
    gcp_project_id: str
    bq_location: str
    # dbt 的 ml 模型所在的資料集（dbt 的命名規則：<BQ_DBT_DATASET>_ml），模型與預測結果也放在這裡
    dataset: str
    # 訓練只用最近幾天的資料：使用型態會隨季節改變，太舊的資料幫助不大，也讓訓練費用有上限
    training_days: int
    # 時間上最後這個比例的資料留作驗證，不參與訓練
    holdout_fraction: float
    # 有標籤的訓練資料少於這個數量就不訓練
    min_training_rows: int

    @classmethod
    def from_env(cls) -> MLSettings:
        return cls(
            gcp_project_id=_require("GCP_PROJECT_ID"),
            bq_location=os.environ.get("BQ_LOCATION", "asia-east1"),
            dataset=os.environ.get("BQ_DBT_DATASET", "youbike") + "_ml",
            training_days=int(os.environ.get("ML_TRAINING_DAYS", "28")),
            holdout_fraction=float(os.environ.get("ML_HOLDOUT_FRACTION", "0.2")),
            min_training_rows=int(os.environ.get("ML_MIN_TRAINING_ROWS", "1000")),
        )

    def table(self, name: str) -> str:
        return f"{self.gcp_project_id}.{self.dataset}.{name}"

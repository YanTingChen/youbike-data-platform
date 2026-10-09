"""ML 流程的單元測試：設定與 SQL 範本（不需要連 BigQuery）。"""

import re

import pytest

from ml.config import CLIPPED_PREDICTION, COMPLETE_FEATURES, FEATURE_COLUMNS, LABEL, MLSettings
from ml.pipeline import SQL_DIR, render

SETTINGS = MLSettings(
    gcp_project_id="my-project",
    bq_location="asia-east1",
    dataset="youbike_ml",
    training_days=28,
    holdout_fraction=0.2,
    min_training_rows=1000,
)
# 需要呼叫端額外提供的參數
EXTRA_PARAMS = {
    "train_model": {"where_clause": "not is_holdout"},
    "predict": {"model_trained_at": "2026-10-08T03:30:00+00:00"},
}


def test_settings_follow_dbt_dataset_naming(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("BQ_DBT_DATASET", "analytics")

    settings = MLSettings.from_env()

    # dbt 把 ml 模型建在 <BQ_DBT_DATASET>_ml，ML 流程必須讀寫同一個資料集
    assert settings.dataset == "analytics_ml"
    assert settings.table("station_forecasts") == "my-project.analytics_ml.station_forecasts"


@pytest.mark.parametrize("name", sorted(path.stem for path in SQL_DIR.glob("*.sql")))
def test_every_sql_template_renders_completely(name):
    sql = render(name, SETTINGS, **EXTRA_PARAMS.get(name, {}))

    # 沒有漏填的佔位符，資料表都是完整的 專案.資料集.名稱
    assert not re.search(r"[{}]", sql)
    assert "`my-project.youbike_ml." in sql


def test_training_selects_exactly_the_features_and_label():
    sql = render("train_model", SETTINGS, where_clause="true")
    selected = sql.split(") as", 1)[1]

    for column in (*FEATURE_COLUMNS, LABEL):
        assert re.search(rf"\b{column}\b", selected)
    # 驗證旗標與目標時間不能混進特徵，否則等於把答案的線索交給模型
    assert "is_holdout" not in selected.split("from")[0]
    assert "target_ts" not in selected


def test_candidate_and_final_models_are_different_objects():
    candidate = render(
        "train_model",
        SETTINGS,
        model=SETTINGS.table("bike_availability_forecaster_candidate"),
        where_clause="x",
    )
    final = render("train_model", SETTINGS, where_clause="x")

    assert "bike_availability_forecaster_candidate`" in candidate
    assert "bike_availability_forecaster`" in final


def test_training_and_serving_require_the_same_complete_features():
    # 訓練時排除缺值的列，推論時也必須排除，否則模型會遇到訓練時沒見過的輸入
    assert COMPLETE_FEATURES in render("build_training_set", SETTINGS)
    assert COMPLETE_FEATURES in render("predict", SETTINGS, model_trained_at="2026-10-08T03:30:00+00:00")


def test_evaluation_and_serving_clip_predictions_the_same_way():
    # 評估用的預測值必須與上線時完全相同，評估出來的誤差才有意義
    assert CLIPPED_PREDICTION in render("evaluate_model", SETTINGS)
    assert CLIPPED_PREDICTION in render("predict", SETTINGS, model_trained_at="2026-10-08T03:30:00+00:00")

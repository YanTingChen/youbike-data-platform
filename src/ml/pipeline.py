"""依序執行 BigQuery ML SQL，供排程與命令列共用。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ml.config import CLIPPED_PREDICTION, COMPLETE_FEATURES, FEATURE_COLUMNS, LABEL, MLSettings

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"

MODEL = "bike_availability_forecaster"
CANDIDATE_MODEL = "bike_availability_forecaster_candidate"


class NotReadyError(RuntimeError):
    """前置條件還沒滿足（資料不夠、模型尚未訓練）。不是程式錯誤，呼叫端應該略過而不是告警。"""


def render(name: str, settings: MLSettings, **extra: Any) -> str:
    """讀取 sql/<name>.sql 並填入資料表名稱與設定值。"""
    params = {
        "features": settings.table("ml_station_features"),
        "popular_stations": settings.table("ml_popular_stations"),
        "training_set": settings.table("ml_training_set"),
        "evaluations": settings.table("model_evaluations"),
        "forecasts": settings.table("station_forecasts"),
        "model": settings.table(MODEL),
        "candidate_model": settings.table(CANDIDATE_MODEL),
        "label": LABEL,
        "feature_columns": ",\n    ".join(FEATURE_COLUMNS),
        "clipped_prediction": CLIPPED_PREDICTION,
        "complete_features": COMPLETE_FEATURES,
        "training_days": settings.training_days,
        "holdout_fraction": settings.holdout_fraction,
        **extra,
    }
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8").format(**params)


def _client(settings: MLSettings):
    from google.cloud import bigquery

    return bigquery.Client(project=settings.gcp_project_id, location=settings.bq_location)


def _run(client, sql: str):
    job = client.query(sql)
    result = job.result()  # 等待完成；失敗時拋出例外讓 Airflow 重試
    logger.info("查詢完成：%s，處理 %s bytes", job.job_id, job.total_bytes_processed)
    return job, result


def train(settings: MLSettings) -> dict[str, Any]:
    """訓練並評估模型，回傳這次的評估結果。"""
    client = _client(settings)
    _run(client, render("create_tables", settings))
    _run(client, render("build_training_set", settings))

    _, rows = _run(
        client,
        f"select countif(not is_holdout) as train_rows, countif(is_holdout) as holdout_rows "
        f"from `{settings.table('ml_training_set')}`",
    )
    counts = dict(next(iter(rows)))
    if counts["train_rows"] < settings.min_training_rows or counts["holdout_rows"] == 0:
        raise NotReadyError(
            f"訓練資料不足（訓練 {counts['train_rows']} 列、驗證 {counts['holdout_rows']} 列，"
            f"至少需要 {settings.min_training_rows} 列訓練資料），等資料累積後再訓練"
        )

    _run(
        client,
        render("train_model", settings, model=settings.table(CANDIDATE_MODEL), where_clause="not is_holdout"),
    )
    _run(client, render("evaluate_model", settings))
    _run(client, render("train_model", settings, where_clause="true"))

    _, rows = _run(
        client,
        f"select * from `{settings.table('model_evaluations')}` order by evaluated_at desc limit 1",
    )
    evaluation = {key: _jsonable(value) for key, value in dict(next(iter(rows))).items()}
    logger.info(
        "訓練完成：模型 MAE %.3f、基準 MAE %.3f、相對基準改善 %.1f%%（訓練 %d 列、驗證 %d 列）",
        evaluation["mae_model"],
        evaluation["mae_baseline"],
        100 * evaluation["improvement_over_baseline"],
        evaluation["train_rows"],
        evaluation["holdout_rows"],
    )
    return evaluation


def predict(settings: MLSettings) -> int:
    """用正式模型對熱門站點的最新特徵做預測，回傳新增的預測筆數。"""
    from google.api_core.exceptions import NotFound

    client = _client(settings)
    try:
        model = client.get_model(settings.table(MODEL))
    except NotFound as exc:
        raise NotReadyError("模型尚未訓練，先執行訓練（youbike_ml_train）") from exc

    _run(client, render("create_tables", settings))
    job, _ = _run(client, render("predict", settings, model_trained_at=model.modified.isoformat()))
    inserted = int(job.num_dml_affected_rows or 0)
    logger.info("新增 %d 筆預測（模型訓練於 %s）", inserted, model.modified.isoformat())
    return inserted


def _jsonable(value: Any) -> Any:
    """評估結果會存進 Airflow XCom，時間轉成字串。"""
    return value.isoformat() if hasattr(value, "isoformat") else value

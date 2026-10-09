"""特徵更新後觸發推論；訓練獨立排程，失敗時沿用既有模型。"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag, task
from airflow.sdk.exceptions import AirflowSkipException

from ml import pipeline
from ml.config import FEATURES_ASSET, MLSettings

DBT = "/home/airflow/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/dbt"
DBT_FLAGS = f"--project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=20),
}


@dag(
    dag_id="youbike_ml_train",
    schedule="30 3 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["youbike", "ml"],
)
def youbike_ml_train():
    @task
    def train() -> dict:
        try:
            return pipeline.train(MLSettings.from_env())
        except pipeline.NotReadyError as exc:
            raise AirflowSkipException(str(exc)) from exc

    train()


@dag(
    dag_id="youbike_ml_predict",
    schedule=[Asset(FEATURES_ASSET)],
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["youbike", "ml"],
)
def youbike_ml_predict():
    @task
    def predict() -> int:
        try:
            return pipeline.predict(MLSettings.from_env())
        except pipeline.NotReadyError as exc:
            raise AirflowSkipException(str(exc)) from exc

    # 預測表存在之後才能建立準確度模型，所以不放在主要的 dbt build 裡
    accuracy = BashOperator(
        task_id="forecast_accuracy",
        bash_command=f"{DBT} build --select tag:ml_monitoring {DBT_FLAGS}",
    )

    predict() >> accuracy


youbike_ml_train()
youbike_ml_predict()

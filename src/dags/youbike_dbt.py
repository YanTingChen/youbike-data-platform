"""擷取與轉換分開排程，避免轉換失敗中斷資料保存。"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag

from ml.config import FEATURES_ASSET

DBT = "/home/airflow/dbt-venv/bin/dbt"  # dbt 安裝在獨立 venv，避免與 Airflow 套件版本衝突
DBT_DIR = "/opt/airflow/dbt"
DBT_FLAGS = f"--project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"


@dag(
    dag_id="youbike_dbt",
    schedule="5 * * * *",  # 每小時第 5 分，讓整點那一輪擷取先完成
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Taipei"),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "data-eng", "retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["youbike", "dbt", "transform"],
)
def youbike_dbt():
    freshness = BashOperator(task_id="source_freshness", bash_command=f"{DBT} source freshness {DBT_FLAGS}")
    # snapshot 讀的是 staging view，必須連同上游一起建（+），否則首次執行時 view 還不存在
    snapshot = BashOperator(
        task_id="snapshot",
        bash_command=f"{DBT} build --select +resource_type:snapshot {DBT_FLAGS}",
    )
    # ml_monitoring 依賴預測表，由 youbike_ml_predict 在推論後執行，這裡排除
    # outlets：build 成功就發出特徵表的 Asset 事件，觸發推論 DAG
    build = BashOperator(
        task_id="build",
        bash_command=f"{DBT} build --exclude resource_type:snapshot tag:ml_monitoring {DBT_FLAGS}",
        outlets=[Asset(FEATURES_ASSET)],
    )

    freshness >> snapshot >> build


youbike_dbt()

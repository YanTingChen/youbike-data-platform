# Airflow 映像：加裝擷取程式需要的套件，並把 dbt 裝在獨立的 venv
ARG AIRFLOW_VERSION=3.2.2
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION
COPY requirements-airflow.txt /tmp/requirements-airflow.txt
# 一併指定 apache-airflow 版本，避免安裝其他套件時把 Airflow 升級或降級
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /tmp/requirements-airflow.txt

# dbt 與 Airflow 的相依套件常有版本衝突，分開安裝最穩定
RUN python -m venv /home/airflow/dbt-venv \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core~=1.12.0" "dbt-bigquery~=1.12.0"

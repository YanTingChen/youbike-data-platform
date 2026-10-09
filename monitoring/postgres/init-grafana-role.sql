-- 建立 Grafana 專用的唯讀帳號（可重複執行）

select format('create role grafana_ro login password %L', :'password')
where not exists (select from pg_roles where rolname = 'grafana_ro') \gexec
alter role grafana_ro password :'password';

-- 串流資料庫可能還沒建立（從沒啟動過串流）；先建好，儀表板才不會連線失敗
select 'create database youbike_streaming'
where not exists (select from pg_database where datname = 'youbike_streaming') \gexec

grant connect on database youbike_streaming, airflow to grafana_ro;

\connect youbike_streaming
grant usage on schema public to grafana_ro;
grant select on all tables in schema public to grafana_ro;
-- 之後由 airflow 帳號新建的表（串流啟動時才建表）也自動可讀
alter default privileges for role airflow in schema public grant select on tables to grafana_ro;

\connect airflow
grant usage on schema public to grafana_ro;
-- Airflow 中繼資料庫只開放 DAG 執行紀錄；connection、variable 等含機密的表不給讀
grant select on dag_run to grafana_ro;

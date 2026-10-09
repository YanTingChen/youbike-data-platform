-- 事實表的唯一鍵不能重複（驗證去重與 merge 邏輯）
select station_uid, source_updated_at, count(*) as n
from {{ ref('fct_bike_availability') }}
group by 1, 2
having count(*) > 1

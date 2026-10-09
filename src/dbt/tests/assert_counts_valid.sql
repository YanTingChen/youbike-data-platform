-- 可借車數、可還空位不可為負數
select *
from {{ ref('fct_bike_availability') }}
where bikes_available < 0 or docks_available < 0

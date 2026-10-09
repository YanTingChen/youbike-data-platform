-- 串流結果的資料表（PostgreSQL）。串流啟動時執行，已存在則略過

create table if not exists station_window_stats (
    station_uid            text not null,
    window_start           timestamptz not null,
    window_end             timestamptz not null,
    observations           integer not null,
    avg_bikes_available    double precision,
    min_bikes_available    integer,
    max_bikes_available    integer,
    avg_docks_available    double precision,
    empty_observations     integer not null,
    full_observations      integer not null,
    updated_at             timestamptz not null default now(),
    primary key (station_uid, window_start)
);
create index if not exists station_window_stats_window_start_idx
    on station_window_stats (window_start);

create table if not exists station_status_events (
    station_uid                 text not null,
    status                      text not null,
    previous_status             text,
    changed_at                  timestamptz not null,
    previous_duration_seconds   bigint,
    bikes_available             integer,
    docks_available             integer,
    detected_at                 timestamptz not null default now(),
    primary key (station_uid, changed_at)
);
create index if not exists station_status_events_changed_at_idx
    on station_status_events (changed_at);

-- 站點的參考資料：上面兩張表只有站點代碼，儀表板靠這張表顯示站名
create table if not exists stations (
    station_uid    text primary key,
    station_name   text not null,
    lat            double precision,
    lng            double precision,
    capacity       integer,
    updated_at     timestamptz not null default now()
);

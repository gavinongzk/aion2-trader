-- Daily price summaries in Supabase: one row per server, item and day (the day's median cheapest
-- price and listings), for all 20 Asia servers, kept 30 days. The hourly job uploads each complete
-- day once (python -m aion2 publish) and deletes days older than 30. Run once, in the SQL editor.
create table if not exists public.daily_prices (
  server_id integer not null,
  item_key bigint not null,
  day date not null,
  price double precision,          -- the day's median cheapest price
  listings integer,                -- the day's median number of listings
  primary key (server_id, item_key, day)
);
create index if not exists daily_prices_day on public.daily_prices (day);
-- No policies: only the secret key (the hourly job) can read or write.
alter table public.daily_prices enable row level security;

-- For example, an item's world price by day (the median across the other servers):
--   select day, percentile_cont(0.5) within group (order by price) as world
--   from daily_prices where item_key = 610620013 and server_id <> 12510
--   group by day order by day;

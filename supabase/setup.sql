-- What the online bot keeps in Supabase. Run once, in the project's SQL editor.
--
-- 1. The Discord price alerts (/watch), shared by the hourly job (which checks them) and the
--    slash-command function on Vercel (which adds and removes them).
create table if not exists public.watches (
  user_id text not null,              -- Discord user id
  server_id integer not null,         -- the game server (12510: Hadala)
  item_key bigint not null,
  name text,
  below double precision not null,    -- alert when listed at or below this
  channel_id text not null,           -- where to ping
  last_alert_price double precision,  -- so one listing doesn't alert every hour
  created_at timestamptz not null default now(),
  primary key (user_id, server_id, item_key)
);
-- No policies: only the service key (the job and the function, server-side) can read or write.
alter table public.watches enable row level security;

-- 2. The hourly trigger. GitHub's own schedule only manages about three runs a day, so Supabase's
--    scheduler starts the job instead, at 7 minutes past every hour.
--    First store a GitHub token that can start the workflow, in the vault (run this line alone,
--    with your token in place of the dots):
--      select vault.create_secret('github_pat_...', 'github_dispatch_token');
create extension if not exists pg_cron;
create extension if not exists pg_net;
select cron.schedule('aion2-refresh', '7 * * * *', $$
  select net.http_post(
    url := 'https://api.github.com/repos/gavinongzk/aion2-trader/actions/workflows/refresh.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'aion2-trader-cron'),
    body := '{"ref": "main"}'::jsonb)
$$);

-- To check it: select * from cron.job_run_details order by start_time desc limit 5;
-- and the responses: select status_code, content from net._http_response order by created desc limit 5;

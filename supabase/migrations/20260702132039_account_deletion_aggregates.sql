-- Account deletion support (docs/roadmap-ios-launch.md §2b, aggregate-then-delete).
-- Policy: when a user deletes their account, their reports are folded into
-- identity-free daily counts (preserving all YoY/forecast value), then their
-- identified rows are removed via FK cascade when the auth user is deleted.

-- daily_report_aggregates (also the eventual home of Phase D's scheduled job)
create table public.daily_report_aggregates (
  beach_id     text not null,
  report_date  date not null,
  report_type  text not null,
  count        int not null default 0,
  primary key (beach_id, report_date, report_type)
);
alter table public.daily_report_aggregates enable row level security;
-- no policies -> deny by default for anon/authenticated; service_role only
grant select, insert, update, delete on public.daily_report_aggregates to service_role;
-- Remember 2026-07-02's lesson: "Automatically expose new tables" being off
-- withholds base grants from service_role too, not just anon/authenticated -
-- this GRANT is required, BYPASSRLS does not substitute for it.

-- Atomic aggregation step, run by the backend immediately before deleting a
-- user via the Auth admin API. SECURITY DEFINER so it can run the GROUP BY +
-- upsert as the function owner regardless of caller (backend already calls
-- this only with a server-verified reporter_id, never client-supplied).
create or replace function public.aggregate_reports_before_delete(p_reporter_id uuid)
returns void
language sql
security definer
set search_path = public
as $$
  insert into public.daily_report_aggregates (beach_id, report_date, report_type, count)
  select beach_id, created_at::date, report_type, count(*)::int
  from public.reports
  where reporter_id = p_reporter_id
  group by beach_id, created_at::date, report_type
  on conflict (beach_id, report_date, report_type)
  do update set count = daily_report_aggregates.count + excluded.count;
$$;
revoke all on function public.aggregate_reports_before_delete(uuid) from public;
grant execute on function public.aggregate_reports_before_delete(uuid) to service_role;

-- FK cascade: deleting the auth user (via admin API, after aggregation above)
-- now removes their identified rows instead of failing.
alter table public.reports
  drop constraint reports_reporter_id_fkey,
  add constraint reports_reporter_id_fkey
    foreign key (reporter_id) references auth.users(id) on delete cascade;

alter table public.reporter_beach_standing
  drop constraint reporter_beach_standing_reporter_id_fkey,
  add constraint reporter_beach_standing_reporter_id_fkey
    foreign key (reporter_id) references auth.users(id) on delete cascade;

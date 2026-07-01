-- Beach Pulse (community reports) schema.
-- See docs/handoff-beach-pulse.md §2 for the design rationale.

-- reports
create table public.reports (
  id             uuid primary key default gen_random_uuid(),
  beach_id       text not null,                       -- matches BEACH_CONFIG key
  report_type    text not null,                       -- see SEVERITY_TIER keys in handoff §3
  severity_tier  text not null check (severity_tier in ('low','moderate','high')),
  notes          text check (char_length(notes) <= 140),
  reporter_id    uuid not null references auth.users(id),
  status         text not null default 'published'
                 check (status in ('published','escalated','held_for_review')),
  corroborated_by uuid[] not null default '{}',
  created_at     timestamptz not null default now(),
  beach_lat      double precision,
  beach_lng      double precision
);
create index reports_beach_created_idx on public.reports (beach_id, created_at desc);
create index reports_beach_type_created_idx on public.reports (beach_id, report_type, created_at desc);

-- Local Guide standing (Phase C reads/writes this; safe to create now)
create table public.reporter_beach_standing (
  reporter_id        uuid not null references auth.users(id),
  beach_id           text not null,
  corroborated_count int not null default 0,
  is_local_guide     boolean not null default false,
  points             int not null default 0,
  primary key (reporter_id, beach_id)
);
alter table public.reporter_beach_standing enable row level security;
-- no policies defined -> no anon/authenticated access at all (deny by default);
-- only the backend's service_role (which bypasses RLS) reads/writes this table

-- RLS (defense-in-depth; backend uses service_role and bypasses this)
alter table public.reports enable row level security;

create policy "read visible reports" on public.reports
  for select using (status in ('published','escalated'));

create policy "insert own reports" on public.reports
  for insert to authenticated
  with check (reporter_id = auth.uid());
-- no update/delete policies -> clients cannot edit or remove reports

-- Favorite beaches on the user profile (owner request 2026-07-02).
-- Server-side (vs. the device-local home beach) so favorites sync across
-- devices and feed the planned digest, push-notification, and widget features.

create table public.user_favorites (
  user_id    uuid not null references auth.users(id) on delete cascade,
  beach_id   text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, beach_id)
);
alter table public.user_favorites enable row level security;
-- no policies -> deny by default for anon/authenticated; backend service_role only
grant select, insert, update, delete on public.user_favorites to service_role;
-- (explicit grant required: "Automatically expose new tables" is off and that
-- withholds base grants from service_role too - see 2026-07-02 lesson)

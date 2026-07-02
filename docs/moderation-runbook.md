# Moderation runbook — Beach Pulse reports

Founder-scale moderation via direct SQL, run through the linked Supabase CLI
(`supabase db query --linked "..."`). No admin UI exists yet, and per
[docs/roadmap-ios-launch.md](roadmap-ios-launch.md) Track 4, none is planned
until report volume justifies building one — this runbook is the interim
tool. All queries use `service_role`-equivalent access via the CLI's own
auth, same as every other migration/verification query run against this
project.

---

## 1. List reports currently held for review

Spike detection (`reports.py::_maybe_hold_spike`) sets `status =
'held_for_review'` when 5+ high-tier reports of one type land at one beach
within 15 minutes, all from accounts with no prior corroborated reports —
the abuse signature. These never surface publicly until you act.

```sql
select id, beach_id, report_type, severity_tier, notes, reporter_id, created_at
from public.reports
where status = 'held_for_review'
order by created_at desc;
```

## 2. Release a held report (it was legitimate)

```sql
update public.reports
set status = 'published'
where id = '<report-id>';
```

## 3. Reject a held report (it was abuse/spam)

Deleting is correct here — a rejected report shouldn't linger with any
status, and it was never counted in `daily_report_aggregates` (aggregation
only happens for a reporter's *own* reports at account-deletion time, not
per-report on rejection).

```sql
delete from public.reports where id = '<report-id>';
```

To reject an entire held batch from one spike event at once:

```sql
delete from public.reports
where status = 'held_for_review'
  and beach_id = '<beach-id>'
  and report_type = '<report-type>'
  and created_at > now() - interval '20 minutes';
```

## 4. Check a reporter's history (deciding trust before releasing)

```sql
select r.id, r.beach_id, r.report_type, r.status, r.created_at
from public.reports r
where r.reporter_id = '<reporter-id>'
order by r.created_at desc
limit 50;

select * from public.reporter_beach_standing where reporter_id = '<reporter-id>';
```

A reporter with a clean history of `published`/`escalated` reports and no
prior `held_for_review` rows is a low-risk release. A reporter who only
appears in held batches is a candidate to leave held (or, if abuse is
repeated, deleted — see §6).

## 5. Find a reporter's email (support/abuse escalation)

Reports never store email or auth identity beyond `reporter_id` (a Supabase
auth user id). Only look this up when genuinely needed (abuse escalation,
a user support request referencing their own reports):

```sql
select id, email, created_at from auth.users where id = '<reporter-id>';
```

## 6. Remove an abusive account entirely

This is the same **aggregate-then-delete** flow the app uses for
self-service deletion ([roadmap §2b](roadmap-ios-launch.md)) — their
report *counts* survive anonymously, their identified rows and account do
not. Prefer this over raw `DELETE FROM auth.users`, which would skip the
aggregation step.

```sql
select public.aggregate_reports_before_delete('<reporter-id>');
```

Then delete the auth user via the Supabase dashboard (Authentication →
Users → find by id → Delete) or the Admin API — not directly via SQL, so
GoTrue's own cleanup runs. The `on delete cascade` FK then removes their
`reports`/`reporter_beach_standing` rows automatically.

## 7. Sanity check: nothing held is stuck for long

Run periodically (or before this becomes a scheduled job in Phase C+):

```sql
select count(*), min(created_at) as oldest
from public.reports
where status = 'held_for_review';
```

If `oldest` is more than a day or two old, something in §1–3 was missed —
work the queue down before it erodes trust in the categories it's holding.

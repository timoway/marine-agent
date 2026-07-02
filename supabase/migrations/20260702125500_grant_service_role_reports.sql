-- Fix: unchecking "Automatically expose new tables" at project creation withheld
-- base table privileges from service_role too, not just anon/authenticated.
-- BYPASSRLS (which service_role has) only skips row-level policy checks - it does
-- not substitute for the underlying GRANT, which Postgres checks first. Confirmed
-- via information_schema.role_table_grants: service_role had TRUNCATE/REFERENCES/
-- TRIGGER but not SELECT/INSERT/UPDATE/DELETE, causing "permission denied for
-- table reports" (42501) on every backend write/read.
--
-- anon/authenticated intentionally remain without these grants - all reads/writes
-- go through the backend's service_role client, never directly from the browser.

grant select, insert, update, delete on public.reports to service_role;
grant select, insert, update, delete on public.reporter_beach_standing to service_role;

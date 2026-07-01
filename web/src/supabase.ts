import { createClient } from '@supabase/supabase-js';

// Beach Pulse uses Supabase for Google sign-in only — all report reads/writes
// go through the marine-agent API (see docs/handoff-beach-pulse.md §0).
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabaseConfigured = Boolean(url && anonKey);

// When unconfigured (e.g. a preview without env), export null and let callers
// degrade gracefully rather than throwing at import time.
export const supabase = supabaseConfigured
  ? createClient(url as string, anonKey as string)
  : null;

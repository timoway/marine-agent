import { createClient } from '@supabase/supabase-js';

// Beach Pulse uses Supabase for Google sign-in only — all report reads/writes
// go through the marine-agent API (see docs/handoff-beach-pulse.md §0).
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabaseConfigured = Boolean(url && anonKey);

// When unconfigured (e.g. a preview without env), export null and let callers
// degrade gracefully rather than throwing at import time.
// Auth options are the supabase-js defaults, pinned explicitly so a future
// library default change can't silently alter session behavior.
export const supabase = supabaseConfigured
  ? createClient(url as string, anonKey as string, {
      auth: {
        flowType: 'pkce',
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

// Surface OAuth callback errors that would otherwise vanish silently — Supabase
// appends error params to the redirect URL when the exchange fails.
if (typeof window !== 'undefined') {
  const params = new URLSearchParams(window.location.search + '&' + window.location.hash.replace(/^#/, ''));
  const authError = params.get('error_description') || params.get('error');
  if (authError) {
    console.error('[AUTH] OAuth callback error:', authError);
  }
}

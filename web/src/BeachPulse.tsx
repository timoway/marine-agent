import { useCallback, useEffect, useState } from 'react';
import { Megaphone, X } from 'lucide-react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from './supabase';
import { apiFetch, apiPost, ApiError } from './api';
import type { BeachPulse, CommunityReport, ReportType } from './types';

// Category metadata — keys match the backend SEVERITY_TIER report_type keys.
export const REPORT_CATEGORIES: { type: ReportType; icon: string; label: string }[] = [
  { type: 'jellyfish', icon: '🪼', label: 'Jellyfish' },
  { type: 'riptide', icon: '🌀', label: 'Riptide' },
  { type: 'shark', icon: '🦈', label: 'Shark' },
  { type: 'red_tide', icon: '☠️', label: 'Red tide' },
  { type: 'surf', icon: '🌊', label: 'Rough surf' },
  { type: 'dead_fish', icon: '🐟', label: 'Dead fish' },
  { type: 'algae', icon: '🌿', label: 'Algae' },
  { type: 'clarity', icon: '👁️', label: 'Water clarity' },
  { type: 'debris', icon: '🗑️', label: 'Debris' },
  { type: 'crowd', icon: '👥', label: 'Crowd' },
  { type: 'parking', icon: '🅿️', label: 'Parking' },
  { type: 'dog', icon: '🐕', label: 'Dog-friendly' },
];

const CATEGORY_BY_TYPE = Object.fromEntries(
  REPORT_CATEGORIES.map(c => [c.type, c]),
) as Record<ReportType, { type: ReportType; icon: string; label: string }>;

const PENDING_KEY = 'beachpulse-pending';

// --- Auth session hook (Google sign-in via Supabase; null when unconfigured) ---
export function useSession(): Session | null {
  const [session, setSession] = useState<Session | null>(null);
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);
  return session;
}

function timeAgo(minAgo: number | null): string {
  if (minAgo == null) return '';
  if (minAgo < 1) return 'just now';
  if (minAgo < 60) return `${minAgo}m ago`;
  const h = Math.floor(minAgo / 60);
  return `${h}h ago`;
}

// --- Beach Pulse badge: adjacent to the verdict, never inside it ---
export function BeachPulseBadge({ pulse }: { pulse?: BeachPulse }) {
  if (!pulse || !pulse.reports_enabled || pulse.counts.length === 0) return null;
  return (
    <div className="pulse-badge" aria-label="Community reports today">
      <span className="pulse-badge-label">Beach Pulse</span>
      <div className="pulse-chips">
        {pulse.counts.map(c => {
          const cat = CATEGORY_BY_TYPE[c.type];
          return (
            <span
              key={c.type}
              className={`pulse-chip${c.escalated ? ' escalated' : ''}`}
              title={`${cat?.label ?? c.type} · ${timeAgo(c.last_report_min_ago)}`}
            >
              <span className="pulse-chip-icon">{cat?.icon ?? '•'}</span>
              {cat?.label ?? c.type} {c.count}
            </span>
          );
        })}
      </div>
      <span className="pulse-badge-note">Community reports — not official data</span>
    </div>
  );
}

// --- Report FAB + category sheet ---
export function ReportFab({
  beachId,
  session,
  onSubmitted,
}: {
  beachId: string;
  session: Session | null;
  onSubmitted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ReportType | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const doSubmit = useCallback(
    async (beach: string, type: ReportType, token: string) => {
      setBusy(type);
      setMessage(null);
      try {
        await apiPost('/reports', { beach_id: beach, report_type: type }, token);
        setMessage(`Thanks — ${CATEGORY_BY_TYPE[type]?.label ?? type} report submitted.`);
        onSubmitted();
        setTimeout(() => {
          setOpen(false);
          setMessage(null);
        }, 1400);
      } catch (err) {
        if (err instanceof ApiError && err.status === 429) {
          setMessage('You already reported this recently.');
        } else if (err instanceof ApiError && err.status === 401) {
          setMessage('Please sign in again.');
        } else {
          setMessage(err instanceof Error ? err.message : 'Could not submit report.');
        }
      } finally {
        setBusy(null);
      }
    },
    [onSubmitted],
  );

  // After an OAuth redirect back, submit the report the user tapped pre-sign-in.
  useEffect(() => {
    if (!session) return;
    const raw = localStorage.getItem(PENDING_KEY);
    if (!raw) return;
    localStorage.removeItem(PENDING_KEY);
    try {
      const pending = JSON.parse(raw) as { beachId: string; type: ReportType };
      if (pending.beachId && pending.type) {
        setOpen(true);
        void doSubmit(pending.beachId, pending.type, session.access_token);
      }
    } catch { /* ignore malformed pending */ }
  }, [session, doSubmit]);

  const onCategory = useCallback(
    (type: ReportType) => {
      if (session) {
        void doSubmit(beachId, type, session.access_token);
        return;
      }
      if (!supabase) {
        setMessage('Sign-in is unavailable right now.');
        return;
      }
      // Stash the intent, then sign in — the effect above resubmits on return.
      localStorage.setItem(PENDING_KEY, JSON.stringify({ beachId, type }));
      void supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin },
      });
    },
    [beachId, session, doSubmit],
  );

  return (
    <>
      <button
        className="pulse-fab"
        onClick={() => setOpen(true)}
        aria-label="Report beach conditions"
      >
        <Megaphone size={20} />
        <span className="pulse-fab-text">Report</span>
      </button>

      {open && (
        <div className="pulse-sheet-overlay" onClick={() => setOpen(false)}>
          <div
            className="pulse-sheet"
            onClick={e => e.stopPropagation()}
            role="dialog"
            aria-label="Report beach conditions"
          >
            <div className="pulse-sheet-header">
              <span>Report conditions</span>
              <button
                className="pulse-sheet-close"
                onClick={() => setOpen(false)}
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            {!session && (
              <p className="pulse-sheet-note">You'll sign in with Google first (one tap).</p>
            )}
            <div className="pulse-grid">
              {REPORT_CATEGORIES.map(cat => (
                <button
                  key={cat.type}
                  className="pulse-cat"
                  disabled={busy !== null}
                  onClick={() => onCategory(cat.type)}
                >
                  <span className="pulse-cat-icon">{cat.icon}</span>
                  <span className="pulse-cat-label">
                    {busy === cat.type ? 'Sending…' : cat.label}
                  </span>
                </button>
              ))}
            </div>
            {message && <p className="pulse-sheet-message">{message}</p>}
          </div>
        </div>
      )}
    </>
  );
}

// --- Community reports section: today's visible reports for a beach ---
export function CommunityReports({ beachId, refreshKey }: { beachId: string; refreshKey: number }) {
  const [reports, setReports] = useState<CommunityReport[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ reports: CommunityReport[] }>(`/reports/${beachId}`, { retries: 1 })
      .then(res => { if (!cancelled) setReports(res.reports); })
      .catch(() => { if (!cancelled) setReports([]); });
    return () => { cancelled = true; };
  }, [beachId, refreshKey]);

  if (!reports || reports.length === 0) return null;

  return (
    <div className="card community-reports-card">
      <div className="card-title"><Megaphone size={18} /> Community reports today</div>
      <ul className="community-list">
        {reports.map(r => {
          const cat = CATEGORY_BY_TYPE[r.report_type];
          return (
            <li key={r.id} className="community-item">
              <span className="community-item-icon">{cat?.icon ?? '•'}</span>
              <span className="community-item-label">{cat?.label ?? r.report_type}</span>
              {r.notes && <span className="community-item-notes">{r.notes}</span>}
              {r.status === 'escalated' && <span className="community-item-tag">confirmed</span>}
            </li>
          );
        })}
      </ul>
      <p className="community-disclaimer">Community-submitted — verify official flags before entering the water.</p>
    </div>
  );
}

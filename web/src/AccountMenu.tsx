import { useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { User, X, LogOut, Trash2 } from 'lucide-react';
import { supabase } from './supabase';
import { providerLabel, CATEGORY_BY_TYPE } from './BeachPulse';
import { apiGetAuthed, apiDelete, ApiError } from './api';
import type { Beach, MyReport } from './types';

const STATUS_LABEL: Record<MyReport['status'], string | null> = {
  published: null, // default state — no chip needed, matches Beach Pulse's plain-count philosophy
  escalated: 'confirmed',
  held_for_review: 'held for review',
};

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMin = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

export function AccountAvatarButton({
  session,
  onClick,
  className,
}: {
  session: Session | null;
  onClick: () => void;
  className?: string;
}) {
  if (!session) {
    return (
      <button
        className={className ?? 'account-avatar-btn'}
        onClick={() => void supabase?.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } })}
        aria-label="Sign in"
      >
        <User size={18} />
      </button>
    );
  }
  const initial = (session.user.email ?? '?').charAt(0).toUpperCase();
  return (
    <button className={className ?? 'account-avatar-btn'} onClick={onClick} aria-label="Account menu">
      <span className="account-avatar-circle">{initial}</span>
    </button>
  );
}

export function AccountSheet({
  session,
  beaches,
  favorites,
  onSelectBeach,
  onClose,
}: {
  session: Session;
  beaches: Beach[];
  favorites: string[];
  onSelectBeach: (beachId: string) => void;
  onClose: () => void;
}) {
  const [myReports, setMyReports] = useState<MyReport[] | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGetAuthed<{ reports: MyReport[] }>('/me/reports', session.access_token)
      .then(res => { if (!cancelled) setMyReports(res.reports); })
      .catch(() => { if (!cancelled) setMyReports([]); });
    return () => { cancelled = true; };
  }, [session.access_token]);

  const beachName = (id: string) => beaches.find(b => b.id === id)?.name ?? id;

  const signOut = () => {
    if (supabase) void supabase.auth.signOut();
    onClose();
  };

  const confirmDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      await apiDelete('/me', session.access_token);
      if (supabase) await supabase.auth.signOut();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete account. Try again.');
      setDeleting(false);
    }
  };

  return (
    <div className="pulse-sheet-overlay" onClick={onClose}>
      <div className="pulse-sheet account-sheet" onClick={e => e.stopPropagation()} role="dialog" aria-label="Account">
        <div className="pulse-sheet-header">
          <span>Account</span>
          <button className="pulse-sheet-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <p className="pulse-sheet-note">
          {session.user.email}
          {providerLabel(session) && ` · Signed in with ${providerLabel(session)}`}
        </p>

        {favorites.length > 0 && (
          <div className="account-section">
            <span className="account-section-title">Favorite beaches</span>
            <ul className="community-list">
              {favorites.map(id => (
                <li key={id}>
                  <button
                    className="account-favorite-item"
                    onClick={() => { onSelectBeach(id); onClose(); }}
                  >
                    ♥ {beachName(id)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="account-section">
          <span className="account-section-title">My reports</span>
          {myReports === null ? (
            <p className="account-empty">Loading…</p>
          ) : myReports.length === 0 ? (
            <p className="account-empty">You haven't submitted any reports yet.</p>
          ) : (
            <ul className="community-list account-reports-list">
              {myReports.map(r => {
                const cat = CATEGORY_BY_TYPE[r.report_type];
                const statusLabel = STATUS_LABEL[r.status];
                return (
                  <li key={r.id} className="community-item">
                    <span className="community-item-icon">{cat?.icon ?? '•'}</span>
                    <span className="community-item-label">{cat?.label ?? r.report_type}</span>
                    <span className="account-report-meta">
                      {beachName(r.beach_id)} · {relativeTime(r.created_at)}
                    </span>
                    {statusLabel && <span className="community-item-tag">{statusLabel}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="account-actions">
          <button className="account-action-btn" onClick={signOut}>
            <LogOut size={16} /> Sign out
          </button>
        </div>

        <div className="account-danger-zone">
          {!confirmingDelete ? (
            <button className="account-delete-btn" onClick={() => setConfirmingDelete(true)}>
              <Trash2 size={16} /> Delete account
            </button>
          ) : (
            <div className="account-delete-confirm">
              <p>
                This permanently deletes your account and your {myReports?.length ?? 0} report
                {myReports?.length === 1 ? '' : 's'}. This cannot be undone.
              </p>
              {error && <p className="account-delete-error">{error}</p>}
              <div className="account-delete-confirm-actions">
                <button className="pulse-note-cancel" onClick={() => setConfirmingDelete(false)} disabled={deleting}>
                  Cancel
                </button>
                <button className="account-delete-confirm-btn" onClick={() => void confirmDelete()} disabled={deleting}>
                  {deleting ? 'Deleting…' : 'Delete account'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function AccountMenu({
  session,
  beaches,
  favorites,
  onSelectBeach,
}: {
  session: Session | null;
  beaches: Beach[];
  favorites: string[];
  onSelectBeach: (beachId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <AccountAvatarButton session={session} onClick={() => setOpen(true)} />
      {open && session && (
        <AccountSheet
          session={session}
          beaches={beaches}
          favorites={favorites}
          onSelectBeach={onSelectBeach}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

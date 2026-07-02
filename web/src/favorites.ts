import { useCallback, useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { apiGetAuthed, apiPost, apiDelete } from './api';

// Profile-level favorite beaches, synced via the API (device-local home beach
// stays separate — it's the "default view" concept; favorites feed digests,
// push alerts, and the widget later).
export function useFavorites(session: Session | null) {
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    if (!session) {
      setFavorites([]);
      return;
    }
    let cancelled = false;
    apiGetAuthed<{ favorites: string[] }>('/me/favorites', session.access_token)
      .then(res => { if (!cancelled) setFavorites(res.favorites); })
      .catch(() => { /* favorites are non-critical; leave empty on failure */ });
    return () => { cancelled = true; };
  }, [session]);

  const toggleFavorite = useCallback(
    (beachId: string) => {
      if (!session) return;
      const isFav = favorites.includes(beachId);
      // optimistic; revert on failure
      setFavorites(f => (isFav ? f.filter(b => b !== beachId) : [...f, beachId]));
      const call = isFav
        ? apiDelete(`/me/favorites/${beachId}`, session.access_token)
        : apiPost<void>('/me/favorites', { beach_id: beachId }, session.access_token);
      call.catch(() => {
        setFavorites(f => (isFav ? [...f, beachId] : f.filter(b => b !== beachId)));
      });
    },
    [session, favorites],
  );

  return { favorites, toggleFavorite };
}

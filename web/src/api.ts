export const API_BASE = import.meta.env.VITE_API_BASE || (
  import.meta.env.PROD ? '/api' : `http://${window.location.hostname}:8000/api`
);

export async function apiFetch<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new Error('Cannot reach the Marine Agent API. Check your connection.');
  }

  const text = await res.text();
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(
        'API backend is not running yet. Deploy marine-agent-api on Render, then redeploy Vercel.'
      );
    }
    throw new Error(`API error (${res.status}): ${text.slice(0, 120) || res.statusText}`);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error('API returned invalid data. The backend may still be starting up — try again in 30s.');
  }
}
export const API_BASE = import.meta.env.VITE_API_BASE || (
  import.meta.env.PROD ? '/api' : `http://${window.location.hostname}:8000/api`
);

const RETRYABLE_STATUS = new Set([502, 503, 504, 429]);
const RETRY_DELAYS_MS = [2000, 5000, 10000];

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export interface ApiHealth {
  status: 'ok' | 'warming';
  ready: boolean;
  beaches_cached: number;
  beaches_total: number;
}

export async function waitForApiReady(maxWaitMs = 90000): Promise<ApiHealth> {
  const started = Date.now();
  let lastError = 'API is starting up';

  while (Date.now() - started < maxWaitMs) {
    try {
      const health = await apiFetch<ApiHealth>('/health', { retries: 1 });
      if (health.ready) {
        return health;
      }
      lastError = `Coastal sensors loading (${health.beaches_cached}/${health.beaches_total} beaches)`;
    } catch (err) {
      lastError = err instanceof Error ? err.message : 'API is starting up';
    }
    await sleep(3000);
  }

  throw new Error(lastError);
}

export async function apiFetch<T>(
  path: string,
  options?: { retries?: number },
): Promise<T> {
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  const maxAttempts = options?.retries ?? 3;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let res: Response;
    try {
      res = await fetch(url);
    } catch {
      if (attempt < maxAttempts - 1) {
        await sleep(RETRY_DELAYS_MS[attempt] ?? 10000);
        continue;
      }
      throw new Error('Cannot reach the Marine Agent API. The server may be waking up — try again shortly.');
    }

    const text = await res.text();
    if (!res.ok) {
      if (RETRYABLE_STATUS.has(res.status) && attempt < maxAttempts - 1) {
        await sleep(RETRY_DELAYS_MS[attempt] ?? 10000);
        continue;
      }
      if (res.status === 404) {
        throw new Error(
          'API backend is not running yet. Deploy marine-agent-api on Render, then redeploy Vercel.',
        );
      }
      throw new Error(`API error (${res.status}): ${text.slice(0, 120) || res.statusText}`);
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      if (attempt < maxAttempts - 1) {
        await sleep(RETRY_DELAYS_MS[attempt] ?? 10000);
        continue;
      }
      throw new Error('API returned invalid data. The backend may still be starting up — try again in 30s.');
    }
  }

  throw new Error('Cannot reach the Marine Agent API. The server may be waking up — try again shortly.');
}
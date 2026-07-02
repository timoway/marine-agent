"""Beach Pulse — community reports, backed by Supabase.

All report logic lives here (rate limiting, spike detection, severity tiers,
JWT verification, aggregation) so marine_server.py just wires HTTP routes to it.
See docs/handoff-beach-pulse.md §0/§3 for the architecture.

Degrades safely: if SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY are unset or Supabase
is unreachable, reads return empty and build_beach_pulse() returns a disabled
pulse rather than raising — the core /api/conditions response is never broken.
"""

from __future__ import annotations

import os
import datetime
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

FL_TZ = ZoneInfo("America/New_York")
UTC = datetime.timezone.utc

# --- Tunable constants (starting values; see docs/handoff-beach-pulse.md §3b) ---
RATE_LIMIT_PER_HOUR = 1          # per (reporter_id, beach_id, report_type)
SPIKE_COUNT = 5                  # high-tier reports of one type at one beach...
SPIKE_WINDOW_MIN = 15            # ...within this window, all from low-trust accounts → held
LOCAL_GUIDE_THRESHOLD = 3        # corroborated reports at a beach → Local Guide (Phase C)

SEVERITY_TIER = {
    "clarity": "low", "crowd": "low", "wildlife": "low",
    "parking": "low", "debris": "low", "algae": "low",
    "dead_fish": "moderate", "surf": "moderate", "jellyfish": "moderate",
    "riptide": "high", "shark": "high", "red_tide": "high",
}
CORROBORATION_WINDOWS_MIN = {    # type-specific freshness for corroboration/escalation
    "riptide": 120, "shark": 120,                       # time-sensitive
    "jellyfish": 240, "surf": 240, "dead_fish": 240, "red_tide": 240, "wildlife": 240,
    "clarity": 360, "crowd": 360,
    "parking": 360, "debris": 360, "algae": 360,
}
VALID_REPORT_TYPES = frozenset(SEVERITY_TIER.keys())

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


class ReportError(Exception):
    """A report operation failed. `.status` maps to the HTTP code to return."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ReportAuthError(ReportError):
    def __init__(self, message: str = "invalid token"):
        super().__init__(message, status=401)


class RateLimitError(ReportError):
    def __init__(self, message: str = "already reported this recently"):
        super().__init__(message, status=429)


# --- Supabase client (lazy, degrades to None when unconfigured) ---
_client = None
_client_init = False


def _get_client():
    global _client, _client_init
    if _client_init:
        return _client
    _client_init = True
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[REPORTS] SUPABASE_URL/SERVICE_ROLE_KEY unset — reports disabled")
        return None
    try:
        from supabase import create_client

        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        print("[REPORTS] Supabase client ready")
    except Exception as exc:
        print(f"[REPORTS] Supabase init failed (reports disabled): {str(exc)[:120]}")
        _client = None
    return _client


def is_enabled() -> bool:
    return _get_client() is not None


# --- Time helpers ---
def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _fl_day_start() -> datetime.datetime:
    """Midnight today in Florida time (tz-aware) — the boundary for 'today's reports'."""
    now_fl = datetime.datetime.now(FL_TZ)
    return now_fl.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_ts(s: str) -> Optional[datetime.datetime]:
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


# --- JWT verification (JWKS / ES256; no shared secret — see handoff §3c) ---
_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        import jwt

        _jwks_client = jwt.PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client


def verify_jwt(token: str) -> str:
    """Verify a Supabase-issued JWT and return the user uuid (`sub`).

    Raises ReportAuthError on any failure. Uses the public JWKS endpoint keyed
    by the token's `kid`, so key rotation needs no code change.
    """
    if not SUPABASE_URL:
        raise ReportAuthError("auth not configured")
    try:
        import jwt

        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["ES256"], audience="authenticated"
        )
    except ReportAuthError:
        raise
    except Exception as exc:
        raise ReportAuthError(f"invalid token: {str(exc)[:80]}")
    sub = claims.get("sub")
    if not sub:
        raise ReportAuthError("token missing sub")
    return sub


# --- Write path ---
def submit_report(
    reporter_id: str,
    beach_id: str,
    report_type: str,
    notes: Optional[str] = None,
    beach_lat: Optional[float] = None,
    beach_lng: Optional[float] = None,
) -> dict:
    """Insert a report. Server sets severity_tier + status. Enforces rate limit
    and (for high-tier) spike hold. Returns the created row."""
    client = _get_client()
    if client is None:
        raise ReportError("reports not available", status=503)

    report_type = (report_type or "").strip()
    if report_type not in VALID_REPORT_TYPES:
        raise ReportError(f"unknown report_type: {report_type or '(empty)'}")
    tier = SEVERITY_TIER[report_type]
    clean_notes = notes.strip()[:140] if notes else None

    try:
        since = _iso(_utcnow() - datetime.timedelta(hours=1))
        existing = (
            client.table("reports")
            .select("id")
            .eq("reporter_id", reporter_id)
            .eq("beach_id", beach_id)
            .eq("report_type", report_type)
            .gte("created_at", since)
            .limit(RATE_LIMIT_PER_HOUR)
            .execute()
        )
        if existing.data and len(existing.data) >= RATE_LIMIT_PER_HOUR:
            raise RateLimitError()

        row: Dict = {
            "beach_id": beach_id,
            "report_type": report_type,
            "severity_tier": tier,
            "reporter_id": reporter_id,
            "status": "published",
        }
        if clean_notes:
            row["notes"] = clean_notes
        if beach_lat is not None:
            row["beach_lat"] = beach_lat
        if beach_lng is not None:
            row["beach_lng"] = beach_lng

        inserted = client.table("reports").insert(row).execute()
        created = inserted.data[0] if inserted.data else row

        if tier == "high":
            _maybe_hold_spike(client, beach_id, report_type)
        return created
    except ReportError:
        raise
    except Exception as exc:
        raise ReportError(f"submission failed: {str(exc)[:80]}", status=502)


def _maybe_hold_spike(client, beach_id: str, report_type: str) -> None:
    """If a burst of high-tier reports of one type at one beach comes entirely
    from low-trust accounts, hold them for review (abuse signature). Established
    reporters (any prior corroboration / Local Guide) exempt the whole burst."""
    since = _iso(_utcnow() - datetime.timedelta(minutes=SPIKE_WINDOW_MIN))
    recent = (
        client.table("reports")
        .select("id,reporter_id")
        .eq("beach_id", beach_id)
        .eq("report_type", report_type)
        .eq("status", "published")
        .gte("created_at", since)
        .execute()
    )
    rows = recent.data or []
    if len(rows) < SPIKE_COUNT:
        return
    reporter_ids = list({r["reporter_id"] for r in rows})
    standing = (
        client.table("reporter_beach_standing")
        .select("reporter_id,corroborated_count,is_local_guide")
        .in_("reporter_id", reporter_ids)
        .execute()
    )
    trusted = any(
        (s.get("corroborated_count", 0) or 0) > 0 or s.get("is_local_guide")
        for s in (standing.data or [])
    )
    if trusted:
        return
    ids = [r["id"] for r in rows]
    client.table("reports").update({"status": "held_for_review"}).in_("id", ids).execute()


# --- Read path ---
def get_reports_for_beach(beach_id: str) -> List[dict]:
    """Today's visible (published/escalated) reports for a beach, newest first."""
    client = _get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("reports")
            .select("id,report_type,severity_tier,notes,status,created_at")
            .eq("beach_id", beach_id)
            .in_("status", ["published", "escalated"])
            .gte("created_at", _iso(_fl_day_start()))
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        print(f"[REPORTS] get_reports_for_beach failed for {beach_id}: {str(exc)[:100]}")
        return []


def get_reports_for_user(reporter_id: str) -> List[dict]:
    """All of the caller's own reports (any status, incl. held) — 'My reports'."""
    client = _get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("reports")
            .select("id,beach_id,report_type,severity_tier,notes,status,created_at")
            .eq("reporter_id", reporter_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        print(f"[REPORTS] get_reports_for_user failed: {str(exc)[:100]}")
        return []


# --- Favorite beaches (profile-level, synced across devices) ---
def get_favorites(user_id: str) -> List[str]:
    """The caller's favorite beach ids, oldest first."""
    client = _get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("user_favorites")
            .select("beach_id")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return [r["beach_id"] for r in (res.data or [])]
    except Exception as exc:
        print(f"[REPORTS] get_favorites failed: {str(exc)[:100]}")
        return []


def add_favorite(user_id: str, beach_id: str) -> None:
    client = _get_client()
    if client is None:
        raise ReportError("favorites not available", status=503)
    try:
        client.table("user_favorites").upsert(
            {"user_id": user_id, "beach_id": beach_id},
            on_conflict="user_id,beach_id",
        ).execute()
    except Exception as exc:
        raise ReportError(f"could not save favorite: {str(exc)[:80]}", status=502)


def remove_favorite(user_id: str, beach_id: str) -> None:
    client = _get_client()
    if client is None:
        raise ReportError("favorites not available", status=503)
    try:
        client.table("user_favorites").delete().eq("user_id", user_id).eq("beach_id", beach_id).execute()
    except Exception as exc:
        raise ReportError(f"could not remove favorite: {str(exc)[:80]}", status=502)


# --- Account deletion (docs/roadmap-ios-launch.md §2b: aggregate-then-delete) ---
def delete_account(reporter_id: str) -> None:
    """Fold the user's reports into identity-free daily counts, then delete their
    auth user — the FK cascade removes their identified rows. Aggregation runs
    first and is atomic (a single SQL statement via RPC); deletion is a separate
    step so a failure here never loses the aggregate that already landed."""
    client = _get_client()
    if client is None:
        raise ReportError("account deletion not available", status=503)
    try:
        client.rpc("aggregate_reports_before_delete", {"p_reporter_id": reporter_id}).execute()
    except Exception as exc:
        raise ReportError(f"could not aggregate reports before deletion: {str(exc)[:100]}", status=502)
    try:
        client.auth.admin.delete_user(reporter_id)
    except Exception as exc:
        raise ReportError(f"account deletion failed: {str(exc)[:100]}", status=502)


def build_beach_pulse(beach_id: str, reports_enabled: bool = True) -> dict:
    """Aggregate today's reports into the `beach_pulse` object for /api/conditions.

    Never raises — returns a disabled/empty pulse on any error so the core
    conditions response is unaffected. Frontend renders no chip when counts is empty.
    """
    default = {"reports_enabled": bool(reports_enabled), "total_today": 0, "counts": []}
    if not reports_enabled:
        return default
    client = _get_client()
    if client is None:
        return default
    try:
        res = (
            client.table("reports")
            .select("report_type,reporter_id,created_at")
            .eq("beach_id", beach_id)
            .in_("status", ["published", "escalated"])
            .gte("created_at", _iso(_fl_day_start()))
            .execute()
        )
        rows = res.data or []
        now = _utcnow()
        by_type: Dict[str, List[dict]] = {}
        for r in rows:
            by_type.setdefault(r["report_type"], []).append(r)

        counts = []
        for rtype, items in by_type.items():
            window = CORROBORATION_WINDOWS_MIN.get(rtype, 240)
            cutoff = now - datetime.timedelta(minutes=window)
            recent_reporters = set()
            newest = None
            for it in items:
                ts = _parse_ts(it.get("created_at", ""))
                if ts is None:
                    continue
                if newest is None or ts > newest:
                    newest = ts
                if ts >= cutoff:
                    recent_reporters.add(it["reporter_id"])
            last_min_ago = int((now - newest).total_seconds() // 60) if newest else None
            counts.append(
                {
                    "type": rtype,
                    "count": len(items),
                    "escalated": len(recent_reporters) >= 2,
                    "last_report_min_ago": last_min_ago,
                }
            )
        counts.sort(key=lambda c: c["count"], reverse=True)
        return {"reports_enabled": True, "total_today": len(rows), "counts": counts}
    except Exception as exc:
        print(f"[REPORTS] build_beach_pulse failed for {beach_id}: {str(exc)[:100]}")
        return default

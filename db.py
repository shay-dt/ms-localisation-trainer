# db.py
# ===========================================================================
# All Supabase database operations for the MS Lesion Trainer.
# Uses the service-role key so Row Level Security doesn't block server calls.
# ===========================================================================

import os
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

import streamlit as st

_client = None   # module-level singleton so we only create the client once


def _get():
    """Return (and lazily create) the Supabase client."""
    global _client
    if _client is None:
        from supabase import create_client
        url = _secret("SUPABASE_URL")
        key = _secret("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in Streamlit secrets.")
        _client = create_client(url, key)
    return _client


def _secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, os.environ.get(key, default)))
    except Exception:
        return os.environ.get(key, default)


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user(email: str) -> Optional[dict]:
    """Return the user row for this email, or None if they don't exist."""
    r = _get().table("users").select("*").eq("email", email.lower()).execute()
    return r.data[0] if r.data else None


def add_user(email: str, role: str = "student", invited_by: Optional[str] = None):
    """Add a new user. Role is 'student' or 'admin'."""
    _get().table("users").insert({
        "email": email.lower(),
        "role": role,
        "invited_by": invited_by,
    }).execute()


def touch_login(email: str):
    """Record that this user just logged in."""
    _get().table("users").update({
        "last_login_at": datetime.now(timezone.utc).isoformat()
    }).eq("email", email.lower()).execute()


def remove_user(email: str):
    """Remove a student from the system."""
    _get().table("users").delete().eq("email", email.lower()).execute()


def all_users() -> list[dict]:
    """Return all users, ordered by when they were added."""
    return _get().table("users").select("*").order("created_at").execute().data


# ── OTP codes ─────────────────────────────────────────────────────────────────

def issue_otp(email: str) -> str:
    """
    Generate a fresh 6-digit code, invalidate any previous ones for this
    email, store it with a 15-minute expiry, and return the code string.
    """
    email = email.lower()
    # Invalidate old unused codes for this email
    _get().table("otp_codes") \
          .update({"used": True}) \
          .eq("email", email) \
          .eq("used", False) \
          .execute()
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    _get().table("otp_codes").insert({
        "email": email,
        "code": code,
        "expires_at": expires,
    }).execute()
    return code


def verify_otp(email: str, code: str) -> bool:
    """
    Return True if the code is valid (matches, unused, not expired).
    Marks the code as used if it passes so it can't be replayed.
    """
    email = email.lower()
    r = _get().table("otp_codes") \
              .select("*") \
              .eq("email", email) \
              .eq("code", code.strip()) \
              .eq("used", False) \
              .execute()
    if not r.data:
        return False
    row = r.data[0]
    expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires:
        return False
    _get().table("otp_codes").update({"used": True}).eq("id", row["id"]).execute()
    return True


# ── Completions ───────────────────────────────────────────────────────────────

def log_completion(email: str, case_number: str, self_rating: str,
                   cp_pattern: Optional[str] = None,
                   cp_regions: Optional[list] = None,
                   cp_sides:   Optional[list] = None,
                   free_text:  Optional[str] = None):
    """
    Record (or update) a case completion with the student's actual answers.
    self_rating is 'nailed_it' or 'needs_review'.
    Uses upsert so submitting the same case twice just updates the record.
    """
    import json as _json
    _get().table("completions").upsert({
        "user_email":  email.lower(),
        "case_number": case_number,
        "self_rating": self_rating,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cp_pattern":  cp_pattern or "",
        "cp_regions":  _json.dumps(cp_regions or []),
        "cp_sides":    _json.dumps(cp_sides or []),
        "free_text":   (free_text or "").strip(),
    }, on_conflict="user_email,case_number").execute()


def completions_for(email: str) -> list[dict]:
    """All completion rows for a given student."""
    return _get().table("completions") \
                 .select("*") \
                 .eq("user_email", email.lower()) \
                 .execute().data


def student_detail(email: str) -> list[dict]:
    """
    All completions for a student, with answer fields parsed back to Python types.
    Returns rows sorted by case_number.
    """
    import json as _json
    rows = completions_for(email)
    for r in rows:
        for col in ("cp_regions", "cp_sides"):
            raw = r.get(col) or "[]"
            try:
                r[col] = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                r[col] = []
    return sorted(rows, key=lambda r: r.get("case_number", ""))


# ── Admin summary ─────────────────────────────────────────────────────────────

def submit_feedback(message: str, email: Optional[str] = None):
    """Store a free-text feedback submission."""
    _get().table("feedback").insert({
        "email":   (email or "").strip().lower() or None,
        "message": message.strip(),
    }).execute()


def get_feedback() -> list[dict]:
    """All feedback entries, newest first."""
    return _get().table("feedback") \
                 .select("*") \
                 .order("created_at", desc=True) \
                 .execute().data


def admin_summary() -> list[dict]:
    """
    Return all users enriched with:
      cases_completed  — number of cases they've self-rated (any rating)
      cases_nailed     — number rated 'nailed_it'
    """
    from collections import Counter
    users = all_users()
    rows = _get().table("completions").select("user_email, self_rating").execute().data
    completed = Counter(r["user_email"] for r in rows)
    nailed    = Counter(r["user_email"] for r in rows if r.get("self_rating") == "nailed_it")
    for u in users:
        e = u["email"]
        u["cases_completed"] = completed.get(e, 0)
        u["cases_nailed"]    = nailed.get(e, 0)
    return users

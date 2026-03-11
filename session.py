# session.py — DILIGENCE Competency
#
# 4D Framework: DILIGENCE
# "Handle data with care. Collect only what you need. Don't persist what you shouldn't."
#
# This module implements session-only data storage.
#
# Design choice — why NO database:
#   In v1, all roasts were written to SQLite permanently. This creates a data
#   accumulation problem: PII (names extracted from resumes) persists forever,
#   the database grows unbounded, and there's no GDPR-style retention policy.
#
#   In v2, results live only in Python memory (_session_store dict).
#   On server restart, all data is cleared. This is intentional — it enforces
#   data minimization by default. The leaderboard shows only results from the
#   current server session.
#
# Tradeoff acknowledged in LIMITATIONS.md:
#   - No cross-restart persistence
#   - Leaderboard resets on deploy
#   - This is a deliberate responsible AI choice, not a bug
#
# Session IDs are randomly generated per upload — they are NOT tied to users
# or browser sessions, so the system collects no identity information.

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RoastResult:
    """
    A single roast result — held in memory only, never written to disk.
    Contains the AI output AFTER validation by validator.py.
    """
    session_id: str
    name: str              # Extracted from resume (best-effort, may be "Anonymous")
    score: int
    one_line: str
    overview: str
    fun_obs: str
    confidence: float      # AI's self-reported confidence (0.0–1.0)
    warnings: List[str]    # Validator warnings — empty if output was clean
    mode: str              # 'quick' or 'full'
    created_at: str = field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def confidence_pct(self) -> str:
        return f"{self.confidence:.0%}"


# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY STORE
# This dict is the entire "database". It is intentionally ephemeral.
# ─────────────────────────────────────────────────────────────────────────────
_session_store: Dict[str, RoastResult] = {}


def new_session_id() -> str:
    """Generate a short random session ID. Not tied to any user identity."""
    return str(uuid.uuid4())[:12]


def save_result(result: RoastResult) -> None:
    """Store a roast result in memory."""
    _session_store[result.session_id] = result


def get_result(session_id: str) -> Optional[RoastResult]:
    """Retrieve a result by session ID, or None if not found."""
    return _session_store.get(session_id)


def get_all_results(limit: int = 40) -> List[RoastResult]:
    """Return all session results sorted by score descending, up to limit."""
    sorted_results = sorted(
        _session_store.values(),
        key=lambda r: (r.score, r.created_at),
        reverse=True,
    )
    return sorted_results[:limit]


def result_count() -> int:
    """Return total number of results in the current session."""
    return len(_session_store)

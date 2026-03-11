# logger.py — DILIGENCE Competency
#
# 4D Framework: DILIGENCE
# "Log every AI interaction so you can audit, debug, and be accountable."
#
# This module provides structured audit logging for all AI API calls.
# Logs are written as newline-delimited JSON (JSONL) for easy parsing.
#
# What is logged:
#   - Timestamp, session ID, event type, model used
#   - Input summary (brief description — NOT the full resume text, to avoid
#     accidentally persisting personal data in logs)
#   - Output metadata: score, confidence, warning count
#   - Token usage for cost tracking
#   - Errors if the API call fails
#   - Validation warnings surfaced by validator.py
#
# What is NOT logged:
#   - Full resume text (contains PII — stays in memory only)
#   - Full AI response text (verbatim content stored would be redundant)
#
# Log location: logs/ai_audit.jsonl
# Log format: one JSON object per line, UTC timestamps

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "ai_audit.jsonl"


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(exist_ok=True)


def log_ai_call(
    *,
    session_id: str,
    event: str,                              # e.g. "roast_request", "roast_response", "roast_error"
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    input_summary: Optional[str] = None,     # Brief description — no raw PII
    output_data: Optional[Dict[str, Any]] = None,
    warnings: Optional[List[str]] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Write one structured log entry for an AI API event.

    DILIGENCE: Every AI call — request, response, error — is logged here.
    This creates an auditable trail. The log file can be used to:
      - Debug unexpected outputs
      - Track token usage and costs
      - Identify patterns in validation failures
      - Demonstrate responsible AI deployment to auditors

    Returns:
        entry_id: A short unique ID for this log entry (for cross-referencing).
    """
    _ensure_log_dir()

    entry_id = str(uuid.uuid4())[:8]
    entry = {
        "id": entry_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "event": event,
        "model": model,
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": (
                (prompt_tokens or 0) + (completion_tokens or 0)
                if prompt_tokens is not None or completion_tokens is not None
                else None
            ),
        },
        "input_summary": input_summary,
        "output": output_data,
        "warnings": warnings or [],
        "warning_count": len(warnings or []),
        "error": error,
        "metadata": metadata or {},
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry_id


def log_validation_event(
    *,
    session_id: str,
    warnings: List[str],
    score: int,
    confidence: float,
) -> None:
    """
    Log the outcome of the validator's checks on an AI response.

    DILIGENCE: Tracks how often the validator flags issues.
    This is valuable for improving prompts and identifying model failure modes.
    """
    event = "validation_warning" if warnings else "validation_pass"
    log_ai_call(
        session_id=session_id,
        event=event,
        model="validator",
        output_data={"score": score, "confidence": confidence},
        warnings=warnings,
    )

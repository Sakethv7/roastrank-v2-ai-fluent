# validator.py — DISCERNMENT Competency
#
# 4D Framework: DISCERNMENT
# "Don't blindly trust AI output. Check it before showing it to users."
#
# This module intercepts every AI response before it reaches the UI and runs
# a series of checks. If anything looks wrong, it surfaces a human-readable
# warning so the user can judge for themselves — not silently pass bad output.
#
# Checks performed (in order):
#   1. Required fields present (structural completeness)
#   2. Score within human-defined rubric range (DELEGATION cross-check)
#   3. Confidence below threshold (AI self-reported low quality)
#   4. Generic language detection (pattern matching for known bad phrases)
#   5. Content length checks (suspiciously short = likely failed generation)
#   6. Resume-response overlap check (did the AI actually read the resume?)
#
# Design principle: warnings are additive and non-blocking. The user sees the
# output AND the warnings, so they can decide how much weight to give the result.

import re
from typing import Any, Dict, List, Tuple

from rubric import SCORE_MIN, SCORE_MAX, SCORING_DIMENSIONS

# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLDS — human-controlled (edit here, not in prompt)
# ─────────────────────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.6      # Below this, warn the user
MIN_OVERVIEW_CHARS = 60         # Shorter overviews are suspiciously thin
MIN_ONE_LINE_CHARS = 20         # One-liners shorter than this are likely errors
MIN_RESUME_OVERLAP_WORDS = 3    # Minimum shared meaningful words before flagging

REQUIRED_FIELDS = {"one_line", "overview", "fun_obs", "score", "confidence"}

# ─────────────────────────────────────────────────────────────────────────────
# GENERIC PHRASE DETECTOR
# Phrases that indicate the AI wrote a canned response rather than reading
# the resume. Expand this list as new patterns are discovered in production.
# ─────────────────────────────────────────────────────────────────────────────
GENERIC_PHRASES = [
    "lacks clarity",
    "needs improvement",
    "more specific",
    "hard to follow",
    "buzzword",
    "stands out from the crowd",
    "in today's competitive",
    "consider revising",
    "you should include",
    "it's important to",
    "hiring managers",
    "tailor your resume",
    "quantify your achievements",  # meta-advice without specific reference
]

# Common English words to exclude from resume-overlap analysis
_STOP_WORDS = {
    "with", "that", "this", "from", "have", "your", "they", "their",
    "will", "been", "were", "said", "each", "which", "time", "about",
    "more", "when", "also", "into", "than", "then", "some", "these",
    "both", "very", "just", "like", "over", "only", "even", "most",
    "after", "back", "other", "well", "work", "role", "resume", "company",
}


def validate_response(
    data: Dict[str, Any],
    resume_text: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Validate an AI-generated roast response before displaying it to the user.

    DISCERNMENT: This is the gatekeeper. Every AI response passes through here.
    Warnings are human-readable strings surfaced in the UI so users can make
    informed judgments about the quality of the AI's output.

    Args:
        data: Parsed JSON dict from the AI response.
        resume_text: Original resume text (used for overlap analysis).

    Returns:
        (cleaned_data, warnings): cleaned_data has defaults filled in for missing
        fields; warnings is a list of strings to show the user (may be empty).
    """
    warnings: List[str] = []

    # ── Check 1: Required fields ───────────────────────────────────────────
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        warnings.append(
            f"AI response was incomplete — missing fields: {', '.join(sorted(missing))}. "
            "Output may be unreliable."
        )
        for field in missing:
            data[field] = _field_default(field)

    # ── Check 2: Score range (DELEGATION cross-check) ─────────────────────
    score = data.get("score")
    if not isinstance(score, (int, float)):
        warnings.append(
            f"AI returned a non-numeric score ('{score}'). Defaulting to 1. "
            "The analysis may have failed."
        )
        data["score"] = 1
    else:
        score = int(score)
        if not (SCORE_MIN <= score <= SCORE_MAX):
            warnings.append(
                f"AI score {score} is outside the valid rubric range "
                f"({SCORE_MIN}–{SCORE_MAX}). Score has been clamped."
            )
            data["score"] = max(SCORE_MIN, min(SCORE_MAX, score))

    # ── Check 3: Confidence threshold ─────────────────────────────────────
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        warnings.append(
            "AI did not return a self-reported confidence score. "
            "Treating as low confidence — feedback may be generic."
        )
        data["confidence"] = 0.0
        confidence = 0.0
    else:
        confidence = float(confidence)
        if confidence < CONFIDENCE_THRESHOLD:
            warnings.append(
                f"Low AI confidence ({confidence:.0%}): The AI self-reported that "
                "its feedback may not be specific to your resume. "
                "Review carefully before acting on this result."
            )

    # ── Check 4: Generic language detection ───────────────────────────────
    combined_text = " ".join([
        str(data.get("one_line", "")),
        str(data.get("overview", "")),
        str(data.get("fun_obs", "")),
    ]).lower()

    found_generic = [p for p in GENERIC_PHRASES if p in combined_text]
    if found_generic:
        warnings.append(
            f"Feedback contains generic language (e.g., '{found_generic[0]}'). "
            "This may indicate the AI did not read your resume carefully."
        )

    # ── Check 5: Content length checks ────────────────────────────────────
    one_line = str(data.get("one_line", ""))
    overview = str(data.get("overview", ""))

    if len(one_line) < MIN_ONE_LINE_CHARS:
        warnings.append(
            "The one-line roast is unusually short — the AI may not have "
            "generated a complete response."
        )
    if len(overview) < MIN_OVERVIEW_CHARS:
        warnings.append(
            "The overview is very brief. The AI's rubric analysis may be incomplete."
        )

    # ── Check 6: Resume-response overlap (off-topic detection) ────────────
    resume_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", resume_text.lower()))
    response_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", combined_text))

    meaningful_resume = resume_words - _STOP_WORDS
    meaningful_response = response_words - _STOP_WORDS
    overlap = meaningful_resume & meaningful_response

    if len(overlap) < MIN_RESUME_OVERLAP_WORDS:
        warnings.append(
            "Warning: The AI's feedback shares very few specific words with your "
            "resume. It may not have analyzed your content — treat results with caution."
        )

    return data, warnings


def _field_default(field: str) -> Any:
    """Return a safe default for a missing required field."""
    defaults: Dict[str, Any] = {
        "one_line": "[AI response incomplete — field missing]",
        "overview": "[AI response incomplete — field missing]",
        "fun_obs": "",
        "score": 1,
        "confidence": 0.0,
    }
    return defaults.get(field, "")

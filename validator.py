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
from typing import Any, Dict, List, Optional, Tuple

from rubric import SCORE_MIN, SCORE_MAX, SCORING_DIMENSIONS

# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLDS — human-controlled (edit here, not in prompt)
# ─────────────────────────────────────────────────────────────────────────────

# Asymmetric confidence quantization bands
# Inspired by ngrok's asymmetric quantization insight: the data distribution
# is not symmetric around zero, so the "zero point" should not be the midpoint.
#
# Claude confidence values cluster around 0.70–0.88 for typical responses.
# The useful decision boundary is therefore NOT at 0.5 (symmetric midpoint)
# but closer to 0.50–0.55 (the lower tail of the real distribution).
#
# ngrok's asymmetric formula:
#   scale  = (vmax - vmin) / (qmax - qmin)
#   zero   = qmin - round(vmin / scale)
# Applied here as three-band asymmetric scale:
#   CRITICAL  (< 0.35)  — q_min: output is likely garbage
#   LOW       (< 0.52)  — zero_point: below center of real distribution, warn
#   OK        (≥ 0.52)  — q_max zone: no confidence-specific warning needed
CONFIDENCE_CRITICAL = 0.35     # Below this → critical warning
CONFIDENCE_WARN = 0.52         # Below this → standard warning (asymmetric zero point)

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

    # ── Check 3: Asymmetric confidence quantization ───────────────────────
    # Inspired by ngrok's asymmetric quantization: separate low/zero/high bands
    # rather than a single symmetric threshold. Claude confidence values skew
    # toward 0.70–0.88, so the useful warning boundary is asymmetric.
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
        if confidence < CONFIDENCE_CRITICAL:
            warnings.append(
                f"Critical: very low AI confidence ({confidence:.0%}) — "
                "feedback is almost certainly generic or the file extraction failed. "
                "Try re-uploading a cleaner PDF or plain-text file."
            )
        elif confidence < CONFIDENCE_WARN:
            warnings.append(
                f"Low AI confidence ({confidence:.0%}): feedback may not be "
                "specific to your resume content. Review carefully before acting on this result."
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

    # ── Check 7: Score-flag alignment (KL divergence analogue) ────────────
    # Inspired by ngrok's KL divergence measurement between original and
    # quantized probability distributions.
    # Here: measure "distortion" between the evidence detected in the resume
    # (the "original distribution") and the AI's score (the "quantized output").
    # High distortion = the score does not match the visible evidence.
    alignment_warning = _check_score_flag_alignment(data, resume_text)
    if alignment_warning:
        warnings.append(alignment_warning)

    return data, warnings


def _check_score_flag_alignment(data: Dict[str, Any], resume_text: str) -> Optional[str]:
    """
    KL divergence analogue: compare the count of detected red-flag patterns
    in the resume against the AI's claimed score.

    ngrok's KL divergence measures the overlap between the original probability
    distribution P and the quantized approximation Q. High KL(P||Q) = the
    quantized model behaves very differently from the original.

    Here: P is the "expected score distribution" implied by detected evidence
    (many red flags → expected low score). Q is the AI's actual score.
    A large gap between them signals potential hallucination or bias.
    """
    score = data.get("score", 50)
    if not isinstance(score, (int, float)):
        return None

    text_lower = resume_text.lower()

    # Count red-flag signals (rough approximation of "negative evidence density")
    red_count = 0
    red_count += min(3, len(re.findall(
        r"\b(helped|assisted|worked on|supported|participated|contributed to)\b",
        text_lower,
    )))
    red_count += min(2, len(re.findall(
        r"\b(microsoft\s+office|ms\s+office|teamwork|communication|passionate|results.driven)\b",
        text_lower,
    )))
    if not re.search(r"\b\d+\s*[%x×]\b|\$[\d,.]+|\b\d+\s*(users?|customers?|ms|seconds?)", text_lower):
        red_count += 2   # No metrics = significant red flag

    # High red-flag count but AI gave a high score → suspicious
    if red_count >= 5 and score >= 72:
        return (
            f"Score-evidence mismatch: {red_count} red-flag patterns detected "
            f"but score is {score}/100. Feedback may be overly generous — "
            "verify the overview cites specific evidence."
        )

    # Low red-flag count but AI gave a very low score → suspicious
    if red_count <= 1 and score <= 30:
        return (
            f"Score-evidence mismatch: no clear red-flag patterns detected "
            f"but score is {score}/100. The AI may have been overly harsh — "
            "check whether the overview justifies this score."
        )

    return None


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

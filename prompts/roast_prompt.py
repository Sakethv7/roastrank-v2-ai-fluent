# prompts/roast_prompt.py — DESCRIPTION Competency
#
# 4D Framework: DESCRIPTION
# "Describe the task with enough precision that a well-aligned AI produces
#  consistent, useful output — not just a plausible-sounding response."
#
# Prompt engineering techniques used in this file:
#
#   1. RUBRIC INJECTION (DELEGATION bridge) — The human-defined rubric from
#      rubric.py is imported and injected at call time. The AI never sees
#      hardcoded scoring criteria — it sees whatever the human has defined.
#      Changing rubric.py changes AI behavior without touching this file.
#
#   2. FEW-SHOT EXAMPLES — Three concrete examples (one bad, two good) show
#      the model what acceptable output looks like. Few-shot examples are more
#      reliable than descriptions alone for format-sensitive tasks.
#
#   3. NEGATIVE EXAMPLES — Showing the model what NOT to produce (the BAD
#      example below) reduces the rate of generic, low-quality responses.
#      Negative examples complement positive ones.
#
#   4. CHAIN-OF-THOUGHT INSTRUCTION — "First identify the single most
#      specific flaw..." prompts the model to reason before generating,
#      which improves output quality on subjective tasks.
#
#   5. JSON SCHEMA CONSTRAINT — The output format is specified with exact
#      field names, types, and descriptions. This is enforced at three
#      levels: (a) this prompt, (b) the API's output_config JSON schema,
#      (c) validator.py post-hoc checking.

import re

from rubric import rubric_summary


# ─────────────────────────────────────────────────────────────────────────────
# FEW-SHOT EXAMPLES
# Technique: Negative + positive examples anchor the output style and quality.
# The BAD example explicitly shows what the model must not produce.
# ─────────────────────────────────────────────────────────────────────────────
_FEW_SHOT_EXAMPLES = """
=== OUTPUT EXAMPLES (study these carefully) ===

--- EXAMPLE: BAD OUTPUT (do not produce this) ---
Reason this is bad: generic phrases, no resume content referenced, confidence dishonestly high.
{
  "one_line": "Your resume lacks clarity and is full of buzzwords.",
  "overview": "The resume is confusing and hard to follow. You need to be more specific about your skills and achievements to stand out from the crowd.",
  "fun_obs": "Consider revising your resume to make it clearer.",
  "score": 42,
  "confidence": 0.9
}

--- EXAMPLE: GOOD OUTPUT for a weak resume ---
{
  "one_line": "You listed 'Microsoft Excel' as a technical skill on a machine learning resume in 2024.",
  "overview": "Three 'Senior Engineer' roles with bullet points so identical they could be copy-pasted — and may have been. The only measurable number in the entire document is a graduation year. The rubric's Impact dimension is a flatline.",
  "fun_obs": "The resume claims to have 'revolutionized data pipelines' at a startup that apparently has no web presence. Bold move listing it first.",
  "score": 29,
  "confidence": 0.88
}

--- EXAMPLE: GOOD OUTPUT for a strong resume ---
{
  "one_line": "Shipped a production ML model at 24 with P50 latency numbers — this person has receipts.",
  "overview": "Every role shows measurable scope increase. The infrastructure work reduced costs 40% (actual figure, not vibes). Skill depth is evidenced by projects, not a list of buzzwords. Only mild credibility flag: 'led a team of 15' as a senior IC.",
  "fun_obs": "The only thing wrong with this resume is that the person reading it will immediately start worrying they can't afford to hire you.",
  "score": 87,
  "confidence": 0.93
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT JSON SCHEMA
# Technique: Exact schema specification prevents missing fields and type errors.
# Matches the JSON schema in main.py's output_config AND validator.py's checks.
# ─────────────────────────────────────────────────────────────────────────────
_OUTPUT_SCHEMA = """
=== REQUIRED OUTPUT FORMAT (respond with ONLY this JSON — no markdown, no explanation) ===
{
  "one_line": "One specific, quotable sentence referencing actual resume content. Max 25 words.",
  "overview": "2–3 sentences applying rubric criteria with specific references to what you read. Mention the rubric dimension driving your score.",
  "fun_obs": "A creative, memorable punchline comparing something specific in the resume to something else. Must reference something real from the resume.",
  "score": <integer 1–100 derived from the rubric bands above>,
  "confidence": <float 0.0–1.0: how specifically does your feedback reference actual resume content?>
}
"""


def _scan_residual_flags(resume_text: str) -> str:
    """
    Stage 2 of the two-stage prompt pipeline — the QJL residual layer.

    TurboQuant analogy:
      Stage 1 (rubric_summary = PolarQuant core): full rubric injected at
        high fidelity — every dimension, weight, and flag definition.
      Stage 2 (this function = QJL residual): a 1-bit signal per rubric
        dimension based on what was actually detected in THIS resume.

    The QJL transform in TurboQuant takes the compression residual, projects
    it through a random Gaussian matrix, and stores just the sign (+1 / -1)
    of each projection — enough to eliminate bias without memory overhead.

    Here: we scan for known rubric flag patterns and return a compact
    "attention residual" block — a binary active/inactive signal per dimension.
    This pre-anchors Claude's attention to the real patterns in the text
    instead of recapping the full rubric (Stage 1 already did that).

    Result: fewer generic responses. Claude sees WHERE the evidence is before
    it starts reasoning — reducing the attention equivalent of "quantization
    bias" (generic output that ignores resume specifics).
    """
    text_lower = resume_text.lower()
    flags: list[str] = []

    # ── IMPACT dimension scan ─────────────────────────────────────────────────
    weak_verbs = re.findall(
        r"\b(helped|assisted|worked on|supported|participated|involved in|contributed to)\b",
        text_lower,
    )
    has_metrics = bool(re.search(
        r"\b\d+\s*[%x×]\b|\$[\d,.]+|\b\d+\s*(users?|customers?|requests?|ms|seconds?|gb|tb|k\b)",
        text_lower,
    ))
    if weak_verbs:
        sample = sorted(set(weak_verbs))[:2]
        flags.append(
            f"[IMPACT ⚑] Weak verbs present: {', '.join(repr(v) for v in sample)}"
            " — penalise unless surrounding context shows real ownership"
        )
    else:
        flags.append("[IMPACT ✓] No passive ownership verbs detected")
    if not has_metrics:
        flags.append("[IMPACT ⚑] No quantified metrics found (no %, $, counts, latency figures)")

    # ── SKILLS dimension scan ─────────────────────────────────────────────────
    filler_skills = re.findall(
        r"\b(microsoft\s+office|ms\s+office|excel|word|google\s+docs|google\s+sheets"
        r"|email|teamwork|communication|time\s+management|interpersonal)\b",
        text_lower,
    )
    if filler_skills:
        sample = sorted(set(filler_skills))[:2]
        flags.append(f"[SKILLS ⚑] Filler/soft skills listed: {', '.join(repr(s) for s in sample)}")
    else:
        flags.append("[SKILLS ✓] No obvious filler skills")

    has_depth = bool(re.search(
        r"\b(python|javascript|typescript|react|vue|angular|node|fastapi|django|flask"
        r"|pytorch|tensorflow|keras|scikit|pandas|numpy|sql|postgres|mysql|redis"
        r"|kafka|spark|airflow|kubernetes|docker|aws|gcp|azure|terraform|rust|go|java"
        r"|c\+\+|swift|kotlin|llm|transformer|fine.tun)\b",
        text_lower,
    ))
    if not has_depth:
        flags.append("[SKILLS ⚑] No recognized technical stack detected")

    # ── CLARITY dimension scan ────────────────────────────────────────────────
    buzzwords = re.findall(
        r"\b(results.driven|passionate|synergistic|dynamic|proactive|self.starter"
        r"|go.getter|ninja|rockstar|guru|thought\s+leader|leverage|utilize|impactful"
        r"|innovative|cutting.edge|world.class|best.in.class)\b",
        text_lower,
    )
    if buzzwords:
        sample = sorted(set(buzzwords))[:2]
        flags.append(f"[CLARITY ⚑] Buzzwords detected: {', '.join(repr(b) for b in sample)}")
    else:
        flags.append("[CLARITY ✓] No buzzword clusters found")

    # ── CREDIBILITY dimension scan ────────────────────────────────────────────
    big_claims = re.findall(r"\b(led|managed|directed|oversaw)\s+(?:a\s+)?(?:team\s+of\s+)?(\d+)", text_lower)
    if big_claims:
        verb, size = big_claims[0]
        n = int(size)
        if n >= 15:
            flags.append(
                f"[CREDIBILITY ⚑] Large team claim: '{verb} {size} people'"
                " — verify title/seniority matches this scope"
            )
        else:
            flags.append(f"[CREDIBILITY ✓] Team size claim ({size}) is plausible")
    else:
        flags.append("[CREDIBILITY —] No explicit team-size claims found")

    header = (
        "=== STAGE 2: RESIDUAL ATTENTION FLAGS ===\n"
        "Pre-scanned patterns in this resume. Use these as focused attention"
        " anchors — they show WHERE the evidence is for each rubric dimension.\n"
    )
    return header + "\n".join(flags)


def build_roast_prompt(resume_text: str, mode: str) -> str:
    """
    Build the full user-turn prompt for a resume roast.

    Two-stage prompt pipeline (TurboQuant-inspired):

    STAGE 1 — Core rubric injection (PolarQuant analogue):
      rubric_summary() injects the full human-defined scoring rubric at high
      fidelity. This is the main compression — all four dimensions, weights,
      red/green flags, score bands. Equivalent to the PolarQuant stage:
      high-quality compression of the "what to evaluate" knowledge.

    STAGE 2 — Residual flag scan (QJL residual analogue):
      _scan_residual_flags() does a quick regex pass over the resume text
      and returns a 1-bit active/inactive signal per rubric dimension.
      This is the QJL residual layer — a tiny, targeted signal that tells
      Claude WHERE the evidence is, eliminating "attention bias" (the tendency
      to write generic output when specifics aren't surfaced early).

    DELEGATION: rubric_summary() pulls human-defined criteria from rubric.py.
    DESCRIPTION: Two-stage structure + few-shot + chain-of-thought + schema.

    Args:
        resume_text: Extracted, block-quantized resume text.
        mode: 'quick' (punchy one-liner focus) or 'full' (all four dimensions).

    Returns:
        A complete user-turn prompt string ready to send to the Claude API.
    """
    # STAGE 1: Core rubric — high-fidelity compression of scoring knowledge
    rubric = rubric_summary()

    # STAGE 2: Residual attention flags — 1-bit signal per dimension
    residual = _scan_residual_flags(resume_text)

    mode_instruction = (
        "Focus on the single most memorable flaw or strength. Be punchy."
        if mode == "quick"
        else "Cover all four rubric dimensions. Be comprehensive and specific."
    )

    return f"""\
Roast the following resume using the rubric and instructions below.

{rubric}

MODE: {mode.upper()} — {mode_instruction}

{_FEW_SHOT_EXAMPLES}

=== CHAIN-OF-THOUGHT INSTRUCTIONS ===
Before writing your response, think through these steps:
1. Read the resume carefully. What is the SINGLE most specific, interesting flaw or strength?
2. Which rubric dimension drives the score most — and what is your evidence from the text?
3. What exact phrase, job title, skill, or claim can you quote or reference in your one_line?
4. How honest is your confidence score? Only give >= 0.8 if you're referencing 3+ specifics.

=== RESUME TEXT ===
{resume_text}
=== END RESUME ===

{residual}

{_OUTPUT_SCHEMA}"""

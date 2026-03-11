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


def build_roast_prompt(resume_text: str, mode: str) -> str:
    """
    Build the full user-turn prompt for a resume roast.

    DELEGATION: The rubric is injected from rubric.py at call time.
      The AI never sees hardcoded scoring criteria — only what humans define.

    DESCRIPTION: Rubric + few-shot examples + chain-of-thought + schema
      are all combined here into one structured, purposeful prompt.

    Args:
        resume_text: Extracted resume text (already truncated to MAX_TEXT_CHARS).
        mode: 'quick' (punchy one-liner focus) or 'full' (comprehensive analysis).

    Returns:
        A complete user-turn prompt string ready to send to the Claude API.
    """
    rubric = rubric_summary()  # DELEGATION: pull human-defined criteria at runtime

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

{_OUTPUT_SCHEMA}"""

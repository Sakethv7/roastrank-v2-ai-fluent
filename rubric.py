# rubric.py — DELEGATION Competency
#
# 4D Framework: DELEGATION
# "Humans define the rules; AI handles only the natural language judgment."
#
# This file is the single source of truth for ALL scoring criteria.
# The AI reads this rubric as context — it does NOT invent criteria.
# To change how resumes are scored, edit THIS file. Never edit a prompt.
#
# Human editors own:  scoring dimensions, weights, red/green flags, score bands
# AI is responsible for: applying natural language judgment within these criteria

from dataclasses import dataclass, field
from typing import List


@dataclass
class ScoringDimension:
    """A single dimension of evaluation — fully human-defined."""
    name: str
    weight: float           # 0.0–1.0; all weights must sum to 1.0
    description: str        # What this dimension measures
    red_flags: List[str]    # Human-written patterns that lower scores
    green_flags: List[str]  # Human-written patterns that raise scores


@dataclass
class ScoreBand:
    """A human-defined label for a score range."""
    label: str
    min_score: int
    max_score: int
    verdict: str            # A human-written verdict sentence shown to users


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN-DEFINED SCORING DIMENSIONS
# Edit these to change what the AI evaluates. Weights must sum to 1.0.
# ─────────────────────────────────────────────────────────────────────────────
SCORING_DIMENSIONS: List[ScoringDimension] = [
    ScoringDimension(
        name="Impact & Achievements",
        weight=0.30,
        description=(
            "Does the resume quantify accomplishments with metrics, "
            "outcomes, and measurable results — not just duties?"
        ),
        red_flags=[
            "vague verbs: 'helped', 'assisted', 'worked on', 'supported'",
            "no numbers, percentages, dollar amounts, or scale indicators",
            "describes what the role was, not what was accomplished",
        ],
        green_flags=[
            "specific metrics: percentages, user counts, latency figures, revenue",
            "clear before/after or problem/solution framing",
            "ownership verbs: 'built', 'led', 'shipped', 'reduced', 'grew'",
        ],
    ),
    ScoringDimension(
        name="Skill Relevance & Currency",
        weight=0.25,
        description=(
            "Are listed skills current, specific, and relevant to target roles? "
            "Are they evidenced by actual work, not just listed?"
        ),
        red_flags=[
            "lists 'Microsoft Office', 'Google Docs', or 'email' as technical skills",
            "lists 'communication', 'teamwork', or 'leadership' with no evidence",
            "stale technologies listed without explanation (Flash, COBOL on a new grad resume)",
            "skill section has 30+ tools with no depth signals",
        ],
        green_flags=[
            "specific frameworks and tools evidenced by projects or roles",
            "skills have visible depth: not just 'Python' but the domain it's used in",
            "current, in-demand technologies appropriate to career stage",
        ],
    ),
    ScoringDimension(
        name="Clarity & Signal-to-Noise",
        weight=0.25,
        description=(
            "Is the resume focused? Does each line add new signal "
            "or just fill space with buzzwords and repetition?"
        ),
        red_flags=[
            "stacking buzzwords without substance: 'synergistic', 'passionate', 'results-driven'",
            "job titles inflated far beyond described scope",
            "identical bullet points repeated across multiple roles",
            "objective statement or summary that could apply to anyone",
        ],
        green_flags=[
            "each bullet adds distinct, new information",
            "clear progression of scope and responsibility across roles",
            "concise language — high information per word",
        ],
    ),
    ScoringDimension(
        name="Credibility & Coherence",
        weight=0.20,
        description=(
            "Does the resume tell a believable, consistent career story? "
            "Do claimed titles and responsibilities match each other?"
        ),
        red_flags=[
            "claims to have 'led' 10+ person teams as a first-year employee",
            "titles that don't align with described responsibilities",
            "companies or projects that seem fabricated or unverifiable in context",
            "scope claims that escalate implausibly between roles",
        ],
        green_flags=[
            "consistent growth narrative with increasing scope",
            "titles and responsibilities that match each other sensibly",
            "education and experience are coherent with claimed expertise level",
        ],
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# HUMAN-DEFINED SCORE BANDS
# Edit these to change how scores are labeled and interpreted.
# ─────────────────────────────────────────────────────────────────────────────
SCORE_BANDS: List[ScoreBand] = [
    ScoreBand("Disaster",    1,  30, "This resume needs emergency surgery before it sees a recruiter."),
    ScoreBand("Weak",       31,  50, "There's a resume in here somewhere, buried under the noise."),
    ScoreBand("Average",    51,  70, "Hirable but forgettable. Does the job, won't get the dream job."),
    ScoreBand("Solid",      71,  85, "Strong signals, clear story. A few tweaks away from standout."),
    ScoreBand("Impressive", 86, 100, "Hard to ignore. This resume earns respect on the first read."),
]

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS (human-controlled operational limits)
# ─────────────────────────────────────────────────────────────────────────────
SCORE_MIN = 1
SCORE_MAX = 100
MAX_TEXT_CHARS = 4000   # Max resume characters sent to AI — controls cost & focus


# ─────────────────────────────────────────────────────────────────────────────
# RUBRIC HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_band(score: int) -> ScoreBand:
    """Return the ScoreBand that contains the given score."""
    for band in SCORE_BANDS:
        if band.min_score <= score <= band.max_score:
            return band
    return SCORE_BANDS[-1]


def rubric_summary() -> str:
    """
    Returns a human-readable rubric string injected into every AI prompt.
    This is the DELEGATION bridge: the human-defined criteria reach the AI
    through this function, not through hardcoded prompt text.
    """
    lines = [
        "=== SCORING RUBRIC (human-defined — apply these criteria exactly) ===",
        "You must apply the dimensions below when computing your score.",
        "Do NOT invent additional criteria beyond what is listed here.\n",
    ]
    for dim in SCORING_DIMENSIONS:
        lines.append(f"[{dim.name}]  Weight: {int(dim.weight * 100)}%")
        lines.append(f"  Evaluate: {dim.description}")
        lines.append(f"  Penalize: {'; '.join(dim.red_flags)}")
        lines.append(f"  Reward:   {'; '.join(dim.green_flags)}\n")

    lines.append("=== SCORE BANDS ===")
    for band in SCORE_BANDS:
        lines.append(f"  {band.min_score:>3}–{band.max_score}: {band.label} — {band.verdict}")

    return "\n".join(lines)

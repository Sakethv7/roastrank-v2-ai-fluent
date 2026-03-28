# extractor.py — Block Quantization for Resume Text
#
# Inspired by ngrok's "Quantization from the ground up":
#   "Quantize in blocks of 32–256 parameters — not the whole model at once.
#    This prevents outliers in one section from corrupting the entire range."
#
# Applied here:
#   A naive text[:4000] truncation is "whole-model quantization" — a bloated
#   Objective section (low signal) consumes budget that should go to Work
#   Experience (high signal). We fix this by treating each resume section as
#   an independent block, assigning a signal weight, and greedily packing the
#   highest-weight blocks within the character budget.
#
# TurboQuant parallel:
#   PolarQuant converts Cartesian → polar (radius + angle) to simplify geometry
#   before quantization. Here we convert flat text → labeled sections to
#   simplify the structure before context-window compression.
#
# Result:
#   Claude always sees the most information-dense content, regardless of where
#   it sits in the document. A 10-page resume with a 3-paragraph Objective
#   section won't crowd out the Work Experience bullets.

import re
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# SECTION SIGNAL WEIGHTS
# Each resume section type is assigned a signal weight (0.0–1.0).
# Higher weight = more useful signal for rubric scoring.
# These are the "block scale factors" from ngrok's block quantization.
# ─────────────────────────────────────────────────────────────────────────────
_SECTION_WEIGHTS: dict = {
    # High signal — direct evidence for rubric dimensions
    "experience":            1.00,  # Impact & Achievements, Credibility
    "work experience":       1.00,
    "employment":            1.00,
    "professional experience": 1.00,
    "career history":        1.00,
    "work history":          1.00,
    # Good signal — evidences skill depth and project scope
    "projects":              0.82,
    "side projects":         0.82,
    "personal projects":     0.82,
    "open source":           0.82,
    "portfolio":             0.80,
    # Moderate signal — evidences skills, but often low depth
    "skills":                0.78,
    "technical skills":      0.78,
    "core competencies":     0.75,
    "technologies":          0.75,
    "tech stack":            0.75,
    "technical expertise":   0.75,
    "tools":                 0.70,
    # Lower signal — important but brief
    "education":             0.60,
    "academic background":   0.60,
    "qualifications":        0.60,
    "certifications":        0.55,
    "certificates":          0.55,
    "awards":                0.52,
    "honors":                0.52,
    "publications":          0.50,
    "languages":             0.48,
    "volunteer":             0.45,
    # Low signal — context, but rarely scored
    "summary":               0.28,
    "professional summary":  0.28,
    "objective":             0.22,
    "profile":               0.28,
    "about":                 0.28,
    # Near-zero signal — consume budget for nothing useful
    "references":            0.05,
    "contact":               0.05,
    "personal details":      0.05,
    "address":               0.05,
}

_DEFAULT_WEIGHT = 0.65   # Content before any section header (usually header/contact)
_FALLBACK_BLOCK_SIZE = 400  # chars per paragraph-block when no headers detected


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def extract_blocks(text: str, budget: int) -> str:
    """
    Block-quantize a resume: split into semantic sections, weight each section
    by information density, and pack the highest-signal sections within budget.

    Args:
        text:   Raw resume text from file extraction.
        budget: Max characters to include (MAX_TEXT_CHARS from rubric.py).

    Returns:
        Packed resume text within budget, ordered by signal weight descending,
        then by original document position for readability.
    """
    if len(text) <= budget:
        return text  # No compression needed — pass through unchanged

    sections = _detect_sections(text)

    if len(sections) <= 1:
        # No section structure detected — fall back to paragraph blocks
        sections = _paragraph_blocks(text)

    # Sort by weight descending for greedy packing
    by_weight = sorted(sections, key=lambda s: s[2], reverse=True)

    packed: List[Tuple[str, float, int]] = []   # (text, weight, original_idx)
    used = 0

    for idx, (section_text, weight, orig_idx) in enumerate(by_weight):
        if used >= budget:
            break
        remaining = budget - used
        if len(section_text) <= remaining:
            packed.append((section_text, weight, orig_idx))
            used += len(section_text)
        else:
            # Partial block: truncate to remaining budget
            # Prefer to cut at a newline rather than mid-word
            cut = section_text.rfind("\n", 0, remaining)
            truncated = section_text[:cut] if cut > 0 else section_text[:remaining]
            packed.append((truncated + "\n[…section truncated]", weight, orig_idx))
            used = budget
            break

    # Re-sort by original document order so the text reads naturally
    packed.sort(key=lambda x: x[2])

    return "\n".join(p[0] for p in packed).strip()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _detect_sections(text: str) -> List[Tuple[str, float, int]]:
    """
    Split resume text into (section_text, weight, original_index) blocks
    by detecting common section header patterns.
    """
    lines = text.split("\n")
    sections: List[Tuple[str, float, int]] = []

    current_lines: List[str] = []
    current_weight: float = _DEFAULT_WEIGHT
    current_idx: int = 0
    section_count: int = 0

    for i, line in enumerate(lines):
        weight = _header_weight(line)
        if weight is not None:
            # Flush current section
            block = "\n".join(current_lines).strip()
            if block:
                sections.append((block + "\n", current_weight, current_idx))
            # Start new section
            current_lines = [line]
            current_weight = weight
            current_idx = section_count
            section_count += 1
        else:
            current_lines.append(line)

    # Flush final section
    block = "\n".join(current_lines).strip()
    if block:
        sections.append((block + "\n", current_weight, current_idx))

    return sections


def _header_weight(line: str) -> Optional[float]:
    """
    Return the signal weight if this line looks like a section header,
    or None if it is regular content.

    A "section header" is a short line (< 45 chars) whose normalized text
    matches a known section keyword. All-caps variants are also accepted.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 45:
        return None

    # Skip lines that look like bullet points, dates, or sentences
    if stripped.startswith(("-", "•", "·", "*", "–", "▸")) or stripped[0].isdigit():
        return None
    if "." in stripped and len(stripped) > 20:
        return None

    normalized = stripped.lower().rstrip(":").rstrip()

    # Exact match
    if normalized in _SECTION_WEIGHTS:
        return _SECTION_WEIGHTS[normalized]

    # Prefix match (e.g. "Technical Skills & Tools" matches "technical skills")
    for keyword, weight in _SECTION_WEIGHTS.items():
        if normalized.startswith(keyword):
            return weight

    return None


def _paragraph_blocks(text: str) -> List[Tuple[str, float, int]]:
    """
    Fallback: split into paragraph-sized blocks when no section headers found.

    Earlier paragraphs are weighted higher (most resumes put the most
    important content near the top). Weight decays linearly with position —
    mirrors ngrok's asymmetric quantization insight that data distributions
    aren't uniform and the scale should reflect actual density.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    blocks: List[Tuple[str, float, int]] = []

    for i, para in enumerate(paragraphs):
        # Linear decay: first paragraph = 0.90, -0.06 per step, floor at 0.30
        weight = max(0.30, 0.90 - i * 0.06)
        blocks.append((para + "\n\n", weight, i))

    return blocks

# AI Limitations — RoastRank v2

> **DILIGENCE Competency**: Honest documentation of AI limitations is part of responsible deployment.
> This file should be read before using AI scores to make any consequential decisions.

---

## What This AI Can Do

- Read resume text and apply a human-defined rubric to produce a score
- Generate specific, creative feedback grounded in visible resume content
- Self-report confidence when feedback may be generic rather than specific
- Flag its own uncertainty through the confidence field (validated by `validator.py`)

---

## What This AI Cannot Do

### It Cannot Verify Facts
The AI reads text only. It has no ability to verify:
- Whether claimed achievements actually happened
- Whether employment dates are accurate or gaps are explained
- Whether listed companies exist or employed the candidate
- Whether claimed degrees, certifications, or projects are real

**A resume with fabricated content will score the same as a truthful one.**

### It Cannot Account for Context
- Industry norms vary widely — a "weak" ML resume may be strong for embedded systems
- Career gaps, non-linear paths, and alternative credentials are systematically undervalued
- Domain-specific skills outside common tech stacks may not be recognized
- Resumes written in non-standard formats (graphic design CVs, academic CVs) score poorly

### It Cannot Replace Human Judgment
- A high score does not guarantee interviews or offers
- A low score does not mean you won't get hired
- Recruiters weigh factors invisible to this system: referrals, timing, fit, and interviews
- The rubric reflects one set of values chosen by the tool's author — not universal truth

---

## Known Failure Modes

| Mode | Description | Indicator |
|------|-------------|-----------|
| Generic feedback | AI writes canned responses unrelated to resume | `confidence < 0.6` + validator warning |
| PDF extraction failure | Heavily formatted PDFs may extract as garbled text | `validator.py` flags empty/short content |
| Short resume underscoring | Resumes under ~200 words produce unreliable scores | Low confidence, thin overview |
| Non-English content | System is optimized for English — other languages score poorly | No explicit warning (known gap) |
| Inflated job titles | AI cannot detect industry-specific title norms | No mitigation |
| Visual resumes | Image-based or design-heavy PDFs may extract no text | Extraction failure warning |

---

## Bias Disclosure

Large language models are trained on text data that reflects historical patterns in hiring. This system may:

- **Favor traditional formats**: Resumes written in formal American English style with standard sections
- **Underweight non-traditional paths**: Bootcamp grads, career changers, freelancers, artists
- **Apply uneven standards by field**: Tech resumes are likely better calibrated than those in healthcare, education, or trades
- **Reflect gender/cultural patterns**: Research shows LLMs can exhibit bias in resume screening; this tool has not been audited for such bias

---

## Data Handling

| What | How it's handled |
|------|-----------------|
| Resume text | Held in memory during processing only — never written to disk |
| Extracted name | Stored in memory for the current server session, cleared on restart |
| AI inputs (summaries) | Logged to `logs/ai_audit.jsonl` — no full resume text in logs |
| AI outputs (metadata) | Score, confidence, warning count logged — no verbatim text |
| Browser data | No cookies, no tracking, no analytics |

---

## Appropriate Use

This tool is appropriate for:
- Personal self-reflection and entertainment
- Identifying obvious resume red flags before applying
- Portfolio demonstration of responsible AI development (4D Framework)

This tool is **not** appropriate for:
- Screening job applicants
- Making hiring or promotion decisions
- Determining anyone's professional worth or capability
- Use in any regulated industry without independent human review

---

## Rubric Transparency

The scoring criteria are fully visible in [`rubric.py`](rubric.py). There are no hidden criteria.
The four dimensions and their weights are:

| Dimension | Weight |
|-----------|--------|
| Impact & Achievements | 30% |
| Skill Relevance & Currency | 25% |
| Clarity & Signal-to-Noise | 25% |
| Credibility & Coherence | 20% |

To understand exactly how your score was computed, read `rubric.py`.

# RoastRank v2 — AI-Fluent Edition

**Portfolio showcase of responsible AI development using the 4D Framework**

> Built on the [Anthropic AI Fluency course](https://www.anthropic.com) framework:
> **Delegation · Description · Discernment · Diligence**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Claude](https://img.shields.io/badge/Claude-Opus%204.6-purple.svg)](https://www.anthropic.com/)

---

## What Is This?

RoastRank v2 is a resume roasting app powered by Claude (Anthropic). It is intentionally designed as a **demonstration of responsible AI development** — every architectural decision maps to one of the four 4D Framework competencies.

The v1 version (in `../roastrank_CV/`) worked, but had these problems:
- Prompts inline in `main.py` with no structure
- Scoring criteria hardcoded in prompt text (AI defines what it scores)
- No validation of AI outputs before display
- Permanent SQLite storage of names and roasts
- No AI disclosure, no audit logging, no limitations documentation

**v2 fixes all of these.** Every file exists for a reason rooted in responsible AI practice.

---

## The 4D Framework — Code Map

### 1. DELEGATION
> *"Humans define the criteria. AI handles only the natural language judgment."*

| Component | File | What it does |
|-----------|------|--------------|
| Scoring rubric | [`rubric.py`](rubric.py) | Human-defined dimensions, weights, red flags, green flags, score bands |
| Rubric injection | [`prompts/roast_prompt.py`](prompts/roast_prompt.py) | `rubric_summary()` is called at runtime — AI never sees hardcoded criteria |

**Key principle**: If you want to change what the AI evaluates, you edit `rubric.py` — not a prompt. The AI is given the rubric as context and asked to apply it. It does not invent what to score on.

**Before (v1)**: Scoring criteria were a paragraph of text buried inside a 40-line prompt string in `main.py`. Changing scoring behavior required editing the prompt directly.

**After (v2)**: Four structured `ScoringDimension` objects with `name`, `weight`, `description`, `red_flags`, and `green_flags` — all editable by a human without touching any prompt.

---

### 2. DESCRIPTION
> *"Tell the AI exactly what you need — role, constraints, format, examples."*

| Component | File | Technique used |
|-----------|------|----------------|
| System prompt | [`prompts/system_prompt.py`](prompts/system_prompt.py) | Role definition, behavioral DO/DO NOT constraints, output contract, confidence self-assessment |
| User prompt | [`prompts/roast_prompt.py`](prompts/roast_prompt.py) | Rubric injection, few-shot examples (good + bad), chain-of-thought instructions, JSON schema |
| Structured output | [`main.py`](main.py) | `output_config` JSON schema enforces field types at the API level |

**Techniques in the prompts (each commented in the source)**:
- **Role definition**: Named persona ("RoastRank") with specific behavioral identity
- **Negative examples**: The BAD example in `roast_prompt.py` shows what not to produce
- **Few-shot examples**: Two GOOD examples anchor style and quality expectations
- **Chain-of-thought**: "First identify the single most specific flaw..." induces reasoning
- **Output contract**: JSON schema specified in prompt + API `output_config` + `validator.py`
- **Confidence self-assessment**: AI rates its own specificity — surfaces uncertainty

**Before (v1)**: One 40-line `prompt = f"""..."""` string inside `roast_resume()`. No examples, no constraints, no confidence signaling.

**After (v2)**: Prompts are a separate package (`prompts/`) with documented techniques in comments.

---

### 3. DISCERNMENT
> *"Don't blindly trust AI output. Validate it before showing users."*

| Component | File | Check performed |
|-----------|------|-----------------|
| Output validator | [`validator.py`](validator.py) | 6 checks: required fields, score range, confidence threshold, generic language, content length, resume-response overlap |
| Warning display | [`templates/result.html`](templates/result.html) | Warnings shown in orange panel before the result |
| Confidence bar | [`templates/result.html`](templates/result.html) | Visual indicator of AI self-reported confidence (green/yellow/red) |

**The 6 validation checks**:
1. **Required fields** — All five fields must be present (structural completeness)
2. **Score range** — Score must be within the rubric's 1–100 range (DELEGATION cross-check)
3. **Confidence threshold** — AI self-reports < 0.6 triggers a user-facing warning
4. **Generic language** — Pattern matching for known "canned response" phrases
5. **Content length** — Suspiciously short responses are flagged
6. **Resume-response overlap** — Does the feedback share vocabulary with the actual resume?

**Before (v1)**: `safe_json()` — a 5-line try/except that either parsed JSON or returned a fallback. No quality checking. Bad AI output reached users silently.

**After (v2)**: Every response passes through `validator.py` before display. Users see warnings alongside results, enabling informed judgment.

---

### 4. DILIGENCE
> *"Be honest about limitations. Handle data responsibly. Maintain an audit trail."*

| Component | File | What it does |
|-----------|------|--------------|
| Audit logging | [`logger.py`](logger.py) | Every AI call logged to `logs/ai_audit.jsonl` — input summaries, output metadata, warnings, token usage |
| Session-only storage | [`session.py`](session.py) | In-memory only — no SQLite, no disk writes, cleared on restart |
| AI disclosure | [`templates/index.html`](templates/index.html) | Yellow banner on every page: model name, intended use, limitations link |
| Result disclosure | [`templates/result.html`](templates/result.html) | Model ID shown on result, session-only notice, full disclosure block |
| Limitations docs | [`LIMITATIONS.md`](LIMITATIONS.md) | What the AI can/cannot do, known failure modes, bias disclosure, data handling |

**Before (v1)**:
- All roasts written permanently to `roasts.db`
- No logging of AI calls
- No AI disclosure anywhere
- No limitations documented
- Duplicate detection based on stored names

**After (v2)**:
- Zero disk writes for user data (logs contain only metadata, no resume text)
- Every AI call logged with timestamp, session ID, token count, warnings
- Disclosure notice on every page and result
- `LIMITATIONS.md` with bias disclosure, failure modes, appropriate use guidance

---

## Architecture

```
roastrank-v2-ai-fluent/
├── main.py                  # FastAPI app — orchestrates the 4D pipeline
│
├── rubric.py                # DELEGATION: Human-owned scoring criteria
│
├── prompts/
│   ├── __init__.py
│   ├── system_prompt.py     # DESCRIPTION: Role + constraints + output contract
│   └── roast_prompt.py      # DESCRIPTION: Rubric injection + few-shot + schema
│
├── validator.py             # DISCERNMENT: 6-check output validation layer
│
├── logger.py                # DILIGENCE: Structured JSONL audit logging
├── session.py               # DILIGENCE: In-memory session-only storage
│
├── templates/
│   ├── index.html           # DILIGENCE: AI disclosure notice
│   ├── result.html          # DISCERNMENT: Warnings panel + confidence bar
│   └── leaderboard.html     # DILIGENCE: Session-only data disclosure
│
├── static/
│   └── starfield.js         # Canvas animation (preserved from v1)
│
├── LIMITATIONS.md           # DILIGENCE: Honest AI limitations documentation
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

## Data Flow

```
User uploads resume
       │
       ▼
  extract_text()
       │
       ▼
  guess_name()
       │
       ▼
  new_session_id()          ← DILIGENCE: random ID, no user tracking
       │
       ▼
  build_roast_prompt()      ← DESCRIPTION: structured prompt
    └── rubric_summary()    ← DELEGATION: human criteria injected here
       │
       ▼
  Claude API (streaming)    ← DESCRIPTION: output_config JSON schema
    model: claude-opus-4-6
       │
       ▼
  validate_response()       ← DISCERNMENT: 6 checks, warnings attached
       │
       ▼
  log_ai_call()             ← DILIGENCE: metadata logged, no PII
       │
       ▼
  save_result() in memory   ← DILIGENCE: no database write
       │
       ▼
  result.html rendered      ← DISCERNMENT: warnings shown to user
                            ← DILIGENCE: disclosure + model ID displayed
```

---

## Quick Start

```bash
# 1. Clone and enter the project
cd roastrank-v2-ai-fluent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Anthropic API key
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY=sk-ant-...

# 4. Run
uvicorn main:app --reload --host 0.0.0.0 --port 7860

# 5. Open http://localhost:7860
```

---

## Comparing v1 vs v2

| Concern | v1 (roastrank_CV) | v2 (this repo) |
|---------|-------------------|-----------------|
| Scoring criteria | Hardcoded in prompt string | Human-defined in `rubric.py` |
| Prompts | Inline in `main.py` | Separate `prompts/` package with comments |
| Output validation | 5-line `safe_json()` try/except | 6-check `validator.py` with user-visible warnings |
| Data storage | Permanent SQLite | Session memory only |
| AI disclosure | None | Yellow banner + result page disclosure |
| Audit logging | None | Structured JSONL with token counts |
| Limitations docs | None | `LIMITATIONS.md` with bias disclosure |
| Model | OpenAI GPT-4o-mini | Anthropic Claude Opus 4.6 |
| Prompt structure | One 40-line f-string | Role-set system prompt + rubric + few-shot + schema |

---

## License

MIT — made as a portfolio piece for the Anthropic AI Fluency course.

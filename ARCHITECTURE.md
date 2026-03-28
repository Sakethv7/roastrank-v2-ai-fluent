# RoastRank v2 — Architecture & Concepts

> How the app is built, what was broken, and why each fix matters.

---

## System Overview

```
Browser
  │
  ├─ GET /           → index.html   (upload form + AI disclosure)
  ├─ POST /upload    → roast pipeline → result.html
  ├─ GET /leaderboard → session leaderboard
  ├─ GET /limitations → LIMITATIONS.md rendered
  └─ GET /health     → JSON status check

roast pipeline
  ┌───────────────────────────────────────────────────────┐
  │  extract_text()  PDF/DOCX/TXT → raw string            │
  │       ↓                                               │
  │  build_roast_prompt()  injects rubric (DELEGATION)    │
  │       ↓                                               │
  │  Claude API  tools-based structured output            │
  │       ↓                                               │
  │  validate_response()  6 checks (DISCERNMENT)          │
  │       ↓                                               │
  │  log_ai_call()  JSONL audit (DILIGENCE)               │
  │       ↓                                               │
  │  save_result()  in-memory only (DILIGENCE)            │
  └───────────────────────────────────────────────────────┘
```

---

## The 4D Framework

Every file in this project maps to one of four responsible AI competencies:

```
┌─────────────┬──────────────────────────────────────────────────────┐
│ Competency  │ What it means                                        │
├─────────────┼──────────────────────────────────────────────────────┤
│ DELEGATION  │ Humans write the rules; AI only applies judgment     │
│             │ → rubric.py owns all scoring criteria & weights      │
├─────────────┼──────────────────────────────────────────────────────┤
│ DESCRIPTION │ Prompts are structured, versioned, and explicit      │
│             │ → prompts/system_prompt.py + prompts/roast_prompt.py │
├─────────────┼──────────────────────────────────────────────────────┤
│ DISCERNMENT │ AI output is validated before the user sees it       │
│             │ → validator.py runs 6 checks; warnings shown in UI   │
├─────────────┼──────────────────────────────────────────────────────┤
│ DILIGENCE   │ Data minimization, audit logging, honest disclosure  │
│             │ → session.py (no DB), logger.py, LIMITATIONS.md      │
└─────────────┴──────────────────────────────────────────────────────┘
```

---

## Structured Output: How Claude Returns JSON

### The Problem with `extra_body`

The original scaffold used an `extra_body` parameter to request JSON output:

```python
# ❌ BROKEN — not a real Anthropic API parameter
extra_body={
    "output_config": {
        "format": { "type": "json_schema", "schema": { ... } }
    }
}
```

This was invented syntax. The Anthropic HTTP API has no `output_config` field.
When the SDK sends it, one of two things happens:
- The API ignores unknown fields → Claude returns free-form text → `json.loads()` fails
- The API rejects the request with a `400 Bad Request` → `APIConnectionError`

Either way, the pipeline breaks silently or loudly.

### The Fix: Tool Use for Structured Output

The correct approach is to define a **tool** with a JSON schema and force Claude to call it.
This is the only officially supported way to get guaranteed structured JSON from Claude:

```python
# ✅ CORRECT — tools API enforces schema at the model level
tools=[{
    "name": "submit_roast",
    "description": "Submit the structured roast analysis result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "one_line":   {"type": "string"},
            "overview":   {"type": "string"},
            "fun_obs":    {"type": "string"},
            "score":      {"type": "integer"},
            "confidence": {"type": "number"},
        },
        "required": ["one_line", "overview", "fun_obs", "score", "confidence"],
    },
}],
tool_choice={"type": "tool", "name": "submit_roast"},
```

`tool_choice` with `"type": "tool"` forces Claude to call exactly that function —
it cannot return free-form text. The result arrives as `tool_block.input`, already a dict:

```python
# How to extract the result
tool_block = next(
    (b for b in response.content if b.type == "tool_use"), None
)
data = tool_block.input  # Already a dict — no json.loads() needed
```

```
┌─────────────────────────────────────────────────────────────────┐
│ Why this is better                                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. Schema enforced at the model level, not just in the prompt   │
│ 2. No JSON parsing — .input is already a Python dict            │
│ 3. Missing/extra fields are caught by the API before streaming  │
│ 4. Works with streaming — tool_use block appears in content[]   │
│ 5. validator.py still runs as the human-visible safety layer    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Three Layers of Output Enforcement

```
Layer 1 — Prompt engineering (prompts/roast_prompt.py)
  "Return ONLY valid JSON matching this schema: { ... }"
  Soft: the model is asked, but not forced

Layer 2 — Tools API (main.py: tool_choice)
  tool_choice={"type": "tool", "name": "submit_roast"}
  Hard: the model MUST call this tool — no other output allowed

Layer 3 — validator.py (DISCERNMENT)
  Checks score range, confidence, generic language, field presence
  Human-visible: warnings surfaced in UI so user can judge quality
```

All three layers work together. Removing any one degrades reliability.

---

## Data Flow (Detailed)

```
1. User uploads file (PDF / DOCX / TXT)
        │
2. extract_text() — reads bytes, detects format
   ├─ PDF:  PyPDF2.PdfReader → page text joined
   ├─ DOCX: python-docx Document → paragraph text joined
   └─ TXT:  raw bytes decoded as UTF-8
        │
3. guess_name() — heuristic: first 2-4 word line in first 10 lines
        │
4. new_session_id() — random UUID (NOT tied to browser or user)
        │
5. build_roast_prompt(text, mode)
   └─ rubric_summary() injected here — DELEGATION bridge
        │
6. client.messages.stream(tools=[...], tool_choice={...})
   └─ Claude Opus 4.6 → guaranteed JSON via tool_use
        │
7. validate_response(data, resume_text) — 6 checks
   ├─ Required fields present?
   ├─ Score in 1–100 range?
   ├─ Confidence ≥ 0.6?
   ├─ Generic phrases detected?
   ├─ Content long enough?
   └─ Response shares words with resume?
        │
8. log_ai_call() → logs/ai_audit.jsonl
   (input summary only — no raw resume text)
        │
9. save_result(RoastResult) → _session_store dict
   (memory only — never written to disk)
        │
10. render result.html with score, band, warnings, disclosure
```

---

## Session Storage vs. Database

```
v1 (roastrank_CV):                 v2 (this app):
┌────────────────────────┐         ┌────────────────────────┐
│  SQLite DB             │         │  Python dict (memory)  │
│  results table         │         │  _session_store        │
│  persists forever      │         │  cleared on restart    │
│  PII accumulates       │         │  no disk writes        │
│  no retention policy   │         │  zero PII at rest      │
└────────────────────────┘         └────────────────────────┘
         ↑                                    ↑
    Data liability                  Data minimization
```

The session-only design is not a limitation — it is a deliberate DILIGENCE choice.
It enforces data minimization by default and eliminates the need for a GDPR-style
data retention policy.

---

## Leaderboard: `band_label` Property

`leaderboard.html` needs a band label (e.g. "Solid") for each result.
This is computed from the score by `rubric.py:get_band()`.

**Before the fix:** `RoastResult` had no `band_label` attribute.
Jinja2 returns `Undefined` for missing attributes, so the label showed blank.

**After the fix:** A computed property on `RoastResult`:

```python
# session.py
@property
def band_label(self) -> str:
    return get_band(self.score).label  # "Disaster" / "Weak" / ... / "Impressive"
```

This keeps the label computation in `rubric.py` (single source of truth for band definitions)
while making it accessible as a simple attribute in templates.

---

## Deployment: Hugging Face Spaces

```
Repository
    │
    └─ README.md  (HF Spaces metadata in YAML frontmatter)
         sdk: docker
         app_file: main.py

Hugging Face Spaces
    │
    └─ Detects Dockerfile → builds image
         │
         ├─ FROM python:3.11-slim
         ├─ apt install poppler-utils  (PDF support)
         ├─ pip install -r requirements.txt
         └─ CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
              │
              Port 7860 ← HF Spaces default port (must match)
```

**Required:** Set `ANTHROPIC_API_KEY` as a **Space Secret** in the HF Spaces settings
(Repository → Settings → Variables and secrets → New secret).

Do NOT put the key in the Dockerfile or commit it to the repo.

---

## Deployment: Render

```
render.yaml
    type: web
    runtime: docker
    healthCheckPath: /health
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false   ← set manually in Render dashboard
```

Render builds the Dockerfile and exposes port 7860.
The `/health` endpoint returns 200 with model/session metadata.

---

---

## Quantization-Inspired Optimisations

> Techniques adapted from:
> - **TurboQuant** (Google / ICLR 2026) — two-stage KV cache compression: PolarQuant core + QJL residual
> - **ngrok "Quantization from the ground up"** — block quantization, asymmetric bands, KL divergence measurement

These are applied *analogously* — RoastRank calls the Claude API, it doesn't run models locally.
The same mathematical insights apply to a different resource: the LLM context window.

---

### 1. Block Quantization for Resume Text (`extractor.py`)

**ngrok source:** "Quantize in blocks of 32–256 parameters, not the whole model. This prevents
one outlier section from corrupting the scale for the entire range."

**Problem with naive truncation:**

```
Resume (8,000 chars)  →  text[:4000]  →  Claude sees
┌────────────────────────────────────────────────────────┐
│ John Smith                                             │  ← 200 chars (filler)
│ passionate results-driven professional...             │  ← 300 chars (Objective, low signal)
│ Work Experience ──────────────────────────────        │  ← 3,500 chars (high signal, truncated)
│                                                        │
│ [REST DROPPED — 4,000 chars consumed, budget gone]    │
└────────────────────────────────────────────────────────┘
```

**After block quantization:**

```
Resume (8,000 chars)  →  extract_blocks(text, 4000)  →  Claude sees
┌────────────────────────────────────────────────────────┐
│ Section       │ Signal Weight │ Budget used             │
├───────────────┼───────────────┼─────────────────────────┤
│ Experience    │ 1.00          │ 1,800 chars (full)      │  ← packed first
│ Projects      │ 0.82          │   900 chars (full)      │
│ Skills        │ 0.78          │   500 chars (full)      │
│ Education     │ 0.60          │   400 chars (full)      │
│ Objective     │ 0.22          │   400 chars (partial)   │  ← filled remaining
│ Contact/Refs  │ 0.05          │   DROPPED               │  ← budget exhausted
└────────────────────────────────────────────────────────┘
```

Section weights act as "quantization scale factors" — sections with more useful signal
for the rubric dimensions get a larger share of the context budget.

Fallback (no section headers detected): paragraph blocks with linearly decaying weights
(0.90 → 0.30), mirroring block quantization on unstructured data.

---

### 2. Two-Stage Prompt Pipeline (`prompts/roast_prompt.py`)

**TurboQuant source:** Stage 1 (PolarQuant) handles the main compression at near-optimal
quality. Stage 2 (QJL residual) applies a 1-bit error correction to eliminate bias —
just the sign (+1/-1) of each residual projection.

```
TurboQuant pipeline:
  [KV vector] → PolarQuant → [compressed keys]
                    ↓
              residual error  → QJL (sign bit only) → [bias eliminated]

Prompt pipeline:
  [resume_text] → rubric_summary() → [scoring knowledge, full fidelity]
                        ↓
                 _scan_residual_flags() → [1-bit per dimension: ⚑ or ✓]
```

**Stage 1 — Core rubric (PolarQuant analogue):**
`rubric_summary()` injects all four scoring dimensions, weights, red/green flags, and score bands.
This is the high-quality main compression — Claude gets the full "what to evaluate" knowledge.

**Stage 2 — Residual attention flags (QJL analogue):**
`_scan_residual_flags()` regex-scans the resume for known pattern categories and outputs
a compact signal block:

```
=== STAGE 2: RESIDUAL ATTENTION FLAGS ===
[IMPACT  ⚑] Weak verbs present: 'assisted', 'helped'
[IMPACT  ⚑] No quantified metrics found
[SKILLS  ⚑] Filler skills listed: 'microsoft office', 'communication'
[CLARITY ⚑] Buzzwords detected: 'passionate', 'results-driven'
[CREDIBILITY ✓] No implausible team-size claims
```

Each flag is one binary signal: active (⚑) or clear (✓). This tells Claude exactly where
the evidence is *before* it reasons — the same role QJL plays in TurboQuant: eliminating
systematic bias by correcting the residual before the inner product is computed.

**Why it reduces generic output:**
Without Stage 2, Claude must discover patterns by reading the full text. Generic output
happens when it doesn't find them fast enough. The residual flags pre-anchor attention
to real content, reducing "attention bias" (the tendency to fall back to canned phrasing
when the specific signals aren't surfaced early in the context).

---

### 3. Asymmetric Confidence Quantization (`validator.py`)

**ngrok source:** "Asymmetric quantization stores separate min/max values rather than
centering on zero. This reduces average error from 18% to 8.5% when the data
distribution is not centered."

```
Symmetric (old):                    Asymmetric (new):
────────────────────────────────    ─────────────────────────────────────
  0.0 ────────[0.6]──────── 1.0      0.0 ──[0.35]──[0.52]────────── 1.0
              ↑                             ↑        ↑
        single cutoff               CRITICAL  WARN (zero_point)

  Scale = 1 / 0.6                   scale = (1.0 - 0.0) / (qmax - qmin)
  zero_point = 0.5                  zero_point = 0.52  (real distribution center)
```

Claude confidence values cluster around 0.70–0.88 for typical responses.
The useful warning boundary is at ~0.52 (the lower tail of the actual distribution),
not 0.60 (the intuitive midpoint). This matches ngrok's insight that the zero point
should reflect where the data actually lives.

| Band | Range | Action |
|---|---|---|
| Critical | < 0.35 | Hard warning — output likely garbage, suggest re-upload |
| Low | 0.35 – 0.52 | Standard warning — may be generic |
| OK | ≥ 0.52 | No confidence warning |

---

### 4. Score-Flag Alignment Check — KL Divergence Analogue (`validator.py`)

**ngrok source:** "KL divergence measures the overlap between the original and quantized
probability distributions. Low overlap = high distortion."

```
P = expected score distribution (implied by detected evidence)
Q = AI's actual score

KL(P || Q) is high when:
  - Many red flags detected (P → low score) but AI scored high (Q ≠ P)
  - Few red flags detected (P → higher score) but AI scored very low (Q ≠ P)
```

This is validator **Check 7** — runs after the existing 6 checks and adds a warning if
the score-evidence alignment is suspiciously low:

```python
# High red-flag density + high score → suspicious
if red_count >= 5 and score >= 72:
    "Score-evidence mismatch: 5 red-flag patterns detected but score is 78/100"

# Low red-flag density + very low score → suspicious
if red_count <= 1 and score <= 30:
    "Score-evidence mismatch: no red-flag patterns detected but score is 22/100"
```

---

### Summary: Before vs After

```
BEFORE                              AFTER
──────────────────────────────────  ────────────────────────────────────────
text[:4000]                         extract_blocks(text, 4000)
  Naive truncation                    Section-aware block packing
  Low-signal content consumes         High-signal sections prioritised
  context budget                      within character budget

Single rubric injection             Two-stage prompt
  Full rubric in one block            Stage 1: core rubric (full fidelity)
  No resume-specific context          Stage 2: QJL residual flag scan
                                       (1-bit signal per dimension, pre-computed)

Single confidence threshold (0.60)  Asymmetric 3-band scale
  Symmetric around midpoint           CRITICAL < 0.35 / WARN < 0.52
  Doesn't match data distribution     Zero-point at real distribution center

6 validation checks                 7 validation checks
  No score-evidence alignment         + KL divergence: score vs detected
                                        flag density alignment check
```

---

## What Was Fixed

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `main.py` | `extra_body: output_config` — not a real API param, breaks structured output | Replaced with `tools` + `tool_choice` (official structured output method) |
| 2 | `main.py` | Missing `/limitations` route — broken link in `index.html` | Added route serving `LIMITATIONS.md` via `limitations.html` template |
| 3 | `session.py` | `RoastResult` missing `band_label` — leaderboard showed blank label | Added `@property band_label` using `get_band()` from `rubric.py` |
| 4 | `templates/` | `limitations.html` did not exist | Created template with client-side markdown renderer |

---

## File Reference

```
roastrank-v2-ai-fluent/
├── main.py              ← FastAPI app, routes, roast pipeline
├── rubric.py            ← DELEGATION: human-defined scoring criteria
├── validator.py         ← DISCERNMENT: 6-check output validation
├── logger.py            ← DILIGENCE: JSONL audit logging
├── session.py           ← DILIGENCE: in-memory ephemeral storage
├── prompts/
│   ├── system_prompt.py ← DESCRIPTION: role + constraints
│   └── roast_prompt.py  ← DESCRIPTION: rubric injection + few-shot
├── templates/
│   ├── index.html       ← Upload form + AI disclosure
│   ├── result.html      ← Roast result + warnings
│   ├── leaderboard.html ← Session leaderboard
│   └── limitations.html ← AI limitations disclosure (new)
├── static/
│   └── starfield.js     ← Canvas animation
├── Dockerfile           ← Container build (port 7860)
├── render.yaml          ← Render deployment config
├── README.md            ← HF Spaces metadata + documentation
└── LIMITATIONS.md       ← Honest AI limitations disclosure
```

# main.py — RoastRank v2: AI-Fluent Edition
#
# 4D Framework orchestration layer — this file wires the four competencies together:
#
#   DELEGATION  → rubric.py      Human criteria injected into prompts at runtime
#   DESCRIPTION → prompts/       All LLM prompts live in the prompts package
#   DISCERNMENT → validator.py   Every AI response is validated before display
#   DILIGENCE   → logger.py      Every AI call is audited; session.py: no persistence
#
# This file should contain NO inline prompts, NO scoring logic, NO hardcoded criteria.
# Those concerns are separated by design.

import io
import json
import os
import re
import tempfile

import anthropic
import PyPDF2
from docx import Document
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rubric import get_band, MAX_TEXT_CHARS
from extractor import extract_blocks
from validator import validate_response
from logger import log_ai_call, log_validation_event
from session import RoastResult, new_session_id, save_result, get_all_results, result_count
from prompts import SYSTEM_PROMPT, build_roast_prompt

load_dotenv()

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="RoastRank v2 — AI-Fluent Edition")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Anthropic client ─────────────────────────────────────────────────────────
api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. "
        "Copy .env.example to .env and add your key."
    )

client = anthropic.Anthropic(api_key=api_key)

# claude-opus-4-6: most capable model — appropriate for nuanced resume analysis
MODEL = "claude-opus-4-6"

# ── File extraction ──────────────────────────────────────────────────────────
def extract_text(file: UploadFile) -> str:
    """Extract readable text from PDF, DOCX, or TXT uploads."""
    ext = file.filename.lower()
    raw = file.file.read()

    if ext.endswith(".pdf"):
        try:
            pdf = PyPDF2.PdfReader(io.BytesIO(raw))
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if text.strip():
                return text
        except Exception as e:
            print(f"PDF extraction error: {e}")

    if ext.endswith(".docx"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            doc = Document(tmp_path)
            os.remove(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            if text.strip():
                return text
        except Exception as e:
            print(f"DOCX extraction error: {e}")

    # Fallback: treat as plain text
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def guess_name(text: str) -> str:
    """Heuristic name extraction from the first 10 lines of the resume."""
    for line in text.split("\n")[:10]:
        line = line.strip()
        if 2 <= len(line.split()) <= 4:
            if all(c.isalpha() or c.isspace() or c in "'-." for c in line):
                skip_words = {"resume", "cv", "curriculum", "vitae", "contact", "email", "phone"}
                if not any(w in line.lower() for w in skip_words):
                    return line
    return "Anonymous"


# ── Roast engine ─────────────────────────────────────────────────────────────
def roast_resume(text: str, mode: str, session_id: str) -> dict:
    """
    Main AI pipeline:
      1. Build prompt (DESCRIPTION — from prompts/)
      2. Call Claude with streaming (DILIGENCE — logged, session-scoped)
      3. Parse + validate response (DISCERNMENT — via validator.py)
      4. Return data with warnings attached

    Uses streaming via client.messages.stream() + get_final_message() to
    avoid HTTP timeouts on long resume inputs (per Anthropic SDK best practice).
    """
    if not text.strip():
        return {
            "one_line": "Your file contained no readable text.",
            "overview": "File extraction failed. Try uploading a cleaner PDF or DOCX.",
            "fun_obs": "",
            "score": 1,
            "confidence": 0.0,
            "warnings": ["File extraction failed — no text could be read from the upload."],
        }

    # DELEGATION: rubric criteria are injected inside build_roast_prompt()
    # Block-quantize the resume before sending: extract highest-signal sections
    # within the character budget instead of naive truncation.
    compressed = extract_blocks(text, MAX_TEXT_CHARS)
    prompt = build_roast_prompt(compressed, mode)

    # DILIGENCE: log the request (input summary only — no raw resume text in logs)
    log_ai_call(
        session_id=session_id,
        event="roast_request",
        model=MODEL,
        input_summary=f"mode={mode}, resume_chars={len(text)}, name_guess={guess_name(text)}",
        metadata={"mode": mode, "text_length": len(text)},
    )

    try:
        # Stream the response to handle long inputs without timeout.
        # DESCRIPTION: Force structured output via the tools API — Claude must call
        # "submit_roast" with exactly the schema fields we define. This is the
        # officially supported way to get guaranteed JSON output from Claude.
        # It acts as the third enforcement layer (after prompt + validator.py).
        _ROAST_TOOL = {
            "name": "submit_roast",
            "description": "Submit the structured roast analysis result.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "one_line":   {"type": "string", "description": "One-line punchy verdict"},
                    "overview":   {"type": "string", "description": "Multi-sentence rubric analysis"},
                    "fun_obs":    {"type": "string", "description": "A funny, specific observation"},
                    "score":      {"type": "integer", "description": "Score 1–100"},
                    "confidence": {"type": "number", "description": "Self-reported confidence 0.0–1.0"},
                },
                "required": ["one_line", "overview", "fun_obs", "score", "confidence"],
            },
        }

        with client.messages.stream(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[_ROAST_TOOL],
            tool_choice={"type": "tool", "name": "submit_roast"},
        ) as stream:
            response = stream.get_final_message()

        # Extract structured output from the tool_use block
        tool_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_block:
            data = tool_block.input  # Already a dict — no JSON parsing needed
        else:
            # Fallback: attempt to extract JSON from any text block
            raw_content = next(
                (b.text for b in response.content if hasattr(b, "text")), "{}"
            )
            match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        # DISCERNMENT: validate before showing to user
        data, warnings = validate_response(data, text)

        # DILIGENCE: log the response metadata (not full content)
        log_ai_call(
            session_id=session_id,
            event="roast_response",
            model=MODEL,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            output_data={
                "score": data.get("score"),
                "confidence": data.get("confidence"),
                "warnings_count": len(warnings),
            },
            warnings=warnings,
        )

        # DILIGENCE: log validation outcome separately for auditability
        log_validation_event(
            session_id=session_id,
            warnings=warnings,
            score=data.get("score", 1),
            confidence=float(data.get("confidence", 0.0)),
        )

        data["warnings"] = warnings
        return data

    except anthropic.RateLimitError as e:
        _log_error(session_id, f"RateLimitError: {e}")
        return _error_result(f"Rate limit reached. Please wait a moment and try again.")
    except anthropic.AuthenticationError:
        _log_error(session_id, "AuthenticationError")
        return _error_result("API key is invalid. Check your .env file.")
    except anthropic.APIConnectionError as e:
        _log_error(session_id, f"APIConnectionError: {e}")
        return _error_result("Could not connect to the Anthropic API. Check your network.")
    except Exception as e:
        _log_error(session_id, f"Unexpected error: {e}")
        return _error_result(f"An unexpected error occurred: {str(e)[:100]}")


def _log_error(session_id: str, error: str) -> None:
    log_ai_call(session_id=session_id, event="roast_error", model=MODEL, error=error)


def _error_result(message: str) -> dict:
    return {
        "one_line": "The roast engine hit an error.",
        "overview": message,
        "fun_obs": "",
        "score": 1,
        "confidence": 0.0,
        "warnings": [f"Error: {message}"],
    }


# ── Routes ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Landing page with AI disclosure notice and upload form."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):
    """
    Handle resume upload:
    1. Extract text from file
    2. Generate session ID (DILIGENCE: no persistent user tracking)
    3. Call roast engine (runs DELEGATION → DESCRIPTION → DISCERNMENT pipeline)
    4. Store result in memory only (DILIGENCE: no database write)
    5. Render result with band label, confidence, and any warnings
    """
    session_id = new_session_id()
    text = extract_text(file)
    name = guess_name(text)

    roast = roast_resume(text, mode, session_id)
    band = get_band(roast["score"])

    result = RoastResult(
        session_id=session_id,
        name=name,
        score=roast["score"],
        one_line=roast["one_line"],
        overview=roast["overview"],
        fun_obs=roast["fun_obs"],
        confidence=float(roast.get("confidence", 0.0)),
        warnings=roast.get("warnings", []),
        mode=mode,
    )
    save_result(result)  # DILIGENCE: memory only — no disk persistence

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": roast["score"],
        "band_label": band.label,
        "band_verdict": band.verdict,
        "one_line": roast["one_line"],
        "overview": roast["overview"],
        "fun_obs": roast["fun_obs"],
        "confidence": float(roast.get("confidence", 0.0)),
        "confidence_pct": f"{float(roast.get('confidence', 0.0)):.0%}",
        "warnings": roast.get("warnings", []),
        "session_id": session_id,
        "model": MODEL,
    })


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard(request: Request):
    """
    Session-only leaderboard — shows results from current server session only.
    DILIGENCE: No data persists across restarts. Explicitly noted in UI.
    """
    results = get_all_results(limit=40)
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "results": results,
        "count": result_count(),
    })


@app.get("/limitations", response_class=HTMLResponse)
def limitations(request: Request):
    """Serve LIMITATIONS.md as an HTML page. Transparency about AI failure modes."""
    md_path = os.path.join(os.path.dirname(__file__), "LIMITATIONS.md")
    try:
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "LIMITATIONS.md not found."
    return templates.TemplateResponse("limitations.html", {
        "request": request,
        "content": content,
    })


@app.get("/health")
def health():
    """Health check endpoint for deployment monitoring."""
    return {
        "status": "ok",
        "model": MODEL,
        "session_results": result_count(),
        "delegation": "rubric.py",
        "description": "prompts/",
        "discernment": "validator.py",
        "diligence": "session.py + logger.py",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

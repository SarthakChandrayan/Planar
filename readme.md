# Planar

Planar turns a messy engineering-meeting transcript into a structured,
traceable engineering record: **decisions, requirements, tasks (with
owners and due dates), risks and open questions**, and then an
**implementation plan**. Every item links back to the transcript lines it
came from.

It runs entirely on your machine with a local model through
[Ollama](https://ollama.com). No cloud APIs, no accounts, no database.

## Quick start (Windows)

Prerequisites: Python 3.12, Node 22, Ollama.

```powershell
# 1. The model (2.5 GB). qwen3:4b is the right size for a 16 GB laptop on CPU.
ollama pull qwen3:4b

# 2. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
cd ..

# 3. Frontend
cd frontend
npm install
cd ..

# 4. Config (optional; defaults are fine)
copy .env.example .env

# 5. Run both and open the browser
.\start.ps1
```

Open http://localhost:5173, paste a transcript (try `test_transcript.txt`),
press **Forge**. You can close the tab: the run continues in the background
and resumes when you come back. When it finishes you get the record, the
plan, and a **Download .md** button.

The header shows a warning if Ollama is not running or the configured model
is not installed, with the command that fixes it.

### From the terminal

```powershell
cd backend
.\.venv\Scripts\python scripts\analyze.py ..\test_transcript.txt
.\.venv\Scripts\python scripts\analyze.py ..\test_transcript.txt --score   # + score vs the answer key
```

Prints each stage with its time and token count, and writes
`backend/data/cli/<name>.md` and `.json`.

## How it works

```
transcript ─► number non-blank lines, detect speakers ─► chunk if long
   │
   ▼  for each chunk, four focused passes (same transcript prefix each time)
   1. decisions
   2. requirements
   3. tasks             (owner, due, priority, done-when)
   4. risks + open questions
   │
   ▼  backend, per item
   look up cited lines ─► check they support the claim
   (else search ±3 lines, else anywhere if a line clearly states it)
   ─► drop unsupported ─► merge duplicates ─► assign IDs
   ─► infer links: requirement→decision, task/risk/question→requirement
   │
   ▼
   implementation plan: steps cite REQ/TSK ids; evidence comes from those
   items; any task the model forgot becomes its own step
```

Design choices, and why they matter on a laptop CPU:

| Choice | Why |
|---|---|
| **Model cites line numbers, never quotes** | Output tokens are the slowest part (~4–6 tok/s on CPU). Line numbers are a few tokens; quotes are dozens. Evidence is then looked up exactly. |
| **Output constrained by JSON schema** (Ollama `format`) | The model cannot produce malformed JSON or wrong field names, so a 5-minute generation is never wasted on a parse error. |
| **Four small passes, transcript first** | A 4B model does one narrow job well and five jobs at once badly. Ollama reuses the cached transcript prefix, so passes 2–4 skip re-reading it (measured: 72 s → 2 s). |
| **Passes never see each other's items; links are inferred** | Shown a list of decisions, a 4B model copied it back as "requirements". Links come from shared evidence lines and distinctive wording instead, and only above a threshold, so the graph is never padded. |
| **One-line JSON example per pass** | Small models follow an example's format far better than an instruction; pretty-printed JSON wasted ~30% of output tokens. |
| **`temperature 0` + fixed seed** | Same transcript, same output, so evaluation scores are comparable between runs. |
| **Grounding checks with transcript-derived stopwords** | Words that appear on many lines (the meeting's topic) don't count as evidence. No domain vocabulary is hard-coded. |
| **Owner/due kept only if they appear in the transcript** | The model can't invent an assignee or a deadline. |
| **Chunking with overlap** | Long meetings are split instead of being silently truncated by the context window. |
| **One background worker, runs saved as JSON** | One CPU can only run one model call efficiently. A refresh, a closed tab or a restart doesn't lose finished work. |
| **Failed pass → retry with a note → warning** | One bad section doesn't throw away the rest of the record. |

Item IDs are assigned by the application, never by the model. A
`MeetingAnalysis` is rejected if a relationship points at an ID that is not
in the same record. In the implementation plan the model does cite record
IDs; unknown ones are stripped, and a step left with none is dropped.

"Confidence" on decisions and requirements is evidence strength: how well
the cited transcript lines back the statement, not the model's self-rating.

## Making it faster on a 16 GB laptop

Set these for the **Ollama server** (not Planar), then quit and restart
Ollama from the tray:

```powershell
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

Together they roughly halve the memory used for the context window.

Other levers, in `.env`:

- `OLLAMA_NUM_CTX=8192` uses less RAM and is a little faster. Fine for
  meetings up to ~30 minutes; longer ones get chunked automatically. Keep
  `CHUNK_MAX_TOKENS` about 4000 below `OLLAMA_NUM_CTX`.
- `OLLAMA_KEEP_ALIVE=30m` (default) keeps the model loaded between runs.

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/runs` | Start a run `{transcript, title?, include_plan?}` → 202 |
| `GET` | `/api/runs` | Recent runs (summaries) |
| `GET` | `/api/runs/{id}` | Status, progress, and result when done |
| `POST` | `/api/runs/{id}/cancel` | Cancel (stops at the next token) |
| `DELETE` | `/api/runs/{id}` | Delete a run |
| `GET` | `/api/runs/{id}/report.md` | Markdown report |
| `POST` | `/api/meetings/analyze` | Synchronous analysis (blocks for minutes) |
| `POST` | `/api/meetings/implementation-plan` | Plan from an existing analysis |
| `GET` | `/health`, `/health/ready` | Liveness; model readiness |

Interactive docs at http://localhost:8000/docs. Every response carries an
`X-Request-ID`, and the backend logs one line per request plus per-model-call
timing (`prompt_tokens`, `prompt_s`, `output_tokens`, `output_s`).

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest -m "not integration"           # fast, no model
$env:RUN_OLLAMA_TESTS = "1"; .\.venv\Scripts\python -m pytest tests/integration   # live model
```

```powershell
cd frontend
npm run lint
npm run build
```

CI runs the fast backend tests, lint and the frontend build on every push.

## Scope

V1 is deliberately local-only. Not included: cloud APIs, paid services,
databases, authentication, GitHub integration, speech-to-text, vector
databases, LangChain/LangGraph.

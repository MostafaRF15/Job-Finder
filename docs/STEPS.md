# Job Finder Agent — Build Documentation

This document records each step of building an AI agent that helps find and rank jobs.
Use it as the base for a report, tutorial, or project write-up.

**Project path:** `~/Documents/job-finder-agent`

---

## Step 1 — Project structure

### Goal
Create a clear, maintainable layout so each responsibility lives in its own place.

### Why
An agent mixes configuration, external APIs, scoring logic, and a user interface.
Separating them makes the project easier to explain, test, and extend.

### What we created

| Path | Role |
|------|------|
| `src/job_agent/` | Python package: search, score, CLI agent |
| `data/` | User profile and static config (no secrets) |
| `docs/` | Build documentation (this file) |
| `output/` | Saved search results (JSON) |
| `requirements.txt` | Python dependencies |
| `README.md` | Quick start for users |
| `.env.example` | Template for optional API keys |

### Design choice
**Python 3 + CLI first.** A command-line MVP is fast to build, easy to debug, and can later become a Telegram bot or web app without rewriting the core logic.

### How to set up the environment

```bash
cd ~/Documents/job-finder-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Step 2 — User profile (configuration)

### Goal
Store who you are and what you want in a structured file the agent can read.

### Why
The agent must filter and score jobs against real preferences (skills, location, salary).
A JSON profile is simple, editable, and versionable — better than hardcoding values in Python.

### File
`data/profile.json`

### Important fields

| Field | Meaning |
|-------|---------|
| `titles` | Target job titles |
| `skills` | Your technical skills |
| `preferred_keywords` | Words that boost the score |
| `exclude_keywords` | Jobs to ignore |
| `locations` | Preferred locations / Remote |
| `category` | Remotive category (e.g. `software-dev`) |

### Code module
`src/job_agent/profile.py` — loads and validates the JSON file.

### Action for you
Edit `data/profile.json` with your real skills, titles, and preferences.

---

## Step 3 — Job search tool

### Goal
Fetch **real** job listings from a public API and normalize them into one format.

### Why
The agent must not invent jobs. A tool that returns real URLs and titles is the source of truth.

### Source (MVP)
**Remotive** public API: `https://remotive.com/api/remote-jobs`  
- Free for basic use  
- No API key required  
- Focused on remote roles  

### Code module
`src/job_agent/search.py`

### Normalized job format

```json
{
  "id": "...",
  "title": "...",
  "company": "...",
  "location": "...",
  "url": "...",
  "description": "...",
  "tags": [],
  "source": "remotive"
}
```

### Why normalize?
If you later add Adzuna, Reed, or Greenhouse, each API returns different field names.
Normalization keeps scoring and saving code unchanged.

---

## Step 4 — Match / score engine

### Goal
Rank jobs against the profile with **transparent** scores.

### Why
Pure LLM ranking is opaque and inconsistent. Rule-based scoring is explainable.
The optional LLM only adds a short human-readable note.

### Code module
`src/job_agent/scoring.py`

### Scoring weights (0–100)

| Signal | Weight | Logic |
|--------|--------|-------|
| Skills overlap | 45% | How many of your skills appear in the job text |
| Title alignment | 25% | Job title vs your target titles |
| Preferred keywords | 20% | Extra boost for preferred terms |
| Location | 10% | Remote / preferred regions |

### Exclusions
Jobs containing any `exclude_keywords` are dropped before ranking.

### Output per job
- `score` (number)
- `match_reasons` (list of short explanations)
- `skill_hits` (which skills matched)

---

## Step 5 — CLI agent loop (orchestration)

### Goal
One command that: loads profile → searches → scores → prints top matches → saves JSON.

### Why
This is the “agent”: it orchestrates tools from a user request.

### Code module
`src/job_agent/__main__.py`

### Flow diagram

```text
User query
    ↓
load_profile()
    ↓
search_jobs(query, category)   ← Tool 1 (API)
    ↓
score_jobs(jobs, profile)      ← Tool 2 (rules)
    ↓
explain_matches(...)           ← Tool 3 (optional LLM)
    ↓
print top N + save_results()   ← Tool 4 (storage)
```

### How to run

```bash
cd ~/Documents/job-finder-agent
source .venv/bin/activate
PYTHONPATH=src python -m job_agent "python backend" --limit 10 --no-llm
```

### Useful flags

| Flag | Meaning |
|------|---------|
| `--limit N` | Show top N matches |
| `--fetch N` | Fetch N jobs before scoring |
| `--profile PATH` | Custom profile file |
| `--no-llm` | Skip OpenAI explanations |

### Persistence
Results are saved under `output/jobs_YYYYMMDD_HHMMSS.json`.

---

## Step 6 — Optional LLM explanations

### Goal
If an OpenAI API key is present, add 2 short sentences explaining why a job fits.

### Why
Scoring finds matches; natural language helps you decide faster.
**The agent still works without an LLM.**

### Code module
`src/job_agent/llm.py`

### Setup

```bash
cp .env.example .env
# Edit .env and set:
# OPENAI_API_KEY=sk-...
```

Then run without `--no-llm`:

```bash
PYTHONPATH=src python -m job_agent "python backend" --limit 5
```

---

## First successful test (runtime proof)

Command:

```bash
PYTHONPATH=src python -m job_agent "python backend" --no-llm --limit 5
```

Result summary:
- Fetched jobs from Remotive (`software-dev` category)
- Scored and ranked against `data/profile.json`
- Printed top 5 matches with scores, URLs, and reasons
- Saved JSON under `output/`

This proves the pipeline works end-to-end **without** inventing listings.

---

## What you can document in your report

1. **Problem:** Manual job search is slow and noisy.  
2. **Solution:** An agent that searches an API, scores against a profile, and saves results.  
3. **Architecture:** Profile + Tools (search/score/save) + optional LLM.  
4. **Ethics / limits:** Uses official public API; does not auto-apply; does not scrape LinkedIn.  
5. **Next steps:** More job boards, daily cron alerts, cover-letter drafts, application tracker.

---

## Step 7 — Web page (easy UI)

### Goal
Make the agent usable in the browser with a simple graphic interface.

### Why
A CLI is fine for developers; a web page is easier for daily use (upload + button + cards).

### What we added

| Path | Role |
|------|------|
| `src/job_agent/web.py` | Flask app + `/api/search` |
| `templates/index.html` | Page layout |
| `static/style.css` | Basic visual design |
| `static/app.js` | Form submit + render results |

### How to run

```bash
cd ~/Documents/job-finder-agent
source .venv/bin/activate
PYTHONPATH=src python -m job_agent.web
```

Open `http://127.0.0.1:5000`

---

## Step 8 — Resume upload

### Goal
Let the user upload a CV so the agent detects skills and improves ranking.

### Why
A static `profile.json` is incomplete. The resume contains the real skill set.

### How it works

1. User uploads PDF, DOCX, or TXT  
2. `resume.py` extracts text  
3. Skills/titles are detected with a lexicon (and merged into the profile)  
4. Search + scoring use the enriched profile  

### Code module
`src/job_agent/resume.py`

### Supported formats
- `.pdf` (text-based PDFs)  
- `.docx`  
- `.txt` / `.md`  

Scanned image-only PDFs will not work without OCR (future improvement).

---

## Step 9 — Multi-source search + geography

### Goal
Stop relying on one website. Search several boards and prioritize jobs relevant to the user’s region.

### Why
Remotive alone is remote-only and limited. For someone in **Morocco**, local APIs are rare, so the practical strategy is:
1. Aggregate remote + European boards  
2. Boost jobs that mention Morocco / Europe / Remote / MENA  
3. Let the user pick a region in the UI  

### Sources (MVP)

| Source | Coverage | API key? |
|--------|----------|----------|
| Remotive | Remote worldwide | No |
| Arbeitnow | Europe (+ remote EU) | No |
| RemoteOK | Remote worldwide | No |
| Adzuna | Country boards (FR/DE/GB…) | Optional free keys |

### Honest limit for Morocco
There is no strong free public “Morocco-only” jobs API. Practical approach:
- Prefer **remote** roles you can do from Morocco  
- Add **Europe** boards (Arbeitnow) for relocation / EU-remote roles  
- Optional **Adzuna France** keys if you target FR market  

### Region presets
- `morocco` — Morocco + Remote / Europe (default)  
- `europe` — Europe focus  
- `france` — France (+ nearby remote)  
- `remote` — Remote worldwide  

### Scoring change
Location weight increased to **30%** so geographic relevance affects ranking more.

### Runtime proof (2026-07-13)
- Multi-source fetch works: Remotive + Arbeitnow in parallel  
- Europe region returned mixed sources (`arbeitnow: 5`, `remotive: 3`) with Berlin/Munich roles ranked high  
- Adzuna correctly skipped when keys are missing  

### Optional Adzuna
Create free keys at https://developer.adzuna.com/ and set in `.env`:
`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`

---

## Step 10 — Separate scopes: Maroc / Europe / International

### Goal
Stop mixing Remotive into Moroccan searches. Let the user choose one zone, or see all in priority order.

### Zones

| Choice | Sources |
|--------|---------|
| **Maroc** | Rekrute only |
| **Europe** | Arbeitnow (+ Adzuna if keys) |
| **International** | Remotive + RemoteOK |
| **Tout** | Maroc first → Europe → International |

### UI changes
- No score percentage on cards  
- Results grouped by zone when “Tout” is selected  
- Source badge shows the board name (rekrute / arbeitnow / remotive…)  

### Runtime proof
- `region=morocco` → only `rekrute` (Casablanca / Rabat)  
- `region=europe` → only `arbeitnow`  
- `region=all` → Maroc cards first, then Europe  

---

## Step 11 — Morocco multi-site agent

### Goal
Act as a Morocco job-search agent: check a catalog of trusted Moroccan boards, return structured JSON, newest first.

### Active parsers (reachable from this server)
- Rekrute
- Dreamjob
- Jobrapido Maroc
- MarocAnnonces (category scan)
- Avito Emploi

### Catalog also tracked (blocked / SSL / login / not yet parsed)
Emploi.ma, Bayt, Indeed MA, Jooble MA, ANAPEC, LinkedIn, agencies, etc.  
Each search returns `sources_report` with status: `ok` / `unavailable` / `not_implemented`.

### JSON fields per job
title, company, city, contract_type, salary, experience, skills, description, application_url, source, source_website, publication_date

---

## Suggested next improvements

1. Add more Morocco parsers (Stagiaires, Manpower, Emploi-public) when HTML patterns are stable.  
2. Add Adzuna keys for denser France/Europe results.  
3. Application tracker (`applied` / `interview` / `rejected`).  
4. Daily cron digest.  

# Job Finder Agent

Search and rank remote jobs against your profile — via **web UI** or CLI.
Upload a resume (PDF / DOCX / TXT) so matching uses your real skills.

## Web UI (easiest)

```bash
cd ~/Documents/job-finder-agent
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m job_agent.web
```

Open **http://127.0.0.1:5000**

1. (Optional) upload your resume  
2. Enter keywords or leave blank to use resume skills  
3. Click **Search jobs**

## CLI

```bash
PYTHONPATH=src python -m job_agent "remote python backend" --no-llm
```

## Docs

Step-by-step build notes: `docs/STEPS.md`

## Optional: LLM explanations

Set `OPENAI_API_KEY` in `.env` (see `.env.example`), then tick **AI explanations** in the web UI.
# Job-Finder

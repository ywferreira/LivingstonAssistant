# Livingston Township AI Assistant

RAG-based assistant that answers Livingston, NJ residents' questions from the
Township's own website and PDF forms — with a source link for every answer.

**Pipeline:** Crawler (`livingstonnj.org`, robots.txt-compliant, depth 3) →
Markdown/PDF cache in `data/` → local embeddings (`BAAI/bge-small-en-v1.5`,
free) → ChromaDB (`storage/chroma`) → OpenAI `gpt-4o-mini` chat with mandatory
citations → Streamlit UI. An n8n workflow watches the Township sitemap weekly
and triggers a re-scrape + email alert when it changes.

## Setup

```bash
# 1. Environment (requires uv; installs Python 3.11 automatically)
uv venv --python 3.11
uv pip install -r requirements.txt --python .venv/bin/python

# 2. Configure secrets
cp .env.example .env   # then paste your OPENAI_API_KEY and keep the RESCRAPE_TOKEN

# 3. Crawl the Township site (idempotent; only changed pages are rewritten)
.venv/bin/python crawler.py            # full crawl, depth 3
.venv/bin/python crawler.py --depth 1  # quick shallow test

# 4. Build the knowledge index (re-run whenever data/ changes)
.venv/bin/python ingest.py

# 5. Launch the chat UI
.venv/bin/streamlit run app.py
```

The sidebar's "Personalize" field lets a resident enter their street so
trash/recycling answers prioritize the right schedule (F-05).

## Automated monitoring (F-04)

```bash
# API that n8n calls to trigger a re-scrape
.venv/bin/uvicorn api:app --port 8000

# n8n: an instance already runs on this machine at http://localhost:5678
# (self-hosted-ai-starter-kit). On a machine without one:
#   docker compose --profile n8n up -d
```

In the n8n UI at http://localhost:5678:
**Workflows → Import from file → `n8n/workflow.json`**, then:

1. Open the **Trigger Re-scrape** node and replace `YOUR_RESCRAPE_TOKEN` with
   the value from your `.env`.
2. Open **Email Notification** and attach an SMTP credential
   (host `smtp.gmail.com`, port 465/SSL, user `yvonne.ferreira@gmail.com`,
   password = a [Gmail App Password](https://myaccount.google.com/apppasswords)).
3. **Activate** the workflow. Note: the hash comparison uses n8n static data,
   which only persists for *active* (scheduled) runs — a manual test run
   always reports "first run".

Every Monday 6 AM it hashes `livingstonnj.org/sitemap.xml`; on change it POSTs
`/webhook/rescrape` (crawl → re-embed → git push) and emails an alert.

## Deploying to Streamlit Community Cloud

`data/` and `storage/` are committed, so the app serves the index straight
from the repo — no build step in the cloud.

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), create an app from
   the repo with `app.py` as the entrypoint.
3. In the app's **Secrets**, add: `OPENAI_API_KEY = "sk-..."`.

After that, every re-scrape push automatically redeploys the public app with
fresh Township data. A `Dockerfile` is included for self-hosting
(Render/Fly/Railway) if you outgrow Streamlit Cloud:
`docker compose --profile app up`.

## Answer-accuracy guardrails

The system prompt strictly grounds answers in retrieved documents; when the
documents don't contain an answer the bot replies:
*"I cannot find this information in the official documents; please contact
the Township Clerk at 973-992-5000 Ext. 5400."*
Every assertion must cite its source URL, and the retrieved sources are also
listed under each answer. 👍/👎 feedback appends to `feedback_log.csv`.

## Follow-up ideas (from the PRD, not yet built)

- **F-06 Form Wizard mode** — guide residents through permit prerequisites
  step-by-step instead of only linking the form.
- **F-07 Semantic caching** — cache frequent Q&As to cut latency and API cost.

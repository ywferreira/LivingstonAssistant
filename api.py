"""FastAPI service exposing the re-scrape webhook for the n8n monitor.

Run:
    .venv/bin/uvicorn api:app --port 8000
"""

import json
import os
import subprocess
import sys

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException

from config import PROJECT_DIR

load_dotenv(PROJECT_DIR / ".env")

app = FastAPI(title="Livingston Assistant API")

RESCRAPE_LOG = PROJECT_DIR / "rescrape.log"


def _run_rescrape() -> None:
    python = PROJECT_DIR / ".venv" / "bin" / "python"
    subprocess.run(
        [str(python) if python.exists() else sys.executable, "rescrape.py"],
        cwd=PROJECT_DIR,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/rescrape")
def rescrape(background_tasks: BackgroundTasks, x_token: str = Header(default="")) -> dict:
    expected = os.getenv("RESCRAPE_TOKEN")
    if not expected or x_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Token header")
    background_tasks.add_task(_run_rescrape)
    return {"status": "rescrape_started"}


@app.get("/webhook/rescrape/status")
def rescrape_status(x_token: str = Header(default="")) -> dict:
    expected = os.getenv("RESCRAPE_TOKEN")
    if not expected or x_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Token header")
    if not RESCRAPE_LOG.exists():
        return {"status": "never_run"}
    return json.loads(RESCRAPE_LOG.read_text())

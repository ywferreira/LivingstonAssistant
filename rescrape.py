"""Incremental re-scrape: crawl -> re-ingest if changed -> git commit & push.

Called by api.py when the n8n monitor detects a Township site change, or run
manually. A push to GitHub triggers Streamlit Community Cloud to redeploy
with the fresh index.

Usage:
    .venv/bin/python rescrape.py [--depth N] [--no-push]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

from config import CRAWL_DEPTH, PROJECT_DIR

PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"
LOG_PATH = PROJECT_DIR / "rescrape.log"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=CRAWL_DEPTH)
    parser.add_argument("--no-push", action="store_true", help="Skip git commit/push")
    args = parser.parse_args()

    python = str(PYTHON) if PYTHON.exists() else sys.executable
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    crawl = run([python, "crawler.py", "--depth", str(args.depth)])
    changed: list[str] = []
    for line in crawl.stdout.splitlines():
        if line.startswith("CHANGED_JSON:"):
            changed = json.loads(line.removeprefix("CHANGED_JSON:"))
    if crawl.returncode != 0:
        summary = {"started": started, "status": "crawl_failed", "detail": crawl.stderr[-2000:]}
        print(json.dumps(summary))
        LOG_PATH.write_text(json.dumps(summary, indent=2))
        sys.exit(1)

    if not changed:
        summary = {"started": started, "status": "no_changes", "changed": []}
        print(json.dumps(summary))
        LOG_PATH.write_text(json.dumps(summary, indent=2))
        return

    ingest = run([python, "ingest.py"])
    if ingest.returncode != 0:
        summary = {"started": started, "status": "ingest_failed", "detail": ingest.stderr[-2000:]}
        print(json.dumps(summary))
        LOG_PATH.write_text(json.dumps(summary, indent=2))
        sys.exit(1)

    pushed = False
    if not args.no_push:
        run(["git", "add", "data", "storage"])
        commit = run(
            ["git", "commit", "-m", f"Re-scrape: {len(changed)} page(s) changed ({started})"]
        )
        if commit.returncode == 0:
            push = run(["git", "push"])
            pushed = push.returncode == 0

    summary = {
        "started": started,
        "status": "updated",
        "changed": changed,
        "pushed": pushed,
    }
    print(json.dumps(summary))
    LOG_PATH.write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

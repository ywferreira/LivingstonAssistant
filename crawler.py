"""Recursive crawler for livingstonnj.org (F-01, F-02 acquisition side).

Breadth-first crawl of the Township site, honoring robots.txt, limited by
depth and a same-domain filter. HTML pages are reduced to their main content
and saved as Markdown in data/pages/; linked PDFs are downloaded to
data/pdfs/. Every fetched item is recorded in data/manifest.json with a
content hash so re-runs only rewrite what actually changed.

Usage:
    python crawler.py                      # full crawl, depth 3
    python crawler.py --depth 1            # shallow test crawl
    python crawler.py --seed URL [URL ..]  # fetch only the given pages/PDFs
    python crawler.py --force              # rewrite files even if unchanged
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urldefrag, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from config import (
    BASE_URL,
    CRAWL_DEPTH,
    MANIFEST_PATH,
    PAGES_DIR,
    PDFS_DIR,
    REQUEST_DELAY_SECONDS,
    USER_AGENT,
)

MAX_PAGES = 500  # safety valve against runaway crawls ("data bloat" risk)
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".css", ".js",
    ".zip", ".doc", ".docx", ".xls", ".xlsx", ".mp3", ".mp4", ".pptx",
}
# CivicPlus URL patterns that are navigation chrome / infinite spaces,
# not resident-facing content.
SKIP_PATTERNS = re.compile(
    r"/(calendar|search|rss|facilities/facility|mycivic|alertcenter|"
    r"gallery|slideshow|translate|login|logout)\b|[?&](month|year|dt|cid)=",
    re.IGNORECASE,
)

DOMAIN = urlparse(BASE_URL).netloc.lower().removeprefix("www.")


def normalize(url: str) -> str:
    """Canonical URL form. CivicPlus/IIS paths are case-insensitive, the bare
    domain redirects to www, http redirects to https, and empty query params
    (?bidId=) are decorative — normalize all of it so aliases dedupe."""
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    scheme = "https" if parsed.scheme == "http" else parsed.scheme
    netloc = parsed.netloc.lower()
    if netloc == DOMAIN:
        netloc = f"www.{DOMAIN}"
    path = (parsed.path.rstrip("/") or "/").lower()
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if v]
    query = f"?{urlencode(kept)}" if kept else ""
    return f"{scheme}://{netloc}{path}{query}"


def in_domain(url: str) -> bool:
    return urlparse(url).netloc.lower().removeprefix("www.") == DOMAIN


def slugify(url: str) -> str:
    path = urlparse(url).path.strip("/") or "home"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return slug[:120]


def load_robots(client: httpx.Client) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = client.get(f"{BASE_URL}/robots.txt")
        rp.parse(resp.text.splitlines())
    except httpx.HTTPError:
        print("WARNING: could not fetch robots.txt; crawling conservatively.")
        rp.parse(["User-agent: *", "Disallow: /admin"])
    return rp


def extract_main_content(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript", "iframe"]):
        tag.decompose()
    # CivicPlus keeps page content in #moduleContent; fall back gracefully.
    return (
        soup.find(id="moduleContent")
        or soup.find("main")
        or soup.find(id="content")
        or soup.body
        or soup
    )


def html_to_markdown(html: str, url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else url
    title = re.sub(r"\s*\|\s*Livingston.*$", "", title).strip() or url
    main = extract_main_content(soup)
    md = markdownify(str(main), heading_style="ATX", strip=["img"])
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    header = f"# {title}\n\nSource: {url}\n\n"
    return header + md, title


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def crawl(seeds: list[str], depth_limit: int, force: bool) -> dict:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    stats = {"pages": 0, "pdfs": 0, "changed": [], "skipped_robots": 0, "errors": 0}
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque((normalize(u), 0) for u in seeds)

    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        robots = load_robots(client)

        while queue and (stats["pages"] + stats["pdfs"]) < MAX_PAGES:
            url, depth = queue.popleft()
            if url in seen or not in_domain(url):
                continue
            seen.add(url)

            if SKIP_PATTERNS.search(url):
                continue
            if not robots.can_fetch(USER_AGENT, url) or not robots.can_fetch("*", url):
                stats["skipped_robots"] += 1
                print(f"  robots.txt disallows: {url}")
                continue

            ext = Path(urlparse(url).path).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue

            time.sleep(REQUEST_DELAY_SECONDS)
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                stats["errors"] += 1
                print(f"  ERROR {url}: {exc}")
                continue

            # CivicPlus serves the same page under alias URLs (/385 redirects
            # to /385/Leaf-Collection); key everything by the final URL.
            final_url = normalize(str(resp.url))
            if final_url != url:
                if final_url in seen or not in_domain(final_url):
                    continue
                seen.add(final_url)
                url = final_url

            content_type = resp.headers.get("content-type", "").lower()
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")

            if "pdf" in content_type or ext == ".pdf":
                digest = hashlib.sha256(resp.content).hexdigest()
                entry = manifest.get(url)
                fname = f"{slugify(url)}.pdf"
                if force or not entry or entry["sha256"] != digest:
                    (PDFS_DIR / fname).write_bytes(resp.content)
                    stats["changed"].append(url)
                manifest[url] = {
                    "file": f"pdfs/{fname}",
                    "sha256": digest,
                    "last_crawled": now,
                    "title": Path(urlparse(url).path).name,
                    "type": "pdf",
                }
                stats["pdfs"] += 1
                print(f"  [pdf ] {url}")
                continue

            if "html" not in content_type:
                continue

            markdown, title = html_to_markdown(resp.text, url)
            digest = hashlib.sha256(markdown.encode()).hexdigest()
            entry = manifest.get(url)
            fname = f"{slugify(url)}.md"
            if force or not entry or entry["sha256"] != digest:
                (PAGES_DIR / fname).write_text(markdown)
                stats["changed"].append(url)
            manifest[url] = {
                "file": f"pages/{fname}",
                "sha256": digest,
                "last_crawled": now,
                "title": title,
                "type": "page",
            }
            stats["pages"] += 1
            print(f"  [page] depth={depth} {title[:60]} — {url}")

            if depth < depth_limit:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    nxt = normalize(urljoin(url, a["href"]))
                    if nxt not in seen and in_domain(nxt):
                        queue.append((nxt, depth + 1))

    save_manifest(manifest)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl livingstonnj.org into data/")
    parser.add_argument("--depth", type=int, default=CRAWL_DEPTH)
    parser.add_argument("--seed", nargs="+", help="Fetch only these URLs (no link following)")
    parser.add_argument("--force", action="store_true", help="Rewrite files even if unchanged")
    args = parser.parse_args()

    if args.seed:
        seeds, depth = args.seed, 0
    else:
        seeds, depth = [BASE_URL + "/"], args.depth

    print(f"Crawling {len(seeds)} seed(s), depth limit {depth} ...")
    stats = crawl(seeds, depth, args.force)
    print(
        f"\nDone: {stats['pages']} pages, {stats['pdfs']} PDFs "
        f"({len(stats['changed'])} new/changed, {stats['skipped_robots']} blocked by "
        f"robots.txt, {stats['errors']} errors)."
    )
    # Machine-readable line for rescrape.py / n8n email summaries.
    print("CHANGED_JSON:" + json.dumps(stats["changed"]))
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Shared constants for the Livingston Township Assistant."""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# --- Crawler -----------------------------------------------------------
BASE_URL = "https://www.livingstonnj.org"
CRAWL_DEPTH = 3
REQUEST_DELAY_SECONDS = 0.5
USER_AGENT = "LivingstonAssistantBot/1.0 (+resident RAG assistant; respects robots.txt)"

# --- Data / index ------------------------------------------------------
DATA_DIR = PROJECT_DIR / "data"
PAGES_DIR = DATA_DIR / "pages"
PDFS_DIR = DATA_DIR / "pdfs"
MANIFEST_PATH = DATA_DIR / "manifest.json"
CHROMA_DIR = PROJECT_DIR / "storage" / "chroma"
COLLECTION_NAME = "livingston_township"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

# --- Township facts used in prompts ------------------------------------
CLERK_PHONE = "973-992-5000 Ext. 5400"
TOWN_HALL_ADDRESS = "357 S. Livingston Avenue, Livingston, NJ 07039"

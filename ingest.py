"""Ingestion pipeline: data/ (crawled pages + PDFs) -> ChromaDB.

Loads the Markdown pages and PDF forms produced by crawler.py, attaches each
document's source URL and title from data/manifest.json (so the app can cite
real Township links), chunks into 512-token segments, embeds locally with
the HuggingFace model, and persists vectors to storage/chroma.

Safe to re-run: the collection is rebuilt from scratch each time.

Usage:
    .venv/bin/python ingest.py
"""

import json
import sys
from pathlib import Path

from config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DATA_DIR,
    MANIFEST_PATH,
)


def build_metadata_lookup() -> dict[str, dict]:
    """Map absolute file path -> {source_url, title} from the crawl manifest."""
    if not MANIFEST_PATH.exists():
        sys.exit("No data/manifest.json found. Run crawler.py first.")
    manifest = json.loads(MANIFEST_PATH.read_text())
    return {
        str((DATA_DIR / entry["file"]).resolve()): {
            "source_url": url,
            "doc_title": entry["title"],
        }
        for url, entry in manifest.items()
    }


def main() -> None:
    lookup = build_metadata_lookup()
    files = [Path(p) for p in lookup if Path(p).exists()]
    if not files:
        sys.exit("Manifest has no existing files. Run crawler.py first.")

    import chromadb
    from llama_index.core import StorageContext, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.readers import SimpleDirectoryReader
    from llama_index.readers.file import PyMuPDFReader
    from llama_index.vector_stores.chroma import ChromaVectorStore

    from llm_config import get_embed_model

    print(f"Loading {len(files)} file(s) from {DATA_DIR} ...")
    reader = SimpleDirectoryReader(
        input_files=[str(p) for p in files],
        file_extractor={".pdf": PyMuPDFReader()},
    )
    documents = reader.load_data(show_progress=True)

    for doc in documents:
        file_path = doc.metadata.get("file_path")
        meta = lookup.get(str(Path(file_path).resolve())) if file_path else None
        if meta:
            doc.metadata.update(meta)

    print(f"Parsed {len(documents)} document section(s).")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Rebuild the collection so re-ingesting never leaves stale chunks behind.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    storage_context = StorageContext.from_defaults(
        vector_store=ChromaVectorStore(chroma_collection=collection)
    )

    print("Chunking, embedding locally, and writing to ChromaDB ...")
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        embed_model=get_embed_model(),
        transformations=[SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)],
        show_progress=True,
    )

    print(f"Done. {collection.count()} chunks stored in {CHROMA_DIR} (collection '{COLLECTION_NAME}').")


if __name__ == "__main__":
    main()

"""LLM/embedding adapter — the single swap point for models.

Answers come from OpenAI's gpt-4o-mini; embeddings run locally (free) with a
small HuggingFace model, so re-indexing after a re-scrape costs nothing.
"""

LLM_MODEL = "gpt-4o-mini"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def get_llm():
    from llama_index.llms.openai import OpenAI

    return OpenAI(model=LLM_MODEL, max_tokens=1024, temperature=0.1)


def get_embed_model():
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=EMBED_MODEL)

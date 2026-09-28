import asyncio
import json
import os
import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from dotenv import load_dotenv
load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "nagar_schema"
EMBED_MODEL = "bge-m3"
VECTOR_SIZE = 1024
BATCH_SIZE = 8


async def embed_batch(texts: list[str]) -> list[list[float]]:
    url = f"{OLLAMA_URL}/api/embed"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json={"model": EMBED_MODEL, "input": texts})
        resp.raise_for_status()
        return resp.json()["embeddings"]


async def ensure_collection(client: AsyncQdrantClient):
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if COLLECTION_NAME not in names:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"  Created collection '{COLLECTION_NAME}'")
    else:
        print(f"  Collection '{COLLECTION_NAME}' already exists")


async def run_index() -> int:
    schema_path = os.path.join(os.path.dirname(__file__), "schema_docs.json")
    with open(schema_path, "r", encoding="utf-8") as f:
        docs = json.load(f)

    print(f"Loaded {len(docs)} schema chunks from schema_docs.json")

    client = AsyncQdrantClient(url=QDRANT_URL)
    await ensure_collection(client)

    # Embed in batches
    all_vectors = []
    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        texts = [doc["text"] for doc in batch]
        vectors = await embed_batch(texts)
        all_vectors.extend(vectors)
        print(f"  Embedded {min(i + BATCH_SIZE, len(docs))}/{len(docs)} chunks")

    # Build points and upload
    points = [
        PointStruct(
            id=doc["id"],
            vector=all_vectors[idx],
            payload={
                "text": doc["text"],
                "department": doc["department"],
                "table": doc["table"],
            },
        )
        for idx, doc in enumerate(docs)
    ]

    # qdrant-client 1.19: bulk upload methods are sync (return a parallel task handle);
    # call inside a worker thread so the FastAPI event loop is not blocked.
    await asyncio.to_thread(
        lambda: client.upload_points(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )
    )
    print(f"Indexed {len(points)}/{len(docs)} chunks into Qdrant collection '{COLLECTION_NAME}'")
    return len(points)


if __name__ == "__main__":
    asyncio.run(run_index())

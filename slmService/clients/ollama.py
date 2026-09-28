import os
import httpx
from fastapi import HTTPException
from dotenv import load_dotenv
load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "bge-m3"
GENERATE_MODEL = "qwen3:1.7b"


async def embed(text: str) -> list[float]:
    url = f"{OLLAMA_URL}/api/embed"
    payload = {"model": EMBED_MODEL, "input": text}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama is unreachable. Ensure it is running at " + OLLAMA_URL)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Embedding failed: {str(exc)}")


async def generate_sql(system_prompt: str, user_question: str) -> str:
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": GENERATE_MODEL,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 512},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama is unreachable. Ensure it is running at " + OLLAMA_URL)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SQL generation failed: {str(exc)}")


async def check_health() -> str:
    url = f"{OLLAMA_URL}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return "up"
    except Exception:
        return "down"


if __name__ == "__main__":
    import asyncio

    async def smoke_test():
        print("Testing embed...")
        vec = await embed("How many complaints are open in Zone 5?")
        print(f"  Embedding dimensions: {len(vec)}")
        print(f"  First 5 values: {vec[:5]}")

        print("Testing generate_sql...")
        system = "You are a PostgreSQL expert. Return only a SQL SELECT query. No explanation."
        sql = await generate_sql(system, "How many open complaints are in zone 5?")
        print(f"  Generated SQL: {sql}")

    asyncio.run(smoke_test())

import asyncio
import os
import time
import httpx
from dotenv import load_dotenv

# Load backend/.env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path, override=True)

API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")

MODELS = [
    "moonshotai/kimi-k3",
    "z-ai/glm-5.3",
    "z-ai/glm-5.3-flash",
    "deepseek-ai/deepseek-v4.1-flash",
]

PROMPT = "You are an expert data analyst. In 2 sentences, explain the difference between customer churn rate and retention rate."

async def test_model(client: httpx.AsyncClient, model: str) -> dict:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.2,
        "max_tokens": 150,
    }

    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] 🚀 [START] Querying '{model}' in parallel (timeout: 600s)...", flush=True)

    try:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=600.0,
        )
        elapsed = time.time() - t0

        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            content = ""
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content") or msg.get("reasoning") or ""
            print(f"[{time.strftime('%H:%M:%S')}] ✅ [FINISH] '{model}' completed in {elapsed:.2f}s! ({len(content)} chars)", flush=True)
            return {
                "model": model,
                "status": "SUCCESS",
                "status_code": 200,
                "time_seconds": round(elapsed, 2),
                "response": content.strip()[:200],
            }
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ [ERROR] '{model}' returned HTTP {response.status_code} after {elapsed:.2f}s: {response.text[:120]}", flush=True)
            return {
                "model": model,
                "status": f"HTTP {response.status_code}",
                "status_code": response.status_code,
                "time_seconds": round(elapsed, 2),
                "error": response.text[:200],
            }
    except httpx.ReadTimeout:
        elapsed = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] ⏱️ [TIMEOUT] '{model}' timed out after {elapsed:.2f}s (10-minute limit exceeded).", flush=True)
        return {
            "model": model,
            "status": "TIMEOUT",
            "time_seconds": round(elapsed, 2),
            "error": "ReadTimeout after 600s",
        }
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ [EXCEPTION] '{model}' failed after {elapsed:.2f}s: {type(exc).__name__}: {exc}", flush=True)
        return {
            "model": model,
            "status": f"EXCEPTION: {type(exc).__name__}",
            "time_seconds": round(elapsed, 2),
            "error": str(exc),
        }

async def main():
    print("=" * 70)
    print("NVIDIA NIM Parallel Latency & Response Benchmark")
    print(f"Models to test: {MODELS}")
    print(f"Max wait time: 600s (10 minutes) per model")
    print(f"API Key: {API_KEY[:6]}...{API_KEY[-4:] if len(API_KEY) > 10 else '***'}")
    print("=" * 70, flush=True)

    # Use connection limits appropriate for parallel requests
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [test_model(client, model) for model in MODELS]
        results = await asyncio.gather(*tasks)

    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY RESULTS")
    print("=" * 70)
    for r in results:
        status_sym = "✅" if r["status"] == "SUCCESS" else "❌"
        print(f"{status_sym} Model: {r['model']:<35} | Time: {r['time_seconds']:>7.2f}s | Status: {r['status']}")
        if "response" in r:
            print(f"   Sample: \"{r['response'][:100]}...\"")
        elif "error" in r:
            print(f"   Error:  {r['error']}")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())

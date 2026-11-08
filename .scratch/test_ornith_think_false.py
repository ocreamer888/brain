import json
import time

import requests

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "ornith-35b-eval:latest"

ENTITY_PROMPT = """Extract the named entities from the text below.
Include: technologies, libraries, tools, products, people, organizations, file paths, project names.
Exclude: generic words, common verbs, filler.

Return ONLY a JSON object: {{"entities": ["Entity1", "Entity2"]}}
If none: {{"entities": []}}

Text:
{text}"""

TITLE_SUMMARY_PROMPT = """You are summarizing code edits to a file for a memory system.

File: /Users/Shared/Code/quantathon-lifehub/src/qaoa_runner.py
Changes (2):
- def run_qaoa(graph): -> def run_qaoa(graph, p=1, shots=1000):
-  -> result = backend.run(circuit, shots=shots)

Return ONLY valid JSON:
{{
  "title": "concise description of what was done and why (max 80 chars)",
  "summary": "1-2 sentence explanation of the change purpose and impact (max 300 chars)"
}}

Rules:
- Title should describe the PURPOSE, not just "edited X"
- Summary should explain WHY this change matters
- Both must be single-line strings, no newlines"""

REAL_CONTENT_SAMPLE = """GUPPY EXAMPLE 03 -- Repeat Until Success (examples/03_repeat_until_success.py).

## Demonstrates
for-loop RUS; functional h(qubit()); toffoli; measure-branch pattern (Nielsen & Chuang Fig 4.17).
Used by LifeHub for QAOA mixer layer gate decomposition."""


def call(prompt: str, think_false: bool) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    if think_false:
        payload["think"] = False
    t0 = time.time()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=(5, 60))
        elapsed = time.time() - t0
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        thinking = data.get("message", {}).get("thinking", "")
        return {
            "elapsed": round(elapsed, 2),
            "content": content,
            "content_len": len(content),
            "thinking_len": len(thinking),
            "parses": _try_parse(content),
        }
    except Exception as e:
        return {"error": str(e), "elapsed": round(time.time() - t0, 2)}


def _try_parse(content: str) -> bool:
    try:
        json.loads(content.strip())
        return True
    except Exception:
        return False


print(f"=== Testing {MODEL} with think:false ===\n")

print("--- entity extraction prompt, 3 runs ---")
for i in range(3):
    prompt = ENTITY_PROMPT.format(text=REAL_CONTENT_SAMPLE)
    r = call(prompt, think_false=True)
    print(f"run {i+1}: {r}")

print("\n--- title/summary JSON prompt, 3 runs ---")
for i in range(3):
    r = call(TITLE_SUMMARY_PROMPT, think_false=True)
    print(f"run {i+1}: {r}")

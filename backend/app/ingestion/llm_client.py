import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

API_URL = "https://api.nicrron.ai/v1/chat/completions"


def call_nicrron(messages):
    api_key = os.getenv("NICRRON_API_KEY")
    model = os.getenv("NICRRON_MODEL", "openai/gpt-4.1-mini")

    if not api_key:
        raise RuntimeError("NICRRON_API_KEY is missing")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=45) as client:
        for attempt in range(2):
            response = client.post(
                API_URL,
                headers=headers,
                json=payload,
            )

            if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                print(f"Nicrron returned HTTP " f"{response.status_code}. Retrying...")
                time.sleep(2)
                continue

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Nicrron HTTP {response.status_code} " f"using model {model}"
                )

            data = response.json()

            content = data["choices"][0]["message"]["content"]

            if not isinstance(content, str) or not content.strip():
                raise ValueError("Nicrron returned empty text")

            return content

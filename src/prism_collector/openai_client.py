from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class OpenAIConfigError(RuntimeError):
    pass


def openai_json(
    *,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIConfigError("OPENAI_API_KEY must be set to run AI processing")

    selected_model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    payload = {
        "model": selected_model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "schema": schema["schema"],
                "strict": True,
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed: HTTP {exc.code}: {details}") from exc

    return _extract_json(body)


def _extract_json(response: dict[str, Any]) -> dict[str, Any]:
    if "output_text" in response:
        return json.loads(response["output_text"])

    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return json.loads(content.get("text", "{}"))

    raise RuntimeError("OpenAI response did not contain output_text JSON")

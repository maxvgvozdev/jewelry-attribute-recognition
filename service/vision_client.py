"""
Vision analysis client for a remote Spark machine / remote model server.

Run the vision model on a separate host and point this client at it
using environment variables:

  VISION_API_URL  - http://<spark-host>:<port>
  VISION_API_KEY  - optional bearer token
  VISION_MODEL    - model identifier on the remote server
  VISION_PROVIDER - "openai" | "ollama" | "generic"

Provider behavior
-----------------
- openai / openai-style / vllm:
    POST {VISION_API_URL}/v1/chat/completions
    multipart image not required; image is sent as base64 data URI
- ollama:
    POST {VISION_API_URL}/api/chat (fallback: /api/generate)
    image sent as base64 inside the JSON payload
- generic:
    POST {VISION_API_URL}/analyze
    multipart/form-data with image + prompt + optional model
"""

import os
import json
import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("jewelry.vision")

VISION_API_URL = os.getenv("VISION_API_URL", "http://localhost:11434").rstrip("/")
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "llava")
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "ollama").lower()


def _headers() -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if VISION_API_KEY:
        h["Authorization"] = f"Bearer {VISION_API_KEY}"
    return h


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _mime_type(image_path: str) -> str:
    mt, _ = mimetypes.guess_type(image_path)
    return mt or "image/jpeg"


def health_check(timeout: int = 10) -> Dict[str, Any]:
    """Best-effort check against the remote vision service."""
    try:
        if VISION_PROVIDER in ("openai", "openai-style", "vllm"):
            url = f"{VISION_API_URL}/v1/models"
            resp = requests.get(url, headers=_headers(), timeout=timeout)
        elif VISION_PROVIDER in ("ollama",):
            url = f"{VISION_API_URL}/api/tags"
            resp = requests.get(url, headers=_headers(), timeout=timeout)
        else:
            url = VISION_API_URL
            resp = requests.get(url, headers=_headers(), timeout=timeout)

        resp.raise_for_status()
        return {"ok": True, "url": url, "status_code": resp.status_code}
    except Exception as exc:
        return {"ok": False, "url": VISION_API_URL, "error": str(exc)}


def analyze_image_openai_style(image_path: str, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    model = model or VISION_MODEL
    b64 = _encode_image(image_path)
    mime = _mime_type(image_path)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
    }

    url = f"{VISION_API_URL}/v1/chat/completions"
    logger.info("Calling remote OpenAI-style vision endpoint: %s model=%s", url, model)
    resp = requests.post(url, headers=_headers(), json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return {
        "provider": "openai-style",
        "model": model,
        "image": image_path,
        "prompt": prompt,
        "analysis": content,
        "raw": data,
    }


def analyze_image_ollama_style(image_path: str, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    model = model or VISION_MODEL
    b64 = _encode_image(image_path)

    payload_chat = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024},
    }

    url_chat = f"{VISION_API_URL}/api/chat"
    logger.info("Calling remote Ollama-style chat: %s model=%s", url_chat, model)
    try:
        resp = requests.post(url_chat, headers=_headers(), json=payload_chat, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return {
            "provider": "ollama",
            "model": model,
            "image": image_path,
            "prompt": prompt,
            "analysis": content,
            "raw": data,
        }
    except requests.HTTPError as exc:
        logger.warning("Remote Ollama /api/chat failed (%s), falling back to /api/generate", exc)
        payload_gen = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1024},
        }
        url_gen = f"{VISION_API_URL}/api/generate"
        resp = requests.post(url_gen, headers=_headers(), json=payload_gen, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("response", "")
        return {
            "provider": "ollama-generate",
            "model": model,
            "image": image_path,
            "prompt": prompt,
            "analysis": content,
            "raw": data,
        }


def analyze_image_generic(image_path: str, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    model = model or VISION_MODEL
    url = f"{VISION_API_URL}/analyze"

    with open(image_path, "rb") as f:
        files = {"image": (Path(image_path).name, f, _mime_type(image_path))}
        data = {"prompt": prompt, "model": model}
        logger.info("Calling remote generic vision endpoint: %s model=%s", url, model)
        resp = requests.post(url, files=files, data=data, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return {
            "provider": "generic",
            "model": model,
            "image": image_path,
            "prompt": prompt,
            "analysis": data.get("analysis") or data.get("text") or json.dumps(data),
            "raw": data,
        }


def analyze_image(image_path: str, question: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Unified entry point. Dispatches to the configured remote provider backend."""
    provider = VISION_PROVIDER
    if provider in ("openai", "openai-style", "vllm"):
        return analyze_image_openai_style(image_path, question, model)
    if provider in ("ollama",):
        return analyze_image_ollama_style(image_path, question, model)
    if provider in ("generic",):
        return analyze_image_generic(image_path, question, model)

    logger.warning("Unknown VISION_PROVIDER=%s, defaulting to ollama", provider)
    return analyze_image_ollama_style(image_path, question, model)

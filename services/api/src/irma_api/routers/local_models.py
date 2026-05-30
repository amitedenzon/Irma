"""Local model discovery — scans a folder for GGUF files and queries Ollama."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/local-models", tags=["local-models"])

# ---------------------------------------------------------------------------
# Proficiency heuristics — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------
_PROFICIENCY_RULES: list[tuple[list[str], str]] = [
    # Vision
    (["llava", "vision", "moondream", "bakllava", "minicpm-v", "qwen-vl", "cogvlm", "idefics"], "vision"),
    # Coding
    (["deepseek-coder", "codellama", "starcoder", "codegemma", "codestral", "devstral",
      "code-", "-code", "coder"], "coding"),
    # Embeddings
    (["embed", "nomic-embed", "mxbai-embed", "all-minilm", "bge-"], "embeddings"),
    # Math / reasoning
    (["math", "mathstral", "deepseek-r1", "o1", "qwq"], "math"),
]

_QUANT_RE = re.compile(
    r"(q\d+_[a-z0-9]+|fp16|fp32|bf16|f16|f32|int4|int8|gguf)",
    re.IGNORECASE,
)


def _proficiency(name: str) -> list[str]:
    lower = name.lower()
    tags: list[str] = []
    for keywords, label in _PROFICIENCY_RULES:
        if any(kw in lower for kw in keywords):
            tags.append(label)
    if not tags:
        tags.append("chat")
    return tags


def _quantization(name: str) -> str | None:
    m = _QUANT_RE.search(name)
    return m.group(0).upper() if m else None


def _size_label(size_bytes: int) -> str:
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    mb = size_bytes / (1024 ** 2)
    return f"{mb:.0f} MB"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class LocalModel(BaseModel):
    name: str
    display_name: str
    source: str          # "ollama" | "file"
    size_bytes: int
    size_label: str
    proficiency: list[str]
    quantization: str | None
    path: str | None     # only for file-sourced models


class LocalModelsResponse(BaseModel):
    models: list[LocalModel]
    ollama_reachable: bool
    scan_path: str | None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.get("", response_model=LocalModelsResponse)
async def list_local_models(
    request: Request,
    path: str | None = None,
) -> LocalModelsResponse:
    from irma_api.config import Settings
    settings: Settings = request.app.state.settings
    base_url = settings.ollama_base_url.rstrip("/")

    models: list[LocalModel] = []
    ollama_reachable = False

    # --- Ollama API ---
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            ollama_reachable = True
            for m in data.get("models", []):
                raw_name: str = m.get("name", "")
                size_bytes: int = m.get("size", 0)
                models.append(LocalModel(
                    name=raw_name,
                    display_name=raw_name,
                    source="ollama",
                    size_bytes=size_bytes,
                    size_label=_size_label(size_bytes),
                    proficiency=_proficiency(raw_name),
                    quantization=_quantization(raw_name),
                    path=None,
                ))
    except Exception as exc:
        logger.info("local_models.ollama_unreachable", error=str(exc))

    # --- File scan ---
    scan_path: str | None = None
    if path:
        scan_path = path
        folder = Path(path)
        if folder.is_dir():
            for gguf in sorted(folder.rglob("*.gguf")):
                size_bytes = gguf.stat().st_size
                name = gguf.stem
                # Skip if already in Ollama list by rough name match
                existing = {m.name.lower().split(":")[0] for m in models}
                if name.lower() not in existing:
                    models.append(LocalModel(
                        name=name,
                        display_name=name,
                        source="file",
                        size_bytes=size_bytes,
                        size_label=_size_label(size_bytes),
                        proficiency=_proficiency(name),
                        quantization=_quantization(name),
                        path=str(gguf),
                    ))

    return LocalModelsResponse(
        models=models,
        ollama_reachable=ollama_reachable,
        scan_path=scan_path,
    )

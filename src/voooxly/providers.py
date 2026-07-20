"""Catálogo de proveedores de LLM.

Un preset NO es código: es un base_url y un modelo por defecto ya rellenos.
Todos los que hablan el protocolo OpenAI (kind="openai") los atiende el mismo
Refiner._openai() que ya existía, así que añadir un proveedor a esta tabla no
requiere tocar refine.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    default_model: str
    needs_key: bool
    kind: str  # "ollama" | "claude" | "openai"


PROVIDERS: dict[str, Provider] = {
    "ollama": Provider(
        key="ollama",
        label="Ollama (local)",
        base_url="http://localhost:11434",
        default_model="llama3.2",
        needs_key=False,
        kind="ollama",
    ),
    "claude": Provider(
        key="claude",
        label="Claude",
        base_url="",  # lo gestiona el SDK de anthropic
        default_model="claude-sonnet-5",
        needs_key=True,
        kind="claude",
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        needs_key=True,
        kind="openai",
    ),
    "groq": Provider(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        needs_key=True,
        kind="openai",
    ),
    "openrouter": Provider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        needs_key=True,
        kind="openai",
    ),
    "custom": Provider(
        key="custom",
        label="Custom (OpenAI-compatible)",
        base_url="",
        default_model="",
        needs_key=True,
        kind="openai",
    ),
}


def get(key: str) -> Provider | None:
    return PROVIDERS.get(key)

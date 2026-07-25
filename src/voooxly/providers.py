"""Catalog of LLM providers.

A preset is NOT code: it's a base_url and a default model already filled in.
All the ones speaking the OpenAI protocol (kind="openai") are served by the
same Refiner._openai() that already existed, so adding a provider to this
table doesn't require touching refine.py.

Curated, short list on purpose (MVP): the most common ones and the best
performers at cleaning dictation, plus Ollama as the only local option. The
order is the menu's (insertion order): cloud first, Ollama last because most
people don't run models on their own machine, the free one first of all.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    name: str  # the bare name: "Groq". It's what's read in the menu title.
    base_url: str
    default_model: str
    needs_key: bool
    kind: str  # "ollama" | "claude" | "openai"
    note: str = ""  # "free" → shown in the menu; the rest, empty
    # Curated list of models EXCELLENT at cleaning dictation, from best
    # default to alternatives (the first one IS default_model). On connecting,
    # the app lets you pick one (v1.4 feedback: "internally select a specific
    # model when an option is chosen, like cloud"). Empty for Ollama: its
    # models are asked of the user's server (list_ollama_models), not
    # presumed.
    models: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Text of the submenu ROW: the name plus its note, if it has one.

        Derived instead of stored because the parent's title ("AI engine —
        Groq") needs the bare name: with a literal label "Groq — free" it
        came out as "AI engine — Groq — free", with two em dashes in a row.
        """
        return f"{self.name} — {self.note}" if self.note else self.name


PROVIDERS: dict[str, Provider] = {
    # Groq first: it's the only free one in the list and the fastest route to
    # try the refinement without pulling out a card. Behind three paid ones
    # nobody found it.
    "groq": Provider(
        key="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        needs_key=True,
        kind="openai",
        note="free",
        # llama-3.3-70b cleans dictation more than well enough; the 8b is for
        # whoever wants minimum latency at some cost in quality.
        models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
    ),
    "claude": Provider(
        key="claude",
        name="Claude",
        base_url="",  # managed by the anthropic SDK
        default_model="claude-sonnet-5",
        needs_key=True,
        kind="claude",
        # sonnet-5 is the balance; haiku-4-5 the cheap/fast route and
        # opus-4-8 for whoever wants the best writing whatever it costs.
        models=("claude-sonnet-5", "claude-haiku-4-5", "claude-opus-4-8"),
    ),
    "openai": Provider(
        key="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        # The current family is GPT-5.6 (verified on developers.openai.com,
        # jul-2026): luna is the high-volume tier — the natural fit for
        # cleaning dictations —, terra the balanced one. gpt-5.4-mini is still
        # in the API, and gpt-4.1-mini stays as a known non-reasoning option.
        default_model="gpt-5.6-luna",
        needs_key=True,
        kind="openai",
        models=("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.4-mini", "gpt-4.1-mini"),
    ),
    "gemini": Provider(
        key="gemini",
        name="Google Gemini",
        # Gemini's OpenAI-compatible endpoint: same path as openai/groq.
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        # Gemini 3 up front (Eduardo's request; IDs verified on
        # ai.google.dev, jul-2026): 3.6-flash is the house's fast GA and
        # 3.5-flash-lite the cheap tier. 2.5-flash stays as the known net.
        default_model="gemini-3.6-flash",
        needs_key=True,
        kind="openai",
        models=("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"),
    ),
    # Ollama (local) last: the option for whoever runs models on their own
    # machine. No default model (fixing one presumes which one is installed):
    # THEIR Ollama is asked (list_ollama_models) and they pick their own.
    "ollama": Provider(
        key="ollama",
        name="Ollama (local)",
        base_url="http://localhost:11434",
        default_model="",
        needs_key=False,
        kind="ollama",
    ),
}


def get(key: str) -> Provider | None:
    return PROVIDERS.get(key)

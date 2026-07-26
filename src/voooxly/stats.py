"""Usage stats: how many dictations, how many words, how much typing saved.

Cumulative counters in ~/.voooxly/stats.json (no rotation: it's 3 numbers).
The "typing saved" compares speaking (~150 real wpm dictating) with typing
(~40 wpm of an average typist): words/40 − words/150 minutes. Best-effort:
broken stats never get in the way of dictation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("voooxly.stats")

STATS_FILE = Path.home() / ".voooxly" / "stats.json"

TYPING_WPM = 40
SPEAKING_WPM = 150


def load(path: Path | None = None) -> dict:
    path = path or STATS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "dictations": int(data.get("dictations", 0)),
            "words": int(data.get("words", 0)),
            "seconds_recorded": float(data.get("seconds_recorded", 0.0)),
            # New keys with a default: a stats.json from an older version
            # still reads in full instead of being lost.
            "tokens": int(data.get("tokens", 0)),
            "token_provider": str(data.get("token_provider", "")),
        }
    except Exception:
        return {
            "dictations": 0,
            "words": 0,
            "seconds_recorded": 0.0,
            "tokens": 0,
            "token_provider": "",
        }


def bump(words: int, seconds: float, path: Path | None = None) -> None:
    path = path or STATS_FILE
    try:
        s = load(path)
        s["dictations"] += 1
        s["words"] += max(0, int(words))
        s["seconds_recorded"] += max(0.0, float(seconds))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug("Couldn't update stats: %s", e)


def bump_tokens(tokens: int, provider: str, path: Path | None = None) -> None:
    """Accumulate the tokens spent on the remote LLM.

    It lets anyone on a free tier (Groq) see how much they have used without
    leaving the app. Ollama never reaches here: it is local and burns no quota,
    and a counter stuck at 0 next to "free tier" only confuses.
    """
    path = path or STATS_FILE
    try:
        s = load(path)
        s["tokens"] += max(0, int(tokens))
        s["token_provider"] = provider or s["token_provider"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug("Couldn't update tokens: %s", e)


def summary(path: Path | None = None) -> str:
    s = load(path)
    if not s["dictations"]:
        return "No dictations yet — hold the key and speak."
    saved_min = s["words"] * (1 / TYPING_WPM - 1 / SPEAKING_WPM)
    saved = f"~{saved_min / 60:.1f} h" if saved_min >= 60 else f"~{round(saved_min)} min"
    out = (
        f"{s['dictations']} dictations · {s['words']:,} words · "
        f"{saved} of typing saved"
    )
    if s["tokens"]:
        cifra = _formato_tokens(s["tokens"])
        quien = f" · {s['token_provider']}" if s["token_provider"] else ""
        out += f"\n~{cifra} tokens{quien}"
    return out


def _formato_tokens(tokens: int) -> str:
    """"k"/"M" by magnitude, without rounding overflowing the scale.

    Rounding in "k" near a million (e.g. 999,500 → 999.5k → "1000k" with
    .0f) produces a scale that doesn't exist: "1000k" should be "1M". That's
    why the promotion to M is decided AFTER rounding, not before.
    """
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1000:
        miles = round(tokens / 1000)
        if miles >= 1000:  # rounding pushed it into the million scale
            return f"{tokens / 1_000_000:.1f}M"
        return f"{miles}k"
    return f"{tokens}"

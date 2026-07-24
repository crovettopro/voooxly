# Contributing to Voooxly

## Dev setup

The venv must live outside iCloud-synced folders (`~/Desktop`, `~/Documents`) —
iCloud eviction hangs cold imports (pyobjc, anthropic). See `scripts/install.sh:1-8`
for the rationale; the export below is the same convention.

```bash
git clone https://github.com/crovettopro/voooxly && cd voooxly
export UV_PROJECT_ENVIRONMENT=~/.voooxly/venv   # venv fuera de iCloud (evita cuelgues de imports)
uv sync
brew install whisper-cpp
uv run python -m voooxly
```

## Tests

```bash
UV_PROJECT_ENVIRONMENT=~/.voooxly/venv uv run pytest tests/ -q
```

(550+ tests. First run is slow — cold pyobjc imports.)

## Ground rules

- Logic lives in pure modules (no AppKit imports) so it's testable; windows only paint.
- Best-effort everywhere: nothing may break dictation.
- UI strings in English (they're the i18n keys); Spanish goes in `i18n.py`.
- One feature per PR, tests included.

# Contributing to Voooxly

## Dev setup

```bash
git clone https://github.com/crovettopro/voooxly && cd voooxly
uv sync
brew install whisper-cpp
uv run python -m voooxly
```

## Tests

```bash
uv run pytest tests/ -q
```

(~535 tests. First run is slow — cold pyobjc imports.)

## Ground rules

- Logic lives in pure modules (no AppKit imports) so it's testable; windows only paint.
- Best-effort everywhere: nothing may break dictation.
- UI strings in English (they're the i18n keys); Spanish goes in `i18n.py`.
- One feature per PR, tests included.

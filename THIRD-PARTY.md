# Third-party components

Voooxly is MIT-licensed (see [LICENSE](LICENSE)). The shipped `.app` bundles or
depends on the following third-party work.

## Bundled inside the app

| Component | License | Notes |
|---|---|---|
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (`whisper-server`, `libwhisper`, `libggml*`) | MIT | Vendored from Homebrew by `scripts/bundle-whisper.sh`. Not committed to this repo — it is fetched and embedded at build time. |
| [Whisper large-v3-turbo](https://huggingface.co/ggerganov/whisper.cpp) model weights | MIT (OpenAI Whisper) | Downloaded to `~/.voooxly/models/` on first run, never redistributed by us. |

## Python dependencies

Declared in `pyproject.toml` and pinned in `uv.lock`. The runtime set is
`sounddevice`, `numpy`, `webrtcvad`, `pynput`, `rumps`, `pyobjc`, `pyyaml`,
`requests` and `anthropic` — all permissively licensed (MIT / BSD / Apache-2.0).
Run `uv pip list` for the exact resolved versions in your environment.

## Optional AI backends

Voooxly can route text cleanup through Ollama, the Anthropic API or any
OpenAI-compatible endpoint. None of these are bundled; each is used through its
own public API under its own terms. Audio never leaves your Mac in any
configuration — only transcribed text, and only if you enable a cloud backend.

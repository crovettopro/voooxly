# Voooxly

**Free, open-source dictation for Mac with a local AI brain.**
Hold a key, speak, release — polished text appears where your cursor is.
Your voice never leaves your Mac.

<!-- ![Demo](docs/img/demo.gif) — record before launch -->

## Features

- **9 writing modes** — organize your rambling, draft replies from a spoken brief, shape prompts for AIs, take Markdown notes, translate ES↔EN, or keep it verbatim. The LLM cleans up what you said; it never invents.
- **100% local by design** — whisper.cpp on Apple Silicon. Optional AI polish via a local Ollama, or bring your own Claude/OpenAI/Gemini key. Audio is never uploaded, in any configuration.
- **Learns your words by itself** — fix a word in the pasted text and Voooxly picks up the right spelling on your next dictation. No word lists to maintain. It reads only the field it just pasted into, once, on-device — no screenshots, no tracking. Off switch in Settings.
- **Fast** — sub-second transcription for typical sentences on Apple Silicon (p50 ~0.6 s in our benchmark; reproduce it with `scripts/bench_latency.sh`).
- **Everything else you'd expect** — live preview, hands-free latch, personal dictionary with "Correct last dictation", history search, and updates that install themselves.

## Install

Download the [latest DMG](https://github.com/crovettopro/voooxly/releases/latest/download/Voooxly.dmg), open, drag to Applications. Updates install themselves.

First launch asks for two permissions: **Microphone** (to hear you) and **Accessibility** (to paste where your cursor is). Both are required.

## En español

Voooxly habla tu idioma: interfaz, guía y onboarding en español automáticos, modos de
traducción ES↔EN y un diccionario que aprende tus nombres y marcas.
[Más en voooxly.com](https://voooxly.com).

## Privacy

Transcription runs on-device (whisper.cpp). Audio is never uploaded. The optional
AI polish step uses the backend YOU configure — local Ollama by default; with a
cloud backend, only transcribed text is sent, never your voice.

No account. No subscription. No telemetry.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labeled.

## License

MIT © Eduardo Crovetto

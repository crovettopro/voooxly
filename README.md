# Voooxly

**Free, open-source dictation for Mac with a local AI brain.**
Hold a key, speak, release — polished text appears where your cursor is.
Your voice never leaves your Mac.

<!-- ![Demo](docs/img/demo.gif) — grabar antes del martes -->

## Why Voooxly

|  | Voooxly | Handy | VoiceInk | superwhisper | Wispr Flow |
|---|---|---|---|---|---|
| Price | **Free** | Free | $25–49 | $8.49/mo | $12–15/mo |
| Open source | ✅ MIT | ✅ MIT | GPL (paid binary) | ❌ | ❌ |
| 100% local option | ✅ | ✅ | ✅ | ✅ | ❌ cloud-only |
| AI cleanup & modes | ✅ 9 modes | ⚠️ basic | ✅ | ✅ (paid) | ✅ |
| Learns your words | ✅ | ❌ | ✅ | ⚠️ manual | ✅ |
| Auto-updates | ✅ | ✅ | ✅ | ✅ | ✅ |

*(Honest table — each of these is a great tool. Pick what fits.)*

## Features

- **9 writing modes** — organize your rambling, draft replies, prompt AIs, translate ES↔EN, verbatim, and more. The LLM cleans up what you said; it never invents.
- **100% local by design** — whisper.cpp on Apple Silicon. Optional AI polish via local Ollama, or bring your own Claude/OpenAI/Gemini key.
- **Learns your words** — correct a dictation once, Voooxly spells it right forever.
- **Live preview, hands-free latch, personal dictionary, history search, Spanish UI.**

## Install

Download the [latest DMG](https://github.com/crovettopro/voooxly/releases/latest/download/Voooxly.dmg), open, drag to Applications. Updates install themselves.

## En español

Voooxly habla tu idioma: interfaz en español automática, modos de traducción ES↔EN
y un diccionario que aprende tus nombres y marcas. [Más en voooxly.com/es](https://voooxly.com).

## Privacy

Transcription runs on-device (whisper.cpp). Audio is never uploaded. The optional
AI polish step uses the backend YOU configure — local Ollama by default.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labeled.

## License

MIT © Eduardo Crovetto

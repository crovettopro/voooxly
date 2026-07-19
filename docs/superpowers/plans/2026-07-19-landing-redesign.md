# Landing Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolucionar `web/index.html` al nivel de ejecución de wisprflow.ai manteniendo identidad actual (papel/tinta, ámbar/teal) y añadiendo banner free, comparativa y FAQ.

**Architecture:** Un único fichero `web/index.html` con CSS y JS inline (sin build). Cada task es una pasada coherente sobre ese fichero + commit. Verificación visual al final con Chrome + deploy a Vercel.

**Tech Stack:** HTML/CSS/JS vanilla. Deploy: `cd web && vercel --prod`.

## Global Constraints (del spec)

- Peso total < 45 KB. Cero dependencias externas (sin webfonts/CDN).
- Contraste AA; sin scroll horizontal del body ≥320px.
- Animaciones solo bajo `prefers-reduced-motion: no-preference`.
- Links de descarga: `https://github.com/crovettopro/voxly/releases/latest/download/Voxly-1.0.0.dmg`.
- Paleta existente se conserva: `--paper #EDF0EE`, `--ink #0F1716`, `--signal #D08A22`, `--resolved #0C6E5F`.

---

### Task 1: Escala tipográfica y ritmo

**Files:** Modify: `web/index.html` (bloque `<style>`, variables y reglas base)

- [ ] Añadir a `:root`: `--step-hero: clamp(2.5rem, 1.2rem + 5.5vw, 6rem); --step-h2: clamp(1.75rem, 1.1rem + 2.6vw, 3.25rem); --step-lede: clamp(1.05rem, 0.95rem + 0.5vw, 1.3rem); --section-gap: clamp(6rem, 4rem + 8vw, 10rem);`
- [ ] `h1` del hero → `font-size: var(--step-hero); letter-spacing: -0.03em; line-height: 1.02`. `h2` de secciones → `var(--step-h2); letter-spacing: -0.02em`. Ledes → `var(--step-lede)`.
- [ ] Secciones: `padding-block: calc(var(--section-gap) / 2)` (sustituye paddings fijos actuales).
- [ ] Verificar en Chrome (file:// o `python3 -m http.server`) a 1440 y 375: jerarquía clara, sin overflow.
- [ ] Commit: `Landing: escala tipográfica fluida y ritmo de secciones`

### Task 2: Hero — impacto y confianza

**Files:** Modify: `web/index.html` (hero + fondo)

- [ ] Fondo del hero: `background: radial-gradient(120% 90% at 15% 0%, #F6E8D8 0%, transparent 55%), radial-gradient(110% 80% at 90% 10%, #DCEBE6 0%, transparent 50%), var(--paper);` + grano: pseudo-elemento con SVG `feTurbulence` inline como data-URI, `opacity: .035`.
- [ ] Sustituir la línea `.req` por trust-line con separadores: `Free · Signed & notarized by Apple · Apple Silicon · macOS 13+`.
- [ ] CTA principal: sombra suave en reposo, `transform: translateY(-1px)` + sombra mayor en hover, `transition: .18s ease`.
- [ ] Commit: `Landing: hero con gradiente/grano y trust line`

### Task 3: Sistema de motion

**Files:** Modify: `web/index.html` (CSS + `<script>`)

- [ ] CSS: `.reveal { opacity: 0; transform: translateY(18px); } .reveal.visible { opacity: 1; transform: none; transition: opacity .6s ease, transform .6s ease; }` — todo dentro de `@media (prefers-reduced-motion: no-preference)`. Fuera de la media query, `.reveal` es visible (fallback sin JS/con reduced motion).
- [ ] JS: `IntersectionObserver` (threshold .15) que añade `.visible` y hace `unobserve`. Aplicar `.reveal` a cada `<section>` hijo directo y cards.
- [ ] Demo: revisar timings de la animación existente — easing `cubic-bezier(.22,.9,.24,1)` en transiciones del texto "wrote", cursor parpadeante al escribir.
- [ ] Verificar: con reduced-motion activado (Chrome DevTools rendering) no hay animaciones y todo es visible.
- [ ] Commit: `Landing: reveals al scroll y pulido de la demo`

### Task 4: Banner "Free & open source"

**Files:** Modify: `web/index.html` (nueva sección tras el hero)

- [ ] Franja fina full-width, fondo `--ink`, texto `--paper`:
  **"Free. No account. No subscription."** + secundario "Open source — read every line on GitHub" (link al repo). Layout: flex, wrap en móvil.
- [ ] Commit: `Landing: banner free & open source`

### Task 5: Comparativa vs dictado cloud

**Files:** Modify: `web/index.html` (nueva sección antes del FAQ)

- [ ] Título: **"Local by design — not a promise, an architecture"**. Tabla (contenedor `overflow-x: auto`):

| | Voxly | Cloud dictation apps |
|---|---|---|
| Your voice | Never leaves your Mac | Uploaded to their servers |
| Price | Free | ~$12–15/month |
| Works offline | Yes | No |
| Usage limits | None | Word/minute caps |
| Source code | Open on GitHub | Closed |

- [ ] Filas Voxly con check teal (`--resolved`), columna cloud en `--fg-muted`.
- [ ] Commit: `Landing: comparativa local vs cloud`

### Task 6: FAQ

**Files:** Modify: `web/index.html` (nueva sección antes del CTA final)

- [ ] Acordeón nativo `<details>/<summary>` (7 items), summary con `::marker` oculto y chevron CSS rotando en `[open]`:
  1. **Is it really free?** — Yes. No account, no trial, no subscription. You bring your own AI for text cleanup (a local Ollama or an API key) or use none at all — raw transcription works out of the box.
  2. **Which Macs does it run on?** — Apple Silicon (M1 or later) on macOS 13+. Intel isn't supported.
  3. **Where does my voice go?** — Nowhere. Audio is transcribed on your Mac by a local Whisper model. If you connect a cloud AI for cleanup, only the *text* is sent — never audio.
  4. **Do I need Ollama or an API key?** — No. Without any AI, Voxly pastes the raw transcription (already well punctuated). With one, it also tidies grammar and formatting per mode.
  5. **Does it work offline?** — Yes — transcription is fully local. Only optional cloud cleanup and update checks need a connection.
  6. **What languages does it support?** — Whisper large-v3-turbo: ~99 languages, strongest in English and Spanish. It follows your system language automatically.
  7. **How do updates work?** — The app checks a version file at launch and shows "Update available" in the menu. Download the new DMG, replace the app, done.
- [ ] Nav: añadir enlace "FAQ" → `#faq`.
- [ ] Commit: `Landing: FAQ con acordeón nativo`

### Task 7: Pulido de secciones existentes + CTA final

**Files:** Modify: `web/index.html` (privacy, steps, modos, close, footer)

- [ ] Privacy/steps/modos: aplicar nueva escala, aire entre cards (`gap` ampliado), hover con `translateY(-2px)` + sombra en cards.
- [ ] Steps (Hold/Speak/Let go): numerar 01/02/03 en `--mono` color `--signal`.
- [ ] CTA final: fondo `--bg` (oscuro existente) con el mismo tratamiento de gradiente sutil invertido; botón grande.
- [ ] Commit: `Landing: pulido de secciones y CTA final`

### Task 8: Verificación y deploy

- [ ] Peso: `wc -c web/index.html` < 46080 bytes.
- [ ] Chrome: screenshots a 1440/768/375 — sin overflow horizontal, jerarquía correcta, demo funcionando.
- [ ] Reduced motion: sin animaciones, contenido visible.
- [ ] Todos los links descarga → URL correcta (grep).
- [ ] `cd web && vercel --prod` + verificar https://usevoxly.vercel.app (título, FAQ presente, appcast.json intacto).
- [ ] Commit final + push.

## Self-Review

- Cobertura del spec: tipografía (T1), gradiente/grano (T2), motion (T3), banner (T4), comparativa (T5), FAQ (T6), pulido+CTA (T7), verificación/deploy (T8). Nav FAQ en T6. ✓
- Sin placeholders: copy completo de FAQ/tabla/banner incluido. ✓
- Consistencia: clases y variables definidas en T1-T3 se usan en T4-T7. ✓

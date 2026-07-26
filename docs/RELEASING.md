# Releasing a version of Voooxly

How to go from the code to a DMG anyone can download and install.

Almost everything is automated by `scripts/release.sh`. What cannot be automated
is the initial Apple account setup: **four steps, one time only**.

---

## Setup (one time only)

### 1. Create the Developer ID Application certificate

It is what lets macOS open the app on a Mac that is not yours. Requires the
Apple Developer Program ($99/year, the same one you already use for the App
Store apps).

1. Open **Xcode → Settings → Accounts**, select your account and click **Manage
   Certificates…**
2. Click **+** at the bottom left and choose **Developer ID Application**.
3. Xcode creates it and installs it in the keychain.

> Manual alternative: at developer.apple.com → Certificates, IDs & Profiles →
> Certificates → **+** → Developer ID Application. Download the `.cer` and
> double-click it to install it.

Check that it is there:

```bash
security find-identity -v -p codesigning | grep "Developer ID Application"
```

A line with `Developer ID Application: Eduardo Crovetto (TH7LG6UP8H)` should appear.

### 2. Create an app-specific password

Notarization does not accept your regular Apple ID password.

1. Go to [appleid.apple.com](https://appleid.apple.com) → **Sign-In and Security**
   → **App-Specific Passwords**.
2. Generate a new one (name it "voooxly-notarization") and **copy it**: it is only
   shown once.

### 3. Store the notarization profile

This leaves the credentials in the keychain so the script does not ask for them every time:

```bash
xcrun notarytool store-credentials voooxly \
  --apple-id tu-email@ejemplo.com \
  --team-id TH7LG6UP8H \
  --password <la-contraseña-específica-del-paso-2>
```

Verify:

```bash
xcrun notarytool history --keychain-profile voooxly
```

### 4. Install dmgbuild in the release venv

`release.sh` uses it for the DMG window layout and the volume icon. The venv
is made with uv and does not ship `pip`, so it is installed like this:

```bash
uv pip install --python ~/.voooxly/venv/bin/python 'dmgbuild>=1.6'
```

Verify:

```bash
~/.voooxly/venv/bin/dmgbuild --help
```

### 5. Create the GitHub repository for the downloads

The DMGs are served from GitHub Releases (free and with no traffic limit):

```bash
gh repo create voooxly --public --source=. --remote=origin
```

---

## Releasing a version

### 1. Bump the version number

In `Voooxly.spec`, both fields at once:

```python
"CFBundleVersion": "1.0.0",
"CFBundleShortVersionString": "1.0.0",
```

### 2. Dry run (optional but recommended)

Validates the whole mechanics —build, signing of the 145 internal binaries,
DMG— without spending a notarization:

```bash
./scripts/release.sh --dry-run
```

### 3. The real release

```bash
./scripts/release.sh
```

It does, in order: build → copy outside iCloud → sign from the inside out with
hardened runtime → notarize the app (a few minutes) → staple → create the DMG →
sign and notarize the DMG → verify with `spctl` exactly what Gatekeeper will see.

The result ends up in `~/.voooxly/release/Voooxly-<version>.dmg`.

### 4. Upload the DMG to GitHub Releases

```bash
gh release create v1.0.0 ~/.voooxly/release/Voooxly-1.0.0.dmg \
  --title "Voooxly 1.0.0" --notes "Qué ha cambiado…"
```

### 5. Update the appcast and deploy the web

In `web/appcast.json`, set the new version and the DMG URL. Already-installed
apps check it on startup and show "Update to 1.0.0 →" in the menu.

Write **both** `notes` and `notes_es`: they are the only user-facing strings the
app does not own, so they cannot go through `i18n.t()` — `updates._notes()`
picks by UI language and falls back to English when `notes_es` is missing.
Leaving it out shows a Spanish user an English pop-up in an otherwise Spanish
interface.

Refresh `updates.WHATS_NEW` too (and its `i18n.ES` entry) **in the same commit
that bumps the version**: that is the pop-up shown right after installing, and
a test now fails if it still describes the behaviour the release retired.

Y despliega con el script del repo `voooxly-web`, no con `vercel --prod` a mano:

```bash
cd ../voooxly-web && ./deploy.sh
```

`deploy.sh` **se niega a desplegar si el appcast anuncia una versión que GitHub
todavía no ha publicado** — que es la forma de romper esto: la web diría "1.10.0
disponible" y tanto el botón como el actualizador acabarían en un 404. También
avisa si tu DMG local no es esa versión, y comprueba después que
`voooxly.com/download` acaba de verdad en la release correcta. `--dry-run` hace
las comprobaciones sin desplegar.

Los 28 MB los sirve **GitHub Releases**, no Vercel: no tiene límite de tráfico y
su `download_count` es la métrica del lanzamiento. `voooxly.com/download` y
`/Voooxly.dmg` son redirects a `releases/latest/download/Voooxly.dmg`, así que
apuntan solos a la última versión y no hay que tocarlos en cada release.

> **Gate for the release that ships the post-paste learning window.** The site
> copy for it is already written (the "Learns your words by itself" card and the
> "What does it read from my screen, and when?" FAQ) and **must not go live
> before that build does** — until then it would describe reading that the
> installed app does not do. Deploy them in the same pass as the DMG, and make
> the release notes say what changed about reading, not just that learning got
> faster. The `notes` string for that appcast bump:
>
> ```
> Corrections are now learned on the spot: fix a word right after pasting and
> Voooxly saves the spelling within seconds, instead of waiting for your next
> dictation. To do that it reads the field it pasted into for a few seconds
> (on-device, never password fields, nothing stored but the correction) — and
> Settings › "Learn from my corrections" still turns it off completely.
> ```

---

## Why the project is set up this way

**Why not the Mac App Store.** Voooxly needs a global hotkey and to paste text
into third-party apps; the App Store's mandatory sandbox forbids both. That is
why serious dictation apps for macOS ship outside the store, this one included.

**Why signing happens outside iCloud.** The repo lives in `~/Desktop`, which
iCloud syncs, and iCloud keeps re-injecting extended attributes. Signing there
fails with `resource fork, Finder information, or similar detritus not allowed`.
The script copies the bundle to `~/.voooxly/release/` before touching it.

**Why the internal binaries are signed one by one.** The `libggml-*` are loaded
via `dlopen` at runtime, so they need their own signature: without it,
notarization rejects the package. Signing goes from the inside out because
signing the bundle invalidates any signature added inside it afterwards.

**Why Apple Silicon only.** The `whisper-server` vendored in `vendor/` is
arm64. Supporting Intel would require building a universal binary.

---

## If something fails

| Symptom | Cause and fix |
|---|---|
| `no hay certificado 'Developer ID Application'` | Setup step 1 is missing |
| `no existe el perfil de notarización 'voooxly'` | Step 3 is missing |
| `resource fork ... detritus not allowed` | Something is being signed inside iCloud; the script already avoids this, check you have not changed `WORK` |
| Notarization rejected | `xcrun notarytool log <submission-id> --keychain-profile voooxly` gives the exact reason, usually a binary that is unsigned or lacks hardened runtime |
| The app opens but the hotkey does nothing | Accessibility not granted; the onboarding walks through it. Reinstalling changes the signature and macOS revokes the permission |

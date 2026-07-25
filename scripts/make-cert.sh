#!/bin/bash
# Creates a self-signed "Voooxly Dev" code-signing certificate and installs it
# trusted in the keychain. With it, the app signature is stable across rebuilds and
# macOS does NOT revoke the TCC permissions (Accessibility/Microphone/etc.) each build.
#
# Requires interaction: macOS shows a dialog asking for the user's password
# when trusting the certificate (one time only).
set -euo pipefail

NAME="Voooxly Dev"
DIR="$HOME/.voooxly/cert"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

# does the identity already exist? then there is nothing to do
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$NAME"; then
  echo "OK: la identidad '$NAME' ya existe en el llavero."
  exit 0
fi

mkdir -p "$DIR"
cd "$DIR"

cat > openssl.cnf <<'EOF'
[req]
distinguished_name = dn
x509_extensions = codesign_ext
prompt = no
[dn]
CN = Voooxly Dev
[codesign_ext]
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
basicConstraints = critical,CA:FALSE
EOF

echo "→ Generando clave y certificado (10 años)…"
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 3650 -nodes -config openssl.cnf

# We import key and cert as separate PEMs: the p12 fails depending on which
# openssl generated it ("MAC verification failed" — ciphers the keychain
# does not understand). With PEMs the keychain pairs them into the identity itself.
echo "→ Importando clave privada al llavero (autorizada para codesign)…"
security import key.pem -k "$KEYCHAIN" -T /usr/bin/codesign

echo "→ Importando certificado…"
security import cert.pem -k "$KEYCHAIN"

echo "→ Confiando el certificado para firma de código (saldrá un diálogo de contraseña)…"
security add-trusted-cert -p codeSign -k "$KEYCHAIN" cert.pem

chmod 600 key.pem
echo "→ Verificando identidad…"
security find-identity -v -p codesigning | grep "$NAME" && echo "LISTO: firma con: codesign -s '$NAME' …"

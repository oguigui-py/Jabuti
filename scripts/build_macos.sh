#!/usr/bin/env bash
# Gera dist/Jabuti.app, confere com o autoteste e empacota em dist/Jabuti-macOS.zip e .dmg.
#
#   scripts/build_macos.sh                 # usa o "python" do ambiente ativo
#   PYTHON=/caminho/python scripts/build_macos.sh
#
# O ambiente precisa de requirements.txt + pyinstaller (ver requirements-dev.txt). Use um
# ambiente só com o requirements.txt: com o PySide6 completo instalado, o app fica maior.
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
VERSION="$("$PY" -c 'import jabuti; print(jabuti.__version__)')"

echo "== Jabuti $VERSION: PyInstaller"
"$PY" -m PyInstaller --noconfirm --clean packaging/jabuti.spec

echo "== autoteste do executável"
CHECK="$(mktemp -d)"
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" dist/Jabuti.app/Contents/MacOS/Jabuti --autoteste "$CHECK"
codesign --verify --deep dist/Jabuti.app

echo "== Jabuti-macOS.zip (ditto preserva o bundle: links, permissões, assinatura)"
rm -f dist/Jabuti-macOS.zip dist/Jabuti-macOS.dmg
ditto -c -k --keepParent dist/Jabuti.app dist/Jabuti-macOS.zip

echo "== Jabuti-macOS.dmg"
STAGE="$(mktemp -d)"
ditto dist/Jabuti.app "$STAGE/Jabuti.app"
ln -s /Applications "$STAGE/Aplicativos"
cp packaging/LEIAME_INSTALACAO.txt "$STAGE/"
if ! hdiutil create -volname "Jabuti $VERSION" -srcfolder "$STAGE" -ov -format UDZO dist/Jabuti-macOS.dmg; then
  echo "hdiutil falhou: .dmg não gerado (o .zip basta)"
fi
rm -rf "$STAGE" "$CHECK"

du -sh dist/Jabuti.app dist/Jabuti-macOS.zip dist/Jabuti-macOS.dmg 2>/dev/null || true

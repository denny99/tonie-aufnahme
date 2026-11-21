#!/bin/bash
# Baut alle Pakete einer Version nach dist/ und prüft, dass das AppImage startet. Aufruf: build-all.sh 1.2.3
set -euo pipefail
cd "$(dirname "$0")/.."
V=${1:?Version fehlt}
rm -rf dist
./packaging/build-deb.sh "$V"
./packaging/build-appimage.sh "$V"
(cd build/appimage/AppDir && QT_QPA_PLATFORM=offscreen timeout 8 ./AppRun) || [ $? -eq 124 ]
dpkg-deb -I dist/*.deb
(cd dist && sha256sum * > SHA256SUMS && cat SHA256SUMS)

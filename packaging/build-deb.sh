#!/bin/bash
# Baut dist/tonie-aufnahme_<version>_all.deb (Debian 13, Ubuntu 25.04 und neuer).
set -euo pipefail
cd "$(dirname "$0")/.."
V=${1:-$(cat VERSION)}
B=build/deb; rm -rf $B; mkdir -p $B/DEBIAN $B/usr/bin $B/usr/share/tonie-aufnahme $B/usr/share/applications \
  $B/usr/share/icons/hicolor/512x512/apps $B/usr/share/doc/tonie-aufnahme dist
cp -r tonie_aufnahme/app.py tonie_aufnahme/recorder.py tonie_aufnahme/bilder $B/usr/share/tonie-aufnahme/
install -m 755 tonie-aufnahme $B/usr/bin/tonie-aufnahme
cp tonie_aufnahme/bilder/app-icon.png $B/usr/share/icons/hicolor/512x512/apps/tonie-aufnahme.png
sed -e 's#@APP@/app.py#/usr/share/tonie-aufnahme/app.py#' -e 's#^Icon=.*#Icon=tonie-aufnahme#' \
  tonie-aufnahme.desktop > $B/usr/share/applications/tonie-aufnahme.desktop
cp LICENSE $B/usr/share/doc/tonie-aufnahme/copyright
cat > $B/DEBIAN/control <<EOT
Package: tonie-aufnahme
Version: $V
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, ffmpeg, playerctl, pulseaudio-utils
Maintainer: denny99 <noreply@github.com>
Homepage: https://github.com/denny99/tonie-aufnahme
Description: Spotify-Playlist für den Kreativ-Tonie aufnehmen
 Nimmt eine Spotify-Playlist in Echtzeit auf und schneidet sie in einzelne
 MP3-Dateien, fertig zum Hochladen auf einen Kreativ-Tonie.
EOT
find $B -type d -exec chmod 755 {} +
dpkg-deb --root-owner-group --build $B dist/tonie-aufnahme_${V}_all.deb

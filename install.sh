#!/bin/bash
# Installiert die Tonie-Aufnahme für den angemeldeten Benutzer (ohne Administratorrechte).
set -euo pipefail
cd "$(dirname "$0")"
APP="$HOME/.local/share/tonie-aufnahme"
fehlt=()
for p in python3 parec pactl playerctl ffmpeg ffprobe; do command -v $p >/dev/null || fehlt+=($p); done
python3 -c "import PySide6" 2>/dev/null || fehlt+=(PySide6)
if [ ${#fehlt[@]} -gt 0 ]; then
  echo "Es fehlt noch: ${fehlt[*]}"
  echo "Arch/CachyOS:   sudo pacman -S playerctl ffmpeg libpulse pyside6"
  echo "Ubuntu/Debian:  sudo apt install playerctl ffmpeg pulseaudio-utils python3-pyside6.qtwidgets"
  echo "Fedora:         sudo dnf install playerctl ffmpeg pulseaudio-utils python3-pyside6"
  exit 1
fi
mkdir -p "$APP" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp -r tonie_aufnahme/. "$APP/"
install -m 755 tonie-aufnahme "$HOME/.local/bin/tonie-aufnahme"
sed "s#@APP@#$APP#g" tonie-aufnahme.desktop > "$HOME/.local/share/applications/tonie-aufnahme.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Fertig. Die Tonie-Aufnahme steht jetzt im Startmenü."

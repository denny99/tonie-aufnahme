#!/bin/bash
# Baut dist/Tonie-Aufnahme-<version>-x86_64.AppImage: Python 3.12 und PySide6 sind drin,
# ffmpeg, playerctl und parec/pactl kommen vom System.
set -euo pipefail
cd "$(dirname "$0")/.."
V=${1:-0.0.0-dev}
W=build/appimage; rm -rf $W; mkdir -p $W dist
URL=$(curl -fsSL https://api.github.com/repos/niess/python-appimage/releases/tags/python3.12 \
  | python3 -c 'import json,sys; print(next(a["browser_download_url"] for a in json.load(sys.stdin)["assets"] if a["name"].endswith("cp312-cp312-manylinux_2_28_x86_64.AppImage")))')
curl -fsSL -o $W/python.AppImage "$URL"; chmod +x $W/python.AppImage
(cd $W && ./python.AppImage --appimage-extract >/dev/null && mv squashfs-root AppDir)
A=$W/AppDir
PY=$(ls $A/opt/python3.12/bin/python3.12)
"$PY" -m pip install --no-cache-dir --disable-pip-version-check -q "PySide6-Essentials>=6.7"
rm -f $A/AppRun $A/*.desktop $A/*.png $A/.DirIcon $A/usr/share/applications/*.desktop $A/usr/share/metainfo/* 2>/dev/null || true
mkdir -p $A/usr/share/tonie-aufnahme
cp -r tonie_aufnahme/app.py tonie_aufnahme/recorder.py tonie_aufnahme/bilder $A/usr/share/tonie-aufnahme/
cat > $A/AppRun <<'EOT'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONNOUSERSITE=1
exec "$HERE/opt/python3.12/bin/python3.12" -I "$HERE/usr/share/tonie-aufnahme/app.py" "$@"
EOT
chmod +x $A/AppRun
sed -e 's#^Exec=.*#Exec=AppRun#' -e 's#^Icon=.*#Icon=tonie-aufnahme#' tonie-aufnahme.desktop > $A/tonie-aufnahme.desktop
cp tonie_aufnahme/bilder/app-icon.png $A/tonie-aufnahme.png; ln -sf tonie-aufnahme.png $A/.DirIcon
chmod -R a+rX $A; chmod 755 $A
curl -fsSL -o $W/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x $W/appimagetool
ARCH=x86_64 $W/appimagetool --appimage-extract-and-run -n $A dist/Tonie-Aufnahme-${V}-x86_64.AppImage

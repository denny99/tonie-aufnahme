#!/bin/bash
# Entfernt die Tonie-Aufnahme wieder. Deine Aufnahmen in ~/Musik/Tonie bleiben.
set -euo pipefail
rm -rf "$HOME/.local/share/tonie-aufnahme"
rm -f "$HOME/.local/bin/tonie-aufnahme" "$HOME/.local/share/applications/tonie-aufnahme.desktop"
echo "Entfernt. Deine Aufnahmen in ~/Musik/Tonie sind noch da."

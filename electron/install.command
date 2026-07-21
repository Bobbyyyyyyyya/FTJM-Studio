#!/bin/bash

APP_NAME="FTJM Studio"
INSTALL_DIR="/Applications"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== $APP_NAME Installer ==="
echo ""

if [ ! -d "$SCRIPT_DIR/$APP_NAME.app" ]; then
    echo "Fout: $APP_NAME.app niet gevonden in deze map."
    read -p "Druk op Enter om te sluiten..."
    exit 1
fi

if [ -d "$INSTALL_DIR/$APP_NAME.app" ]; then
    echo "Eerder geinstalleerde versie verwijderen..."
    rm -rf "$INSTALL_DIR/$APP_NAME.app"
fi

echo "Installeren naar $INSTALL_DIR..."
cp -R "$SCRIPT_DIR/$APP_NAME.app" "$INSTALL_DIR/$APP_NAME.app"

echo "Gatekeeper quarantine verwijderen..."
xattr -cr "$INSTALL_DIR/$APP_NAME.app"

echo ""
echo "=== Installatie voltooid! ==="
echo ""

open "$INSTALL_DIR/$APP_NAME.app"

osascript -e "tell application \"System Events\" to display notification \"$APP_NAME is geinstalleerd!\" with title \"$APP_NAME\""

read -p "Druk op Enter om te sluiten..."

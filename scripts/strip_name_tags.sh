#!/bin/sh
# Strip redundant category tags like "[ESP32]" from application.fam display names.
# Copied from xMasterX/all-the-plugins (same purpose). Runs on BUILD copies only.
set -eu

DIR="${1:?usage: strip_name_tags.sh <applications_user dir>}"
TAGS="ESP32 ESP8266 NRF24 VGM GPIO"

find "$DIR" -name application.fam | while read -r fam; do
    for tag in $TAGS; do
        if grep -q "name=\"\[$tag\]" "$fam" 2>/dev/null; then
            sed "s/name=\"\[$tag\] */name=\"/g" "$fam" >"$fam.tmp" && mv "$fam.tmp" "$fam"
            echo " stripped [$tag] from $fam"
        fi
    done
done

echo "Done stripping name tags in $DIR"

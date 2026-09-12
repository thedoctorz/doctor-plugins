# Doctor Plugins

Community Flipper Zero apps (`.fap`) compiled for **[The Doctor's Firmware](https://github.com/thedoctorz/doctor-firmware)**.

CI clones [xMasterX/all-the-plugins](https://github.com/xMasterX/all-the-plugins), skips apps that cannot link against this SDK or that already ship in the firmware, compiles the rest, and publishes what succeeded.

Unleashed extra-pack binaries will not load. Match the pack to the firmware API shown on the device (**Settings → System**, or About).

## Install

1. Download `all-the-apps-extra.zip` from [Releases](https://github.com/thedoctorz/doctor-plugins/releases/latest)
2. Unpack
3. Copy folders from `extra_pack_build/artifacts-extra/` onto the microSD `apps/` directory (keep the category folders: `Games/`, `GPIO/`, …)

Or flash the firmware **`e`** package, which already contains this pack.

## Local build

```sh
git clone https://github.com/thedoctorz/doctor-plugins.git
cd doctor-plugins
git clone --depth 1 --recurse-submodules --shallow-submodules \
  https://github.com/thedoctorz/doctor-firmware.git firmware
git clone --depth 1 --branch dev https://github.com/xMasterX/all-the-plugins.git upstream
python3 scripts/fetch_apps.py --upstream upstream --firmware firmware \
  --report extra_pack_build/fetch-report.json
sh scripts/strip_name_tags.sh firmware/applications_user
python3 scripts/build_pack.py --firmware firmware --out extra_pack_build \
  --fetch-report extra_pack_build/fetch-report.json
```

Outputs: `all-the-apps-extra.tgz`, `all-the-apps-extra.zip`, `extra_pack_build/build-report.md`.

A `pack-*` tag publishes a GitHub Release.

## Credits

App sources come from the Flipper community via [all-the-plugins](https://github.com/xMasterX/all-the-plugins), originally collected and patched by [xMasterX](https://github.com/xMasterX). This repo only filters and rebuilds them. Individual apps keep their original authors and licenses.

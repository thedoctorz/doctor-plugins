#!/usr/bin/env python3
"""Compile extra apps against a Doctor firmware tree, skip failures, pack FAPs.

Mirrors Unleashed all-the-plugins output layout so firmware CI can:

    tar zxf all-the-apps-extra.tgz
    cp -R extra_pack_build/artifacts-extra/* \\
        applications/main/extra_resources/resources/apps/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

FAP_APPID_RE = re.compile(r'\bappid\s*=\s*"([^"]+)"')
FAP_CAT_RE = re.compile(r'\bfap_category\s*=\s*"([^"]+)"')
EXTERNAL_RE = re.compile(r"FlipperAppType\.EXTERNAL")


def parse_externals(fam: Path) -> list[tuple[str, str]]:
    """Return (appid, category) for each EXTERNAL App() in a fam file."""
    text = fam.read_text(encoding="utf-8", errors="replace")
    chunks = re.split(r"\bApp\s*\(", text)
    out: list[tuple[str, str]] = []
    for chunk in chunks[1:]:
        if not EXTERNAL_RE.search(chunk):
            continue
        appid = FAP_APPID_RE.search(chunk)
        if not appid:
            continue
        cat = FAP_CAT_RE.search(chunk)
        category = (cat.group(1) if cat else "Extra").strip("/") or "Extra"
        out.append((appid.group(1), category))
    return out


def run_fbt(fw: Path, args: list[str], log: Path) -> int:
    cmd = [str(fw / "fbt"), "COMPACT=1", "DEBUG=0", "FBT_NO_SYNC=0", *args]
    env = os.environ.copy()
    env.setdefault("FORCE_NO_DIRTY", "yes")
    env.setdefault("FBT_GIT_SUBMODULE_SHALLOW", "1")
    with log.open("ab") as fh:
        fh.write(f"\n>>> {' '.join(cmd)}\n".encode())
        fh.flush()
        proc = subprocess.run(
            cmd,
            cwd=fw,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    return proc.returncode


def find_fap(fw: Path, appid: str) -> Path | None:
    candidates = [
        fw / "build" / "f7-firmware-C" / ".extapps" / f"{appid}.fap",
        fw / "build" / "latest" / ".extapps" / f"{appid}.fap",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = list(fw.glob(f"**/{appid}.fap"))
    return matches[0] if matches else None


def copy_apps_data(fw: Path, extra_ids: set[str], dest: Path) -> None:
    src_root = fw / "build" / "f7-firmware-C" / "resources" / "apps_data"
    if not src_root.is_dir():
        src_root = fw / "build" / "latest" / "resources" / "apps_data"
    if not src_root.is_dir():
        return
    for child in src_root.iterdir():
        if child.is_dir() and child.name.lower() in extra_ids:
            target = dest / child.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument(
        "--extra-dir",
        default="applications_user",
        help="Relative to firmware root; used if --fetch-report is omitted",
    )
    parser.add_argument(
        "--fetch-report",
        type=Path,
        default=None,
        help="fetch_apps.py JSON; only compile apps listed there",
    )
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    args = parser.parse_args()

    fw = args.firmware.resolve()
    extra = fw / args.extra_dir
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    artifacts = out / "artifacts-extra"
    if artifacts.exists():
        shutil.rmtree(artifacts)
    artifacts.mkdir(parents=True)
    apps_data = out / "apps_data"
    if apps_data.exists():
        shutil.rmtree(apps_data)
    apps_data.mkdir()

    log = out / "fbt.log"
    if log.exists():
        log.unlink()

    apps: list[tuple[str, str, Path]] = []
    if args.fetch_report:
        report = json.loads(args.fetch_report.read_text(encoding="utf-8"))
        fam_dirs = [fw / item["path"] for item in report.get("selected", [])]
    else:
        fam_dirs = [extra]
    for app_dir in fam_dirs:
        if not app_dir.is_dir():
            continue
        for fam in sorted(app_dir.rglob("application.fam")):
            for appid, category in parse_externals(fam):
                apps.append((appid, category, fam.parent))

    # Unique appids, first category wins
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for appid, category, _parent in apps:
        if appid in seen:
            continue
        seen.add(appid)
        unique.append((appid, category))

    print(f"building {len(unique)} extra FAPs against {fw}", file=sys.stderr)

    ok: list[dict] = []
    failed: list[dict] = []
    extra_ids = {a.lower() for a, _c in unique}

    for appid, category in unique:
        print(f"fap  {appid}  ({category})", file=sys.stderr)
        rc = run_fbt(fw, [f"fap_{appid}"], log)
        fap = find_fap(fw, appid) if rc == 0 else None
        if rc != 0 or fap is None:
            failed.append({"appid": appid, "category": category, "rc": rc})
            print(f"FAIL {appid}", file=sys.stderr)
            continue
        dest_dir = artifacts / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fap, dest_dir / f"{appid}.fap")
        ok.append(
            {
                "appid": appid,
                "category": category,
                "fap": str((dest_dir / f"{appid}.fap").relative_to(out)),
            }
        )
        print(f"OK   {appid} -> {category}/{appid}.fap", file=sys.stderr)

    copy_apps_data(fw, extra_ids, apps_data)
    if not any(apps_data.iterdir()):
        apps_data.rmdir()

    report = {
        "ok": ok,
        "failed": failed,
        "counts": {"ok": len(ok), "failed": len(failed)},
    }
    (out / "build-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Extra apps build",
        "",
        f"Compiled **{len(ok)}**, skipped **{len(failed)}** (missing HAL/API or compile error).",
        "",
        "## Built",
        "",
    ]
    for row in ok:
        lines.append(f"- `{row['category']}/{row['appid']}.fap`")
    if failed:
        lines += ["", "## Failed (not in the pack)", ""]
        for row in failed:
            lines.append(f"- `{row['appid']}`")
    (out / "build-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tgz = out.parent / "all-the-apps-extra.tgz"
    zip_path = out.parent / "all-the-apps-extra.zip"
    # Archive the extra_pack_build folder itself (Unleashed layout)
    pack_parent = out.parent
    folder_name = out.name
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(out, arcname=folder_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in out.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(Path(folder_name) / path.relative_to(out)))

    print(f"wrote {tgz} and {zip_path} ({len(ok)} faps)", file=sys.stderr)
    if not ok:
        print("error: no FAPs compiled", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

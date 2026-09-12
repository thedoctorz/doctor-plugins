#!/usr/bin/env python3
"""Copy compatible all-the-plugins apps into a Doctor firmware tree.

Skips:
  - names in apps/blocklist.txt
  - folders whose name looks like NFC / RFID / iButton / JS
  - sources that match apps/forbidden.txt
  - apps already present in the firmware applications_user/ tree
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PACKS = ("base_pack", "apps_source_code", "non_catalog_apps")
SOURCE_GLOBS = ("*.c", "*.h", "*.cpp", "*.hpp", "*.cc", "application.fam")
NAME_BLOCK_RE = re.compile(
    r"(nfc|rfid|lfrfid|ibutton|mifare|picopass|mfkey|t5577|em4100|"
    r"iso15693|one.?wire|amiibo)",
    re.IGNORECASE,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def name_keys(name: str) -> set[str]:
    n = name.lower().strip()
    compact = re.sub(r"[^a-z0-9]", "", n)
    return {n, n.replace("-", "_"), n.replace("_", "-"), compact}


def occupy(occupied: set[str], name: str) -> None:
    occupied.update(name_keys(name))


def is_occupied(occupied: set[str], name: str) -> bool:
    return bool(occupied.intersection(name_keys(name)))


def load_blocklist(path: Path) -> set[str]:
    occupied: set[str] = set()
    for n in load_lines(path):
        occupy(occupied, n)
    return occupied


def load_forbidden(path: Path) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in load_lines(path)]


def firmware_occupied(fw: Path) -> set[str]:
    occupied: set[str] = set()
    user = fw / "applications_user"
    if user.is_dir():
        for child in user.iterdir():
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            occupy(occupied, child.name)
    for root_name in ("applications_user", "applications"):
        root = fw / root_name
        if not root.is_dir():
            continue
        for fam in root.rglob("application.fam"):
            occupy(occupied, fam.parent.name)
            for appid in appids_from_fam(fam):
                occupy(occupied, appid)
    return occupied


def appids_from_fam(fam: Path) -> set[str]:
    text = fam.read_text(encoding="utf-8", errors="replace")
    return {m.group(1).lower() for m in re.finditer(r'\bappid\s*=\s*"([^"]+)"', text)}


def is_external_fam(fam: Path) -> bool:
    text = fam.read_text(encoding="utf-8", errors="replace")
    return "FlipperAppType.EXTERNAL" in text


def iter_source_text(app_dir: Path) -> str:
    chunks: list[str] = []
    for pattern in SOURCE_GLOBS:
        for path in app_dir.rglob(pattern):
            if not path.is_file():
                continue
            if ".git" in path.parts:
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def forbidden_hit(app_dir: Path, patterns: list[re.Pattern[str]]) -> str | None:
    blob = iter_source_text(app_dir)
    for pat in patterns:
        if pat.search(blob):
            return pat.pattern
    return None


def copy_app(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(".git", ".github", ".gitea", "__pycache__"),
        symlinks=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream",
        required=True,
        type=Path,
        help="Clone of xMasterX/all-the-plugins",
    )
    parser.add_argument(
        "--firmware",
        required=True,
        type=Path,
        help="Firmware tree",
    )
    parser.add_argument(
        "--dest-name",
        default="",
        help="Optional subfolder under applications_user/. Empty = copy each "
        "app as applications_user/<name>/ (required for fbt to see them).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("fetch-report.json"),
        help="Where to write the keep/skip JSON report",
    )
    args = parser.parse_args()

    root = repo_root()
    block = load_blocklist(root / "apps" / "blocklist.txt")
    forbidden = load_forbidden(root / "apps" / "forbidden.txt")
    occupied = firmware_occupied(args.firmware)

    user_root = args.firmware / "applications_user"
    user_root.mkdir(parents=True, exist_ok=True)
    dest_root = user_root / args.dest_name if args.dest_name else user_root
    if args.dest_name:
        if dest_root.exists():
            shutil.rmtree(dest_root)
        dest_root.mkdir(parents=True)

    selected: list[dict] = []
    skipped: list[dict] = []

    for pack in PACKS:
        pack_dir = args.upstream / pack
        if not pack_dir.is_dir():
            print(f"warning: missing pack {pack_dir}", file=sys.stderr)
            continue
        for app_dir in sorted(p for p in pack_dir.iterdir() if p.is_dir()):
            name = app_dir.name
            key = name.lower()
            fams = list(app_dir.rglob("application.fam"))
            reason = None
            if is_occupied(block, name):
                reason = "blocklist"
            elif NAME_BLOCK_RE.search(name) and key not in {"nfc_sniffer"}:
                reason = "name looks like NFC/RFID/iButton"
            elif not fams:
                reason = "no application.fam"
            elif not any(is_external_fam(f) for f in fams):
                reason = "no FlipperAppType.EXTERNAL"
            elif is_occupied(occupied, name) or any(
                is_occupied(occupied, aid)
                for fam in fams
                for aid in appids_from_fam(fam)
            ):
                reason = "already in firmware"
            else:
                hit = forbidden_hit(app_dir, forbidden)
                if hit:
                    reason = f"forbidden import: {hit}"

            if reason:
                skipped.append({"pack": pack, "name": name, "reason": reason})
                continue

            dest = dest_root / name
            if dest.exists():
                skipped.append(
                    {"pack": pack, "name": name, "reason": "already in firmware"}
                )
                continue
            copy_app(app_dir, dest)
            ids = set()
            for fam in dest.rglob("application.fam"):
                ids.update(appids_from_fam(fam))
            occupy(occupied, key)
            for appid in ids:
                occupy(occupied, appid)
            selected.append(
                {
                    "pack": pack,
                    "name": name,
                    "appids": sorted(ids),
                    "path": str(dest.relative_to(args.firmware)),
                }
            )
            print(f"keep  {pack}/{name}")

    report = {
        "selected": selected,
        "skipped": skipped,
        "counts": {"selected": len(selected), "skipped": len(skipped)},
    }
    report_path = args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"selected {len(selected)} apps, skipped {len(skipped)} -> {dest_root}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

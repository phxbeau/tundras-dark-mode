#!/usr/bin/env python3
"""Build Tundras Dark Mode for Firefox and for Chromium browsers (Chrome/Edge).

`tundras-dark-mode/` is the single shared source. The only real difference
between the targets is the manifest:

  * Firefox MV3 runs the background script as an event page  -> background.scripts
  * Chromium MV3 runs it as a service worker                 -> background.service_worker

`browser_specific_settings` is Firefox-only and is dropped from the Chromium
build so Chrome/Edge don't log an "Unrecognized manifest key" warning.

Outputs (dist/):
  tundras-dark-mode-firefox.xpi   load via about:debugging or Add-ons -> Install from file
  chrome/                         unpacked, for chrome://extensions -> Load unpacked
  tundras-dark-mode-chrome.zip    zipped copy of the same, for packaging/upload
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "tundras-dark-mode"
DIST = ROOT / "dist"

ASSETS = [
    "background.js",
    "redactor-fix.js",
    "dark.css",
    "icons/icon-16.png",
    "icons/icon-32.png",
    "icons/icon-48.png",
    "icons/icon-96.png",
    "icons/icon-128.png",
]


def chrome_manifest(base):
    m = json.loads(json.dumps(base))  # deep copy
    m.pop("browser_specific_settings", None)
    m["background"] = {"service_worker": "background.js"}
    m["minimum_chrome_version"] = "109"
    return m


def write_zip(path, manifest, prefix=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        for rel in ASSETS:
            z.write(SRC / rel, prefix + rel)


def main():
    base = json.loads((SRC / "manifest.json").read_text())
    version = base["version"]

    if DIST.exists():
        # A browser still holding files open (Load unpacked, or a headless test
        # run) leaves NFS .nfsXXXX lock files behind and rmtree fails. Clear what
        # we can and carry on rather than dying half-way.
        shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)
    for stale in DIST.rglob("*"):
        if stale.is_file() and not stale.name.startswith(".nfs"):
            stale.unlink(missing_ok=True)

    # --- Firefox: manifest.json is already the Firefox flavour ---
    xpi = DIST / "tundras-dark-mode-firefox.xpi"
    write_zip(xpi, base)

    # --- Chromium (Chrome + Edge): unpacked dir + zip ---
    cm = chrome_manifest(base)
    unpacked = DIST / "chrome"
    (unpacked / "icons").mkdir(parents=True)
    (unpacked / "manifest.json").write_text(json.dumps(cm, indent=2) + "\n")
    for rel in ASSETS:
        shutil.copy2(SRC / rel, unpacked / rel)
    write_zip(DIST / "tundras-dark-mode-chrome.zip", cm)

    print(f"built v{version}")
    for p in sorted(DIST.rglob("*")):
        if p.is_file() and p.parent == DIST and not p.name.startswith(".nfs"):
            print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size:,} bytes)")
    print(f"  {unpacked.relative_to(ROOT)}/  (unpacked, for Load unpacked)")


if __name__ == "__main__":
    main()

"""Build the prepackaged AWORG downloads: Python, AWORG and a browser in one archive.

    python packaging/build.py                 every target
    python packaging/build.py windows-x64     just the ones named

For people without Python, or who would rather not set it up. Each archive
holds a standalone CPython, AWORG with everything it depends on already
installed, and the Chromium Browser capability with that system's headless
engine -- the one thing a pip install never gets. Unpack it and run the start
file.

Built from any one machine for every target. Python comes from
python-build-standalone, AWORG's dependencies are installed as that target's
prebuilt wheels (pip --platform), and the engine comes from Chrome for
Testing, so nothing here has to run on the system it is built for. Only the
build for the machine doing the building can be tried out here.

Downloads are cached in packaging/cache; archives land in packaging/dist,
named aworg-<version>-<target>, ready to attach to the GitHub release
tagged v<version>.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CACHE = HERE / "cache"
DIST = HERE / "dist"

PYTHON = "3.12"

#: Per target: the python-build-standalone triple, the wheel platforms pip
#: may install from, Chrome for Testing's name for it, and the archive kind.
TARGETS = {
    "windows-x64": {
        "triple": "x86_64-pc-windows-msvc",
        "wheels": ["win_amd64"],
        "chrome": "win64",
        "archive": "zip",
    },
    "macos-arm64": {
        "triple": "aarch64-apple-darwin",
        "wheels": ["macosx_11_0_arm64", "macosx_11_0_universal2"],
        "chrome": "mac-arm64",
        "archive": "tar",
    },
    "macos-x64": {
        "triple": "x86_64-apple-darwin",
        "wheels": ["macosx_10_13_x86_64", "macosx_10_13_universal2"],
        "chrome": "mac-x64",
        "archive": "tar",
    },
    "linux-x64": {
        "triple": "x86_64-unknown-linux-gnu",
        "wheels": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64",
                   "manylinux2014_x86_64"],
        "chrome": "linux64",
        "archive": "tar",
    },
}

PBS_RELEASES = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
CHROME_VERSIONS = ("https://googlechromelabs.github.io/chrome-for-testing/"
                   "last-known-good-versions-with-downloads.json")

WINDOWS_START = """@echo off
rem Starts AWORG. Close this window to stop it.
"%~dp0python\\python.exe" -m aworg start %*
pause
"""

UNIX_START = """#!/bin/sh
# Starts AWORG. Press Ctrl+C to stop it.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/python/bin/python3" -m aworg start "$@"
"""

README = """AWORG {version} for {target}
{underline}

Start it
  {start}

It prints an address and a password. Open the address in your browser,
sign in with the password, then open Settings and add a model connection.

Your Aworg lives in the folder .aworg in your home directory, not in this
folder, so you can replace this folder with a newer version and keep
everything.
{extra}
More skills, tools and personas: https://aworg.com
"""

MAC_NOTE = """
macOS: these files are not signed. Installed with the Terminal line on
https://aworg.com/get they run straight away. If you downloaded this in a
browser instead, macOS will refuse to run them until you open Terminal in
this folder and run
  xattr -dr com.apple.quarantine .
"""


def fetch(url: str, name: str) -> Path:
    """Download once into the cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"  downloading {name}")
        request = urllib.request.Request(url, headers={"User-Agent": "aworg-build"})
        with urllib.request.urlopen(request, timeout=600) as response:
            data = response.read()
        path.write_bytes(data)
    return path


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "aworg-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def version() -> str:
    for line in (REPO / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("No version in pyproject.toml")


def python_assets() -> dict[str, tuple[str, str]]:
    """The newest standalone CPython {PYTHON}.x per target, stripped of debug
    symbols where there is a stripped build (it is a fraction of the size)."""
    release = fetch_json(PBS_RELEASES)
    found: dict[str, dict[str, tuple[str, str]]] = {}
    for asset in release["assets"]:
        name = asset["name"]
        if not (name.startswith(f"cpython-{PYTHON}.") and "+" in name):
            continue
        for target, spec in TARGETS.items():
            for kind in ("install_only_stripped", "install_only"):
                if name.endswith(f"-{spec['triple']}-{kind}.tar.gz"):
                    found.setdefault(target, {})[kind] = (name, asset["browser_download_url"])
    return {target: kinds.get("install_only_stripped") or kinds["install_only"]
            for target, kinds in found.items()}


def chrome_downloads() -> tuple[dict[str, str], str]:
    index = fetch_json(CHROME_VERSIONS)
    stable = index["channels"]["Stable"]
    return {d["platform"]: d["url"]
            for d in stable["downloads"]["chrome-headless-shell"]}, stable["version"]


def build_wheel(into: Path) -> Path:
    # setuptools' build/lib is additive: a wheel built over an old one ships
    # files deleted since. See docs/PUBLISHING.md.
    for stale in (REPO / "build", *REPO.glob("*.egg-info")):
        shutil.rmtree(stale, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q",
                    "-w", str(into), str(REPO)], check=True)
    return next(into.glob("aworg-*.whl"))


def site_packages(target: str) -> str:
    """Where packages go, relative to the Python folder."""
    if target.startswith("windows"):
        return "Lib/site-packages"
    return f"lib/python{PYTHON}/site-packages"


def build(target: str, wheel: Path, pythons: dict, chromes: dict, chrome_version: str,
          release: str) -> Path:
    spec = TARGETS[target]
    windows = target.startswith("windows")
    mac = target.startswith("macos")
    print(f"{target}")
    # The archive carries the version; the folder inside is plain AWORG, so a
    # new version unpacks over the old one. The Aworg itself lives in
    # ~/.aworg, untouched.
    name = "AWORG"
    archive_name = f"aworg-{release}-{target}"
    work = Path(tempfile.mkdtemp(prefix="aworg-build-"))
    # Everything that is not the Python itself, laid out as it will be in the
    # archive. Python is added straight from its own tarball instead of being
    # unpacked here: it is full of symlinks (python -> python3.12, the shared
    # library), and unpacked on Windows each one becomes a second full copy.
    stage = work / name
    packages = stage / "python" / site_packages(target)
    packages.mkdir(parents=True)

    # AWORG and its dependencies, as this target's wheels.
    command = [sys.executable, "-m", "pip", "install", "-q", "--no-compile",
               "--target", str(packages),
               "--only-binary=:all:", "--implementation", "cp",
               "--python-version", PYTHON, "--abi", f"cp{PYTHON.replace('.', '')}",
               "--abi", "abi3", "--abi", "none"]
    for platform in spec["wheels"]:
        command += ["--platform", platform]
    subprocess.run(command + [str(wheel)], check=True)

    # The browser, complete: the capability where the installer seeds from,
    # and that platform's engine inside it.
    capability = packages / "aworg" / "capabilities" / "chromium"
    shutil.copytree(REPO / "capabilities" / "chromium", capability,
                    ignore=shutil.ignore_patterns("__pycache__", "chromium"))
    engine = fetch(chromes[spec["chrome"]],
                   f"chrome-headless-shell-{chrome_version}-{spec['chrome']}.zip")
    with zipfile.ZipFile(engine) as bundle:
        bundle.extractall(capability / "chromium")

    # Start file, README and the license.
    if windows:
        start = "AWORG.cmd"
        (stage / start).write_text(WINDOWS_START.replace("\n", "\r\n"),
                                   encoding="utf-8", newline="")
        how = "Double-click AWORG.cmd"
    else:
        start = "AWORG.command" if mac else "aworg.sh"
        (stage / start).write_text(UNIX_START, encoding="utf-8", newline="\n")
        how = (f"Double-click {start}, or run ./{start} in a terminal"
               if mac else f"Run ./{start} in a terminal")
    title = f"AWORG {release} for {target}"
    readme = README.format(version=release, target=target, underline="=" * len(title),
                           start=how, extra=MAC_NOTE if mac else "")
    (stage / "README.txt").write_text(readme.replace("\n", "\r\n") if windows else readme,
                                      encoding="utf-8", newline="")
    for legal in ("LICENSE", "ADDITIONAL-TERMS.md", "TRADEMARKS.md"):
        shutil.copy(REPO / legal, stage / legal)

    asset, url = pythons[target]
    python = fetch(url, asset)
    DIST.mkdir(parents=True, exist_ok=True)

    if windows:
        # Zip, which is what Windows opens. The Windows Python has no symlinks.
        out = DIST / f"{archive_name}.zip"
        out.unlink(missing_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            with tarfile.open(python) as source:
                for member in source:
                    if member.isfile():
                        archive.writestr(f"{name}/{member.name}",
                                         source.extractfile(member).read())
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{name}/{path.relative_to(stage).as_posix()}")
    else:
        # Tar, which keeps symlinks and the execute bits Mac and Linux need.
        out = DIST / f"{archive_name}.tar.gz"
        out.unlink(missing_ok=True)
        engine_dir = capability / "chromium"

        def owned(info: tarfile.TarInfo) -> tarfile.TarInfo:
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info

        def ours(info: tarfile.TarInfo) -> tarfile.TarInfo:
            path = work / info.name
            if info.isfile():
                runnable = (path.name == start or engine_dir in path.parents
                            or path.suffix in (".so", ".dylib"))
                info.mode = 0o755 if runnable else 0o644
            elif info.isdir():
                info.mode = 0o755
            return owned(info)

        with tarfile.open(out, "w:gz", compresslevel=6) as archive:
            with tarfile.open(python) as source:
                for member in source:
                    member.name = f"{name}/{member.name}"
                    if member.islnk():
                        member.linkname = f"{name}/{member.linkname}"
                    data = source.extractfile(member) if member.isfile() else None
                    archive.addfile(owned(member), data)
            for path in sorted(stage.rglob("*")):
                arcname = f"{name}/{path.relative_to(stage).as_posix()}"
                if path.is_dir():
                    continue  # folders come with their files, and Python's from its tarball
                archive.add(path, arcname=arcname, recursive=False, filter=ours)

    shutil.rmtree(work, ignore_errors=True)
    print(f"  {out.name}  {out.stat().st_size / 1024 / 1024:.0f} MB")
    return out


def main(argv: list[str]) -> None:
    targets = argv or list(TARGETS)
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        raise SystemExit(f"Unknown target {', '.join(unknown)}. Known: {', '.join(TARGETS)}")
    release = version()
    pythons = python_assets()
    missing = [t for t in targets if t not in pythons]
    if missing:
        raise SystemExit(f"No standalone Python {PYTHON} found for {', '.join(missing)}")
    chromes, chrome_version = chrome_downloads()
    with tempfile.TemporaryDirectory() as wheels:
        wheel = build_wheel(Path(wheels))
        for target in targets:
            build(target, wheel, pythons, chromes, chrome_version, release)


if __name__ == "__main__":
    main(sys.argv[1:])

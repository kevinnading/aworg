"""Fetch the Chromium this capability drives, into its own folder.

The capability ships as source and no engine, which is the right trade for a
download and the wrong one for a machine that has no Chromium at all. This
closes that: one call, one archive, and an engine in `chromium/` beside this
file, where `find_engine` looks first.

Inside the capability so that the capability is the whole of it. Delete the
folder and the engine goes; reset and choose Capabilities and it goes. The
price is fetching it again afterwards, which is this tool, and which is the
right way round: a reset that left a hundred megabytes behind to save the
owner a download would be deciding something that is theirs to decide.

What it fetches is Chrome for Testing's **headless shell** -- the build
Google publishes for automation, pinned to a known-good version, with no
updater, no profile migration and no first-run anything. It is the same
engine a full Chromium is, minus the parts that only matter when a person is
looking at the window.

It downloads and then runs a binary from the internet, which is exactly what
installing a capability already is. The version and the URL are reported
before anything is written, and the source is Google's own storage bucket.
"""

from __future__ import annotations

import io
import os
import platform
import stat
import sys
import zipfile
from pathlib import Path

import httpx

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import bundled_engine, engine_root


NAME = "install_engine"

DESCRIPTION = (
    "Download the Chromium this capability needs, if the machine has none. "
    "Fetches Chrome for Testing's headless shell (about 100 MB) into this "
    "capability's own folder. Call this when open_page says no Chromium was "
    "found."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "replace": {
            "type": "boolean",
            "description": (
                "Fetch it again even if an engine is already here, replacing "
                "what is there. Defaults to false."
            ),
        },
    },
}

#: Google's index of the versions it publishes for automation, and where each
#: platform's build is. Asked rather than hardcoded: a pinned URL is a URL
#: that stops existing.
VERSIONS = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)
BINARY = "chrome-headless-shell"
DOWNLOAD_TIMEOUT = 600
#: Refused above this. A download that has gone wrong announces itself as an
#: enormous one, and this is a tool that writes to the owner's disk.
MAX_BYTES = 400 * 1024 * 1024


def _platform() -> str:
    """What Chrome for Testing calls the machine we are on."""
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        return "win64" if machine in ("amd64", "x86_64", "arm64") else "win32"
    if sys.platform == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if machine in ("x86_64", "amd64"):
        return "linux64"
    raise ToolError(
        f"Chrome for Testing does not publish a build for {platform.machine()} "
        f"on {sys.platform}. Install Chromium with this machine's package "
        "manager instead."
    )


async def run(context: ToolContext, replace: bool = False) -> ToolResult:
    destination = engine_root()
    existing = next(bundled_engine(), None)
    if existing is not None and not replace:
        return ToolResult(
            text=(
                f"An engine is already here: {existing}. "
                "Pass replace=true to fetch it again."
            ),
            summary="already installed",
        )

    wanted = _platform()
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        try:
            index = (await client.get(VERSIONS)).json()
        except Exception as exc:                              # noqa: BLE001
            raise ToolError(
                f"Could not read Google's list of published builds: {exc}"
            ) from exc

        stable = ((index.get("channels") or {}).get("Stable") or {})
        version = stable.get("version", "unknown")
        builds = (stable.get("downloads") or {}).get(BINARY) or []
        url = next((b.get("url") for b in builds if b.get("platform") == wanted), None)
        if not url:
            raise ToolError(
                f"Google publishes no {BINARY} for {wanted} in this release."
            )

        if context.activity is not None:
            context.activity.progress = f"downloading Chromium {version}"
        try:
            archive = await _download(client, url)
        except ToolError:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise ToolError(f"The download failed: {exc}") from exc

    if context.activity is not None:
        context.activity.progress = "unpacking"
    if destination.exists():
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            _extract(bundle, destination)
    except zipfile.BadZipFile as exc:
        raise ToolError(f"What came back was not a zip archive: {exc}") from exc

    engine = next(bundled_engine(), None)
    if engine is None:
        raise ToolError(
            "The archive unpacked, but no Chromium binary was found inside it."
        )
    _make_runnable(engine)

    return ToolResult(
        text=(
            f"Installed Chromium {version} ({BINARY}, {wanted}) at {engine}. "
            f"{len(archive) // (1024 * 1024)} MB downloaded from Google's "
            "storage for Chrome for Testing. open_page will use it from now "
            "on, in preference to anything installed on this machine."
        ),
        payload={"version": version, "platform": wanted, "path": str(engine),
                 "bytes": len(archive), "url": url},
        summary=f"Chromium {version}",
    )


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    """The archive, refusing anything absurd before it is in memory."""
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_BYTES:
                raise ToolError(
                    f"The download passed {MAX_BYTES // (1024 * 1024)} MB and "
                    "was stopped. That is not a headless shell."
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _extract(bundle: zipfile.ZipFile, destination: Path) -> None:
    """Unpack, refusing any member that would land outside the folder.

    A zip is a list of paths chosen by whoever built it, and `..` in one of
    them writes wherever it likes. The archive here comes from Google, which
    is a reason to expect it to be fine and not a reason to skip the check.
    """
    root = destination.resolve()
    for member in bundle.infolist():
        target = (root / member.filename).resolve()
        if not str(target).startswith(str(root)):
            raise ToolError(
                f"The archive contains a path that escapes the folder: "
                f"{member.filename!r}. Nothing was installed."
            )
        bundle.extract(member, root)


def _make_runnable(engine: Path) -> None:
    """Give the binary the execute bit that a zip does not carry.

    Zip has no POSIX permission bits that Python restores by default, so an
    engine unpacked on macOS or Linux arrives unrunnable -- and the error for
    that is "permission denied" from a file that is plainly there.
    """
    if os.name == "nt":
        return
    for path in (engine, *engine.parent.glob("*.so"), *engine.parent.glob("*")):
        try:
            if path.is_file():
                mode = path.stat().st_mode
                path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            continue

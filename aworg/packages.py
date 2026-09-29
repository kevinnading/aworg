"""Installing a package from the AWORG store: `aworg get NAME`.

The store answers one question -- what is this package, and where is its
zip -- and this does the rest: download it, check the SHA-256 the store
published against the bytes that arrived, and unpack it into the folder in
the home that AWORG already reads from. Nothing here is new machinery for
AWORG itself. A skill lands in skills/, a persona in personas/, a tool in
capabilities/, exactly where copying the folder by hand used to put it.

An existing copy is not deleted. It goes to the trash with a note of where
it came from, the same way delete_file does it, so an update that turns out
worse can be put back.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import httpx

from .paths import Paths

#: Where packages come from. AWORG_STORE points an Aworg at another store --
#: a local copy of the site while working on it, most of all.
DEFAULT_STORE = "https://aworg.com"

NAME = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
TIMEOUT = 60


class GetError(Exception):
    """Something the owner is told, in a sentence, instead of a traceback."""


@dataclass
class Installed:
    name: str
    version: str
    type: str
    folder: Path
    replaced: Path | None


def store_url(override: str | None = None) -> str:
    return (override or os.environ.get("AWORG_STORE") or DEFAULT_STORE).rstrip("/")


def lookup(name: str, store: str) -> dict:
    """The store's record of a package, or a GetError saying why not."""
    if not NAME.match(name):
        raise GetError(f"{name!r} isn't a package name.")
    try:
        response = httpx.get(f"{store}/api/v1/packages/{name}", timeout=TIMEOUT,
                             follow_redirects=True)
    except httpx.HTTPError as exc:
        raise GetError(f"Couldn't reach the store at {store}: {exc}") from None
    if response.status_code == 404:
        raise GetError(f"There's no package called {name} in the store.")
    if response.status_code != 200:
        raise GetError(f"The store answered {response.status_code} for {name}.")
    try:
        return response.json()
    except ValueError:
        raise GetError("The store's answer wasn't JSON.") from None


def target_root(paths: Paths, kind: str) -> Path:
    roots = {"skill": paths.skills, "persona": paths.personas, "tool": paths.capabilities}
    if kind not in roots:
        raise GetError(f"This version of AWORG can't install a {kind}.")
    return roots[kind]


def download(record: dict, store: str, version: str | None) -> tuple[str, bytes]:
    """The zip, checked against the SHA-256 the store published for it."""
    wanted = version or record.get("latest")
    entry = next((v for v in record.get("versions", []) if v["version"] == wanted), None)
    if entry is None:
        raise GetError(f"{record['name']} has no version {wanted}.")
    try:
        response = httpx.get(f"{store}/api/v1/packages/{record['name']}/download",
                             params={"version": wanted}, timeout=TIMEOUT,
                             follow_redirects=True)
    except httpx.HTTPError as exc:
        raise GetError(f"The download failed: {exc}") from None
    if response.status_code != 200:
        raise GetError(f"The download failed: the store answered {response.status_code}.")
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != entry["sha256"]:
        raise GetError(
            f"The download doesn't match the store's SHA-256 for {record['name']} "
            f"{wanted}, so it wasn't installed. Try again; if it keeps "
            "happening, something between here and the store is changing it."
        )
    return wanted, response.content


def unpack(name: str, data: bytes, into: Path) -> None:
    """Every file under `name/` in the zip, into `into`, refusing anything
    that would land outside it. The store builds its zips this way, but the
    check is here too: a store is a server, and servers get replaced."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename.replace("\\", "/"))
            parts = path.parts
            if (path.is_absolute() or not parts or parts[0] != name
                    or any(part in ("..", "") for part in parts) or len(parts) < 2):
                raise GetError(f"The package contains a file it shouldn't: {info.filename}")
            destination = into.joinpath(*parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))


def to_trash(paths: Paths, folder: Path, why: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bin_folder = paths.trash / f"{stamp}-{secrets.token_hex(3)}"
    bin_folder.mkdir(parents=True, exist_ok=True)
    (bin_folder / "origin.json").write_text(json.dumps({
        "path": str(folder), "deleted_at": time.time(),
        "was_directory": True, "reason": why,
    }, indent=2), encoding="utf-8")
    shutil.move(str(folder), str(bin_folder / folder.name))
    return bin_folder


def install(paths: Paths, record: dict, version: str, data: bytes) -> Installed:
    name, kind = record["name"], record["type"]
    root = target_root(paths, kind)
    root.mkdir(parents=True, exist_ok=True)
    final = root / name

    # Unpacked beside the target first, so a failure half way leaves the
    # installed copy exactly as it was.
    staging = root / f".{name}.incoming-{secrets.token_hex(3)}"
    try:
        staging.mkdir()
        unpack(name, data, staging)
        replaced = None
        if final.exists():
            replaced = to_trash(paths, final, f"replaced by {name} {version} from the store")
        staging.rename(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return Installed(name, version, kind, final, replaced)


def describe(result: Installed) -> str:
    lines = [f"Installed {result.type} {result.name} {result.version} into {result.folder}"]
    if result.replaced:
        lines.append(f"The copy that was there is in the trash at {result.replaced}")
    if result.type == "tool":
        lines.append("Restart this Aworg to load it. Tools are read once, at startup.")
    else:
        lines.append("It's available now. No restart needed.")
    return "\n".join(lines)

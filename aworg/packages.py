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

import contextlib
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


#: The words the store uses for each type, in its URLs and here.
PLURALS = ("skills", "tools", "personas")


def _fetch(url: str, **params: str) -> httpx.Response:
    try:
        return httpx.get(url, params=params or None, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise GetError(f"Couldn't reach the store: {exc}") from None


def _json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        raise GetError("The store's answer wasn't JSON.") from None


def lookup(target: str, store: str) -> dict:
    """The store's record of a package, or a GetError saying why not.

    `target` is TYPE/NAME -- skills/house-style, tools/weather -- or a bare
    NAME. Names are unique per type, so a skill and a tool may both be
    called weather; a bare name is resolved when only one type has it, and
    otherwise the owner is shown the choices rather than given a guess.
    """
    plural, _, name = target.strip().rpartition("/")
    if plural and plural not in PLURALS:
        raise GetError(f"{plural!r} isn't a kind of package. Use skills/, tools/ or personas/.")
    if not NAME.match(name):
        raise GetError(f"{name!r} isn't a package name.")
    if not plural:
        response = _fetch(f"{store}/api/v1/packages", name=name)
        if response.status_code != 200:
            raise GetError(f"The store answered {response.status_code} when asked for {name}.")
        matches = [p["id"] for p in _json(response).get("packages", [])]
        if not matches:
            raise GetError(f"There's no package called {name} in the store.")
        if len(matches) > 1:
            raise GetError(f"More than one package is called {name}. Say which:\n"
                           + "\n".join(f"    aworg get {m}" for m in sorted(matches)))
        plural = matches[0].split("/", 1)[0]
    response = _fetch(f"{store}/api/v1/packages/{plural}/{name}")
    if response.status_code == 404:
        raise GetError(f"There's no package called {plural}/{name} in the store.")
    if response.status_code != 200:
        raise GetError(f"The store answered {response.status_code} for {plural}/{name}.")
    return _json(response)


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
    response = _fetch(f"{store}/api/v1/packages/{record['id']}/download", version=wanted)
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


#: Written into every installed package: what the store shipped. On the next
#: update it is how a file the package brought is told apart from one the
#: package made after it arrived -- the Browser's downloaded engine, most of
#: all, which lives in its own folder and is a hundred megabytes nobody
#: wants to fetch twice.
MANIFEST = ".aworg-package.json"


def _made_here(old: Path, shipped_now: set[str]) -> list[str]:
    """Top-level entries in the installed copy that the new version does not
    ship and that were not shipped by the old one either: things the package
    created. Carried over into the new version rather than binned with the
    old code."""
    try:
        record = json.loads((old / MANIFEST).read_text(encoding="utf-8"))
        shipped_before = {path.split("/", 1)[0] for path in record.get("files", [])}
    except (OSError, ValueError):
        # Put there by hand, before the store: nothing says what came with
        # it. Code is never carried over -- a tool file the new version
        # dropped must not come back -- and everything else is.
        shipped_before = None
    keep = []
    for entry in old.iterdir():
        if entry.name in shipped_now or entry.name in (MANIFEST, "__pycache__"):
            continue
        if shipped_before is not None:
            if entry.name in shipped_before:
                continue
        elif entry.suffix == ".py" or entry.name == "__init__.py":
            continue
        keep.append(entry.name)
    return keep


def install(paths: Paths, record: dict, version: str, data: bytes) -> Installed:
    name, kind = record["name"], record["type"]
    root = target_root(paths, kind)
    root.mkdir(parents=True, exist_ok=True)
    final = root / name

    # Unpacked beside the target first, so a failure half way leaves the
    # installed copy exactly as it was.
    staging = root / f".{name}.incoming-{secrets.token_hex(3)}"
    moved: list[str] = []
    try:
        staging.mkdir()
        unpack(name, data, staging)
        shipped = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
        replaced = None
        if final.exists():
            for entry in _made_here(final, {p.split("/", 1)[0] for p in shipped}):
                try:
                    # A rename, never shutil.move: on Windows a folder with one
                    # locked file in it makes move fall back to copy-then-delete,
                    # which deletes everything but the locked file and then
                    # fails. A rename is all or nothing, and staging sits beside
                    # the target, so it is always the same disk.
                    (final / entry).rename(staging / entry)
                except OSError as exc:
                    raise GetError(
                        f"Couldn't move {entry} across to the new version: {exc.strerror or exc}. "
                        "Something is using it -- for the Browser, that is its engine, so "
                        "close the browser (close_browser) or stop the Aworg, and try again. "
                        "Nothing was changed."
                    ) from None
                moved.append(entry)
        (staging / MANIFEST).write_text(json.dumps({
            "name": name, "type": kind, "version": version,
            "sha256": record.get("sha256") if version == record.get("latest") else None,
            "installed_at": time.time(), "files": shipped,
        }, indent=2), encoding="utf-8")
        if final.exists():
            replaced = to_trash(paths, final, f"replaced by {name} {version} from the store")
        staging.rename(final)
        moved.clear()
    finally:
        # Anything carried over goes home before the staging folder is
        # cleared away, so a failure never costs what the package had made.
        for back in moved:
            with contextlib.suppress(OSError):
                (staging / back).rename(final / back)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return Installed(name, version, kind, final, replaced)


def describe(result: Installed) -> str:
    lines = [f"Installed {result.type} {result.name} {result.version} into {result.folder}"]
    if result.replaced:
        lines.append(f"The copy that was there is in the trash at {result.replaced}")
    if result.type == "tool":
        lines.append("A running Aworg loads it before its next message; with the "
                     "interface open it appears within a few seconds.")
    else:
        lines.append("It's available now. No restart needed.")
    return "\n".join(lines)

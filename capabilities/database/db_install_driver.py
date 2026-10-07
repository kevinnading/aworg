"""Install the PostgreSQL or MySQL driver into this capability's own folder."""

from __future__ import annotations

import asyncio
import importlib
import sys

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import DRIVERS, LIB

NAME = "db_install_driver"

DESCRIPTION = (
    "Install the driver a PostgreSQL or MySQL connection needs, into this "
    "capability's own folder. SQLite needs none. Call it when a database tool "
    "says the driver is not installed."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["postgresql", "mysql"], "description": "Which driver."},
    },
    "required": ["kind"],
}


async def run(context: ToolContext, kind: str = "") -> ToolResult:
    kind = str(kind).strip().lower()
    if kind not in DRIVERS:
        raise ToolError("Choose 'postgresql' or 'mysql'.")
    LIB.mkdir(exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
        "--target", str(LIB), "--upgrade", DRIVERS[kind],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=300)
    except asyncio.TimeoutError:
        process.kill()
        raise ToolError("The install took over five minutes and was stopped.") from None
    if process.returncode != 0:
        raise ToolError(f"pip failed: {out.decode(errors='replace')[-800:]}")
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    importlib.invalidate_caches()
    return ToolResult(text=f"Installed {DRIVERS[kind]} into {LIB}.", summary=f"{kind} driver installed")

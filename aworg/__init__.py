"""AWORG - Autonomous Workspace Organism.

A persistent AI Resident that inhabits this machine.
"""

from importlib.metadata import PackageNotFoundError, version as _installed_version


#: What this build calls itself.
#:
#: Read back from the installed distribution rather than written down here,
#: because it was written down in three places -- pyproject.toml, this file,
#: and a hardcoded string in server.py's FastAPI() -- none of which read the
#: others. They agreed by luck. The first release that bumped two of the
#: three would have had the interface confidently reporting a version that
#: was not the one running, which is precisely the kind of claim the
#: Environment pane exists to make checkable.
#:
#: pyproject.toml is where a Python project's version belongs and the only
#: place this number is written down. Everything else -- this attribute, the
#: API's version field, the Environment pane, the Resident's own prompt --
#: reads it back from the metadata that installing actually produced.
#:
#: "unknown" rather than a literal when there is no metadata to ask, which
#: happens only when running out of a checkout nobody installed. A hardcoded
#: fallback would be a second source of truth that is right until the day it
#: is not, and would then report a wrong version confidently in the one place
#: an owner would go to check. The whole reason this is on screen is so a
#: claim about what is running can be trusted; "unknown" keeps that true.
try:
    __version__ = _installed_version("aworg")
except PackageNotFoundError:  # pragma: no cover - only outside an install
    __version__ = "unknown"

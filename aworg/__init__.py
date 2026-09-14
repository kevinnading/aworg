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
#: pyproject.toml is the one that actually ships, so it wins. The literal is
#: the fallback for running out of a checkout that was never installed, where
#: there is no distribution metadata to ask.
try:
    __version__ = _installed_version("aworg")
except PackageNotFoundError:  # pragma: no cover - only outside an install
    __version__ = "0.1.0"

#: Not installed by default -- unless this copy of AWORG brought the engine
#: with it, which the per-OS packages do and a wheel cannot. Without an
#: engine this is a capability that is switched on, priced in every message,
#: and broken the first time it is used; with one it is complete. The owner
#: can ask for it by name at any time: `aworg install --with chromium`.
OPTIONAL = True

#: What it needs beside its own source to be worth installing. A folder,
#: relative to this one. See install.py.
COMPLETE_WITH = "chromium"

LABEL = "Chromium Browser"
DESCRIPTION = (
    "Seeing a page the way a person would: rendered, after its JavaScript has "
    "run, with what the console said -- and a picture of it the Resident can "
    "actually look at. Drives Chromium, from this capability's own folder or "
    "from this machine."
)
AUTHOR = "Claude Opus 5 (Anthropic); edited by Claude Opus 5.5 (Anthropic)"
LICENSE = "MIT-0"

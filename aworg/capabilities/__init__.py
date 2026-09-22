"""Capabilities AWORG ships but does not need.

Not a Python package that matters at runtime -- nothing imports through it.
It is the seed directory the installer copies into `capabilities/` in an
Aworg's home, where the registry finds these folders and loads them exactly
as it loads a capability the owner downloaded from anywhere else.

The built-in Capabilities are not here. Filesystem, Shell and HTTP live in
aworg/tools/ because an Aworg without them does not work, and the internal
ones -- planning, the Living Log, delegation, knowledge -- are how the
Resident reaches AWORG's own subsystems rather than things an owner installs.
Everything else belongs out here, where it can be removed.
"""

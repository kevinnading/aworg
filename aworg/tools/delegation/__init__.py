LABEL = "Delegation"
DESCRIPTION = "Handing bounded work to temporary workers."

#: Not shown in the Capabilities pane and not switchable.
#:
#: This is an environment-embedded tool rather than an installable one: it is
#: how the Resident reaches an AWORG subsystem, not a package an owner chose
#: to add. Listing it beside Filesystem and Shell would invite the owner to
#: turn off a part of the machinery rather than a part of the Resident's
#: reach -- and workers are configured in Settings, where switching them off
#: individually is the control that actually makes sense.
INTERNAL = True

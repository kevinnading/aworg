#: Machinery, and now hidden as such. Both of these are how the Resident
#: reaches an AWORG subsystem rather than a package the owner chose to add:
#: naming the project and reloading the preview are the application's own
#: plumbing, configured in the panes that own them.
#:
#: It used to be shown-but-fixed, on the argument that what it costs per
#: message is worth knowing. That argument loses to what the pane is *for*.
#: Capabilities is where an owner decides what their Resident may reach, and
#: a row with nothing to decide is furniture in a room full of controls --
#: the price of it now rides in the pane's own total instead.
#:
#: The tools are untouched: an internal capability is never asked whether it
#: is enabled, so both still reach the Resident on every message.
INTERNAL = True

LABEL = "Application"
DESCRIPTION = (
    "The thing being built, and the owner's view of it. Reloading the live "
    "preview after a change, so the owner is looking at what exists now "
    "rather than at what existed when the server started."
)

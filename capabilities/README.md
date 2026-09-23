# Capabilities

Folders of Tools that AWORG does not ship.

Each of these is a capability in the form it is installed in: copy one into
`capabilities/` in an Aworg's home and it is offered to the Resident from the
next start, loaded by the same discovery as a built-in. Nothing here is
imported by AWORG itself, which is why it sits outside the package.

Outside on purpose, and it is the same argument as everywhere else in this
system. The built-in Capabilities -- Filesystem, Shell, HTTP, and the internal
ones the Resident reaches AWORG's own subsystems through -- live in
`aworg/tools/` because an Aworg without them does not work. Everything else is
something an owner chose to add and can remove, and a capability that arrives
inside the program is one they cannot.

## What is here

- **chromium** -- seeing a page the way a person would: rendered, after its
  JavaScript has run, with what the console said, and a picture of it the
  Resident can look at. Drives Chromium; `install_engine` fetches one into
  `chromium/` inside the capability if the machine has none.
- **weather** -- the small one. It exists to prove the path works: a folder
  AWORG does not need, loaded and called exactly like a built-in.

These are bound for the AWORG store. Until it exists, installing one is
copying a folder. Skills work the same way and live in `skills/` beside
this.

## Installing one

Copy the folder:

    cp -r capabilities/chromium ~/.aworg/capabilities/

Then restart the Aworg. Capabilities are discovered once at startup -- unlike
skills and personas, which are re-read on every request -- so a new one
appears on the next start rather than immediately. That is deliberate: code
arriving in a running process should happen at a moment somebody chose.

A reset with the Capabilities part ticked empties that folder, and nothing
here is put back automatically, because none of it shipped. Copy in what you
want again.

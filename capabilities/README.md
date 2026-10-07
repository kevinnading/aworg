# Capabilities

Folders of Tools that AWORG does not ship.

Each of these is a capability in the form it is installed in: copy one into
`capabilities/` in an Aworg's home and it is offered to the Resident from its
next message, loaded by the same discovery as a built-in. Nothing here is
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
- **search** -- web search with no key or account: titles, addresses and
  snippets from DuckDuckGo's plain results page. Unofficial, so heavy use is
  rate-limited and a change to that page breaks it until updated.
- **notify** -- push notifications to the owner's phone or desktop through
  ntfy.sh. A random topic is made on first use and kept in `notify.json`;
  the owner subscribes to it once.
- **database** -- named connections to SQLite, PostgreSQL and MySQL: tables,
  columns, read-only queries, and writes that commit or roll back together.
  `db_install_driver` installs the PostgreSQL or MySQL driver into `_lib/`
  in the capability's folder. Connection URLs, passwords included, are kept
  in `connections.json` there.

search, notify and database are in the AWORG store: `aworg get tools/NAME`.
chromium and weather are kept here and not published -- chromium for the
prepackaged builds, which bring their own engine, and weather as the
smallest working example. Installing either is copying its folder. Skills
work the same way and live in `skills/` beside this.

## Installing one

Copy the folder:

    cp -r capabilities/chromium ~/.aworg/capabilities/

A running Aworg picks it up without a restart: before every message, and
every few seconds while the interface is open, it checks the capabilities
folder and reloads any capability whose Python files changed. Only the
changed ones reload, and their old modules are dropped first so versions
never mix. A module that defines `unload()` is called before it goes --
Chromium closes its engine there. `aworg get NAME` installs from the store.

A reset with the Capabilities part ticked empties that folder, and nothing
here is put back automatically, because none of it shipped. Copy in what you
want again.

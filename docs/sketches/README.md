# Sketches

Design explorations, kept because they were expensive to make and cheap to
store. Not direction and not spec — the numbered documents beside this folder
are direction. These are drawings of things that were being decided.

Open the HTML files in a browser. They are self-contained and use AWORG's own
colour tokens, so what you see is roughly what the interface would look like.

## persona-presence.html

Three ways to give the Resident a presence in the chat's top-left, each shown
working / idle / waiting on the owner. Made 2026-09-11 after Kevin said the
persona avatar should be "more than simply an icon by the chat bubbles" — he
pictured "a figure at the top left of the chat box that maybe has a thought
bubble showing it's current status".

- **A · The Perch** — figure in the corner with a thought bubble beside it.
  Closest to what was described. Recommended.
- **B · The Ledge** — a fixed strip across the top: smaller figure, name,
  activity, progress bar. Quieter, costs 46px that never moves.
- **C · The Watcher** — large figure fading into the background, status as a
  floating pill. Most atmospheric. **Conflicts with `chat_background`** —
  `nocturne` and `atelier` already fill that surface with artwork, and a large
  figure on top of it is two pieces of art fighting in one corner.

The figure in all three is a stand-in, not a character design. The layout is
the proposal.

Two things were true of every option and would be true of whatever is built:

- Status is derived from the same live Activity the Activities pane reads
  (`label`, `detail`, `progress`), never asserted, so it goes quiet on its own
  when nothing is running.
- The 28px avatar beside replies stays. This is a presence, not a replacement.

Unresolved when the sketches were made: every persona needs its own figure,
which is six today and none for any persona a stranger writes. The cheapest
honest fallback is that a persona with no `figure.svg` shows its existing
avatar mark at the larger size, with the status bubble unchanged.

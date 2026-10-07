# Personas

Every AWORG persona, as it goes to the store -- all eighteen.

Seven of them also ship preinstalled: atelier, aworg-light, aworg-dark,
egirl, player-two, professional and sunny. Their shipped copies live in
`aworg/personas/` inside the package, and the installer puts them in place.
**This folder is the source**: change a shipped persona here, then copy it
over the one in `aworg/personas/` so the two stay the same.

A persona is a folder with a `PERSONA.md` -- who the Resident is and how it
speaks -- and optionally a `theme.json`, an avatar and a chat background.
Install one by copying its folder into `personas/` in an Aworg's home, or
from the store with `aworg get personas/NAME`.

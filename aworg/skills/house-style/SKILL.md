---
name: house-style
description: This Aworg's own conventions for any file it writes — where things go, how they are named, and what every file must contain. Use before creating any new file, of any kind. These rules are specific to this machine and are not what you would do by default.
---

# House style

Conventions for this Aworg specifically. None of these are general good
practice; they are what this owner wants, and you cannot infer them.

## Every file gets a provenance line

The first line of any file you create is a comment naming the task it came
from, in the comment syntax of that file's language:

    <!-- aworg: <task id> -->
    /* aworg: <task id> */
    # aworg: <task id>

If there is no task, use `aworg: unplanned`. This is how the owner traces a
file back to the reason it exists months later.

## Where things go

- websites and web apps  ->  `site/`
- scripts and one-off tools  ->  `bin/`
- anything data-shaped  ->  `data/`

Never the workspace root. The root is for the folders above and nothing else.

## Naming

Lower case, hyphens, no underscores and no camelCase. `brewing-guide.html`,
not `brewingGuide.html` or `brewing_guide.html`.

## Before you say a file is done

Read it back with read_file and confirm the provenance line is actually the
first line. Writing it and assuming it landed is the failure this Aworg cares
most about.

# Publishing to PyPI

Notes from investigating what it would take for `pip install aworg` to work
for anyone. Nothing has been published. Written 2026-09-14 so that the work
already done does not have to be redone, and so the two things that caught us
by surprise are not surprises twice.

## Where it stands

- **Licensed 2026-09-16**: PolyForm Shield 1.0.0 with `ADDITIONAL-TERMS.md`
  and `TRADEMARKS.md`. Source-available, not open source.

- **The name `aworg` is free.** `pypi.org/pypi/aworg/json` returned 404 on
  2026-09-14. Unclaimed names do not stay unclaimed, and a PyPI name can
  never be renamed or reused after deletion, so claiming it is cheap
  insurance whenever the rest is ready.
- **The build works.** `python -m pip wheel . --no-deps` produces
  `aworg-0.7.0-py3-none-any.whl`, 89 files.
- **It has been run from an installed distribution**, not just a checkout:
  wheel into a fresh virtualenv, boot, ask the running app. Skills, personas
  and the version all came back correct.
- **There is a GitHub remote**, `kevinnading/aworg`, which is what Trusted
  Publishing would attach to.

## The bug this investigation found

A wheel built before 2026-09-14 contained **68 files and not one SKILL.md or
PERSONA.md**. Anyone installing from PyPI would have got a Resident with no
procedures and no character.

It failed quietly, which is the part worth remembering. Nothing errored. The
wheel was valid. The Skills pane would have read *"No skills installed"* --
a sentence that looks like a true statement about a working install.

The cause: `skills/` and `personas/` hold Markdown, SVG and JSON with no
`__init__.py`. They are not packages, so `[tool.setuptools.packages.find]`
never saw them, and `package-data` declared only `web/*`.

Fixed in `pyproject.toml` by declaring them, globbed by extension rather than
`**/*` so a stray file dropped in while working cannot silently join a
release.

**How to check it has not regressed.** Do not read the manifest -- build and
ask the thing:

```bash
python -m pip wheel . --no-deps -w /tmp/w
python -m venv /tmp/clean && /tmp/clean/bin/pip install /tmp/w/aworg-*.whl
```

Then boot `create_app` from that environment and confirm `/api/skills`
returns three and `/api/personas` returns six. Any packaging change deserves
this, because the failure mode is silence.

## Metadata (filled in 2026-09-16)

`pyproject.toml` now declares `readme`, `license`, `license-files`, `authors`,
`keywords`, `classifiers` and `urls`. Checked by building a wheel and reading
its `METADATA`: the README is the long description, all three license files
land in `dist-info/licenses/`, and the wheel still carries 3 skills and 6
personas.

Decisions worth knowing:

- **`license = "LicenseRef-AWORG"`.** AWORG is PolyForm Shield 1.0.0 plus
  `ADDITIONAL-TERMS.md`, and Shield has no SPDX identifier, so a LicenseRef is
  the honest expression. PEP 639 forbids a License classifier next to it.
- **The build now needs `setuptools>=77`**, the first release that reads a
  license expression and `license-files`.
- **No author email and no Issues URL.** Both are a choice for Kevin, not a
  default. AWORG does not accept outside contributions, which may or may not
  mean issues are wanted.
- **Relative links in the README will break on PyPI** (`LICENSE`, `docs/`,
  and the like), because PyPI does not resolve them against the repository.
  Worth making them absolute GitHub URLs before the first upload.

## The steps, when ready

1. PyPI account with 2FA. Mandatory for uploads, no exceptions.
2. Credentials. Either an API token, or **Trusted Publishing** -- register
   `kevinnading/aworg` plus a workflow name on PyPI once and GitHub Actions
   uploads with a short-lived OIDC token. No secret to leak or rotate.
   Preferred.
3. ~~Fill in the metadata above and add a LICENSE.~~ Done 2026-09-16.
4. `python -m build`, then `twine check dist/*`.
5. **TestPyPI first.** Upload, install from it into a clean virtualenv, run
   it. This is the step that would have caught the missing skills.
6. `twine upload dist/*`.

## Two things that cannot be undone

- **A name is permanent.** No renaming, no reuse after deletion.
- **A version can never be re-uploaded.** Publish 0.7.0 with a fault and the
  fix is 0.7.1. You can yank, not replace. Worth burning a throwaway version
  on TestPyPI rather than learning this on the real index.

## Local hazards, not shipping ones

- **Bumping the version needs a reinstall.** `pyproject.toml` is the only
  place the version is written, and everything reads it back from the
  installed distribution metadata via `importlib.metadata`. Change it without
  `pip install -e .` and the Environment pane keeps reporting the old number
  -- in the one place an owner would look to check.
- **There are two distributions named `aworg` on the dev machine**: the
  installed `dist-info` and an `aworg.egg-info` in the repo root from an
  editable install. `importlib.metadata` takes whichever comes first on
  `sys.path`. They agree after a reinstall. `*.egg-info/` is gitignored, so
  nothing escapes into the repository.

## One decision left open

`/api/log` is becoming a public contract. Applications the Resident builds
post to it, and those outlive the Aworg that made them. It may deserve a
version of its own, independent of the product's, so the interface can be
reshaped freely at 0.x without breaking every application already written
against it.

# Publishing to PyPI

Notes from investigating what it would take for `pip install aworg` to work
for anyone. Nothing has been published yet; see "Uploading a version". Written 2026-09-14 so that the work
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

**Always build from a cleaned tree.** setuptools' `build/lib` is *additive*:
it is a copy of the package from the last build, and files deleted from the
source since are still sitting in it. A wheel built over a stale one on
2026-09-22 shipped three personas that had been deleted weeks earlier --
`ada`, `pilot` and `resident` -- twenty-one instead of eighteen, with nothing
in the output to say so.

```bash
rm -rf build aworg.egg-info dist
python -m build --wheel --outdir /tmp/w
```

**How to check it has not regressed.** Do not read the manifest, and do not
run the check from inside the checkout -- `python -m aworg` puts the working
directory on `sys.path`, so the first attempt at this silently tested the
source tree rather than the installed wheel and reported a capability that
was not in it. Build, install into a clean virtualenv, and ask from
somewhere else:

```bash
rm -rf build aworg.egg-info dist
python -m build --wheel --outdir /tmp/w
python -m venv /tmp/clean && /tmp/clean/bin/pip install /tmp/w/aworg-*.whl
cd /tmp && AWORG_HOME=/tmp/home /tmp/clean/bin/python -m aworg install
```

As of 2026-09-22 that prints `3 skills`-shaped lines for nothing but personas:
**18 personas installed, `capabilities  nothing shipped`, and no skills**.
Any packaging change deserves this, because the failure mode is silence.

## Metadata (filled in 2026-09-16)

`pyproject.toml` now declares `readme`, `license`, `license-files`, `authors`,
`keywords`, `classifiers` and `urls`. Checked by building a wheel and reading
its `METADATA`: the README is the long description, all three license files
land in `dist-info/licenses/`, and the wheel still carries 3 skills and 6
personas (eighteen since 2026-09-16).

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

## Decided 2026-10-08

- **Uploads are manual**, by Kevin, when a version is ready. No Trusted
  Publishing workflow. An API token from each index, kept on his machine.
- **Author email** `kevinnading@gmail.com`; **Issues** go to GitHub Issues.
  `[project.urls]` is Homepage aworg.com, Documentation aworg.com/learn,
  Source and Issues on GitHub.
- **README links are absolute** GitHub addresses, so they work on PyPI.
- **Development Status 5 - Production/Stable** from 1.0.
- **TestPyPI first** for the first upload -- a separate account at
  test.pypi.org, with its own token.

Checked 2026-10-08 on 1.0.0: `twine check` passes both files, and the wheel
installed into a clean virtualenv and run from outside the checkout reports
1.0.0 and installs the seven personas, no skills, no capabilities.

## Uploading a version

From the repository, on the machine holding the tokens:

```bash
python -m pip install --upgrade build twine
rm -rf build dist aworg.egg-info
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
```

Then install it from TestPyPI into a fresh virtualenv and start it (the
extra index is where its dependencies come from):

```bash
python -m venv /tmp/try && /tmp/try/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ aworg
```

If it runs, the real one:

```bash
python -m twine upload dist/*
```

twine asks for a username and password: the username is `__token__` and the
password is that index's API token.

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


## What each route ships

Not the same thing, on purpose.

| | Personas | Skills | Weather | Chromium Browser |
|---|---|---|---|---|
| wheel (`pip install aworg`) | yes | **no** | **no** | **no** |
| Docker | yes | **no** | **no** | **no** |
| per-OS package | yes | if the build adds them | if the build adds it | if the build adds it, engine included |

Only personas ship. Capabilities live in `capabilities/` and skills in
`skills/`, both at the top of the repository and outside `aworg/`, where
`packages.find` cannot reach them. They are bound for the store; until it
exists, installing one is copying its folder into the matching directory in
an Aworg's home.

Chromium could not have gone in a wheel regardless: it is a hundred and
fifteen megabytes of engine short of working, carrying the engine would mean
per-platform wheels and is past PyPI's size limit, and the source on its own
would give every pip install a Browser capability that is switched on, priced
into every message and broken the first time it is used.

**The per-OS builds** are made by `packaging/build.py`, from any one machine:
`python packaging/build.py` for all four (Windows x64, macOS arm64 and x64,
Linux x64), or name the ones wanted. Each is a standalone CPython 3.12 from
python-build-standalone (the stripped build), AWORG and its dependencies as
that target's wheels, a start file and a README; archives land in
`packaging/dist/`. Python is copied from its own tarball into the archive
rather than unpacked first, because unpacked on Windows its symlinks become
full copies. Only the build for the building machine can be run there.

Beyond what the wheel build does, it does two things:

1. Copy `capabilities/chromium/` into the packaged application's
   `aworg/capabilities/` directory.
2. Fetch that platform's `chrome-headless-shell` from Chrome for Testing into
   `chromium/` inside that folder -- the same archive `install_engine`
   fetches, unpacked the same way.

The installer then seeds it like anything else, because a capability that
arrived with what it declares it needs is not optional any more. Reset puts
it back from the package rather than downloading it again.

Still to settle: whether Google's terms allow redistributing the Chrome for
Testing headless shell inside a package we publish. Fetching it at runtime,
which is what `install_engine` does, raises no such question.

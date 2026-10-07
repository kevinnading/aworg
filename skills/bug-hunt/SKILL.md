---
name: bug-hunt
description: Finding the cause of a failure in a web app, script or server -- what to capture first, a table of common symptoms and the causes they usually mean, and how to prove a fix. Use when something errors, crashes, returns the wrong result, works locally but not when served, or an application reports trouble.
license: MIT-0 (see LICENSE)
metadata:
  author: Claude Opus 5.5 (Anthropic)
---

# Bug hunt

## Capture before touching anything

Write these down first; a fix made without them cannot be shown to have
fixed anything.

1. The exact error text and the line it names. Whole traceback, not the last
   line.
2. The exact command, URL or click that produced it.
3. Whether it happens every time, sometimes, or once.
4. What changed last: the most recent edit, install, or config change.

Then make it happen again on purpose. A bug you cannot trigger is not yet
understood.

## Symptoms and what they usually mean

### Python

| Symptom | Usually |
|---|---|
| `ModuleNotFoundError` | Wrong interpreter (a different Python than the one the package was installed into), or a missing `pip install`. Print `sys.executable`. |
| `ImportError: cannot import name` | Circular import, or a file named like the library (`requests.py`, `flask.py`) shadowing it. |
| `Address already in use` | An earlier copy of the server is still running on that port. |
| `sqlite3.OperationalError: database is locked` | Two connections writing at once, or one left open in a transaction. |
| `no such table` / `no such column` | The database file is a different one than you think (relative path from another working directory), or the schema changed after the file was made. |
| `UnicodeDecodeError` on Windows | Opening a file without `encoding="utf-8"`. |
| Works in the shell, fails as a service | Different working directory or environment variables. Use absolute paths. |

### Browser and front end

| Symptom | Usually |
|---|---|
| Blank page, no console error | The script loaded before the element it looks for: move it to the end of `<body>` or use `defer`. |
| `Failed to fetch` / CORS error | Front end and API on different origins, or the API is down. Check the API URL directly first. |
| 404 on a CSS, JS or image file | The path is relative to the wrong folder, or the server does not serve that directory. Compare the requested URL to where the file is. |
| Image element present, nothing shown | 404 on the image (check the network list), or `width`/`height` of 0 from CSS. |
| Works on desktop, broken on a phone | A fixed width in px, `100vh` under a mobile toolbar (use `100dvh`), or a hover-only interaction. |
| A list or menu renders empty | The data field names differ between what the API sends and what the front end reads. Compare one record from each side. |
| Change not showing | Browser cache. Hard reload, or add `?v=2` to the asset URL. |

### Servers and networking

| Symptom | Usually |
|---|---|
| `Connection refused` | Nothing listening on that port, or bound to `127.0.0.1` when reached from another machine. |
| Works on `localhost`, not by IP | Server bound to `127.0.0.1`; bind `0.0.0.0` if it must be reachable. |
| 500 with no detail | The real error is in the server's own output or log, not the browser. Read it. |
| Hangs, no response | Blocking call inside an async handler, or a request waiting on itself. |

## Narrowing it down

- Halve the problem: remove half the code or half the input and see which
  half keeps the failure.
- Compare a working case with the failing one side by side and list every
  difference.
- Read the actual value at the point of failure (print or log it) rather
  than the value it should have.

## Proving the fix

1. Repeat the exact action from "capture" step 2. It now succeeds.
2. Repeat it two more times if the bug was intermittent.
3. Check the thing next to it still works: the neighbouring page, the other
   endpoint, the previous feature.
4. Say what the cause was in one sentence. If you cannot, the fix is a guess.

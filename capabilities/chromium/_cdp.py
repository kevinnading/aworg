"""Talking to a real browser, with nothing that is not already here.

The Resident can fetch a URL and read the HTML that came back. What it cannot
do is see what that HTML *becomes*: a page whose content arrives from
JavaScript is, to http_request, an empty shell with a script tag in it. So a
Resident building anything modern is building blind, and the owner is its
eyes. That is the single largest thing missing from what it can reach.

This drives Chromium over the Chrome DevTools Protocol -- the same engine and
the same protocol every browser automation tool in the world is built on, and
one WebSocket carrying JSON.

One engine on purpose. Chrome, Chromium and Edge are the same renderer
wearing different policies, and the differences surface exactly where they
are hardest to diagnose: a managed Edge opening a first-run page, a Chrome
with devtools disabled by policy. A capability whose behaviour depends on
which browser a machine happens to have is one that cannot be debugged from
a description of what went wrong.

Nothing is imported that AWORG does not already have. The WebSocket client
below is about a hundred lines because the protocol needs about a hundred
lines, and a capability that made an owner install a package to read a page
would be a capability most owners do not install.

The engine is not shipped inside AWORG -- a browser is the largest thing that
would then be in it -- but it is not left to chance either. `install_engine`
fetches Chrome for Testing's headless shell into `chromium/` inside this
capability's own folder, and that copy is preferred over anything installed.
An owner who already has Chromium or Chrome pays for no download; one who has
neither runs one tool. Either way what runs is Chromium.

Inside the capability, deliberately, and not somewhere safer. A capability is
a folder: deleting it removes what it could do, and an owner who resets and
chooses Capabilities has asked for exactly that. An engine tucked away
elsewhere would survive both and sit in their home as a hundred megabytes
nothing on screen accounts for. The cost of doing it this way is a re-fetch
after a reset, which is one call and announces itself.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import contextlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


#: How long to wait for the browser to answer its debugging port at startup.
START_TIMEOUT = 25
#: How long any one protocol command may take.
COMMAND_TIMEOUT = 45
#: How long to wait for a page's load event before reading it anyway. A page
#: that never fires load is common and usually still readable -- a hung
#: analytics script should not cost the Resident the page it is looking at.
LOAD_TIMEOUT = 20
#: Console lines and failed requests kept per page. Enough to see what went
#: wrong; not so many that one noisy loop fills the reply.
KEEP_MESSAGES = 40
#: Requests kept per page. A modern page makes a few dozen; a chatty one
#: makes hundreds, and the oldest are the ones least likely to be the
#: question.
KEEP_REQUESTS = 150


class BrowserError(Exception):
    """Something the caller should be told in words rather than a traceback."""


# ---------------------------------------------------------------------------
# Finding an engine
# ---------------------------------------------------------------------------

#: Where an engine this capability fetched for itself lives, relative to this
#: file. Looked at first, so that what AWORG downloaded and knows the version
#: of wins over whatever a machine happens to have.
BUNDLED = ("chromium", "engine")

#: The binaries worth looking inside that folder for, most specific first.
ENGINE_NAMES = (
    "chrome-headless-shell.exe", "chrome-headless-shell",
    "headless_shell.exe", "headless_shell",
    "chrome.exe", "chrome", "chromium",
)

WINDOWS_CANDIDATES = (
    r"%ProgramFiles%\Chromium\Application\chrome.exe",
    r"%LocalAppData%\Chromium\Application\chrome.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)

MAC_CANDIDATES = (
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

LINUX_NAMES = (
    "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
)


def engine_root() -> Path:
    """Where a fetched engine lives: inside this capability's own folder.

    So that removing the capability removes the engine. See the note at the
    top of this file.
    """
    return Path(__file__).parent / BUNDLED[0]


def find_engine() -> Path:
    """The browser this capability will drive, or a refusal that says why.

    Order: one the owner named, one bundled with this capability, then
    whatever is installed. The environment variable wins because a machine
    with four browsers on it is a machine where the owner has an opinion.
    """
    named = os.environ.get("AWORG_BROWSER")
    if named:
        if Path(named).is_file():
            return Path(named)
        raise BrowserError(
            f"AWORG_BROWSER is set to {named!r}, and there is no file there."
        )

    for found in bundled_engine():
        return found

    if sys.platform.startswith("win"):
        for candidate in WINDOWS_CANDIDATES:
            path = Path(os.path.expandvars(candidate))
            if path.is_file():
                return path
    elif sys.platform == "darwin":
        for candidate in MAC_CANDIDATES:
            if Path(candidate).is_file():
                return Path(candidate)
    else:
        for name in LINUX_NAMES:
            found = shutil.which(name)
            if found:
                return Path(found)

    raise BrowserError(
        "No Chromium was found to drive. Run install_engine to fetch one into "
        "this capability's own folder -- it is a single download and needs "
        "nothing else -- or install Chromium or Chrome, or set AWORG_BROWSER "
        "to the path of a Chromium binary."
    )


def bundled_engine():
    """Every engine this capability is carrying, best first.

    A generator so that `find_engine` can take the first and
    `install_engine` can ask whether there is one at all, without either of
    them duplicating where to look.
    """
    here = Path(__file__).parent
    for root in (here / folder for folder in BUNDLED):
        if not root.is_dir():
            continue
        for name in ENGINE_NAMES:
            for found in sorted(root.rglob(name)):
                if found.is_file():
                    yield found


# ---------------------------------------------------------------------------
# A WebSocket client, sized to one job
# ---------------------------------------------------------------------------

class WebSocket:
    """Enough of RFC 6455 to hold a conversation with a browser.

    Text frames out, text frames in, masking as a client must, continuation
    frames reassembled, pings answered. No extensions and no compression:
    CDP does not negotiate any, and every line not written here is a line
    that cannot be wrong.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, url: str) -> "WebSocket":
        parts = urlparse(url)
        port = parts.port or 80
        reader, writer = await asyncio.open_connection(parts.hostname, port)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        writer.write(
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parts.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        await writer.drain()
        status = await reader.readline()
        if b"101" not in status:
            writer.close()
            raise BrowserError(
                f"The browser refused the debugging connection: "
                f"{status.decode(errors='replace').strip()}"
            )
        while True:                       # drain the rest of the headers
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        return cls(reader, writer)

    async def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])        # FIN + text
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.writer.write(bytes(header) + masked)
        await self.writer.drain()

    async def recv(self) -> str:
        """One whole message, however many frames it arrived in."""
        chunks: list[bytes] = []
        while True:
            first, second = await self._exact(2)
            fin = first & 0x80
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", await self._exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await self._exact(8))[0]
            data = await self._exact(length) if length else b""
            # A server must not mask, so there is no unmasking to do here.

            if opcode == 0x8:                       # close
                raise BrowserError("The browser closed the debugging connection.")
            if opcode == 0x9:                       # ping
                self.writer.write(bytes([0x8A, 0x80]) + os.urandom(4))
                await self.writer.drain()
                continue
            if opcode == 0xA:                       # pong
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", errors="replace")

    async def _exact(self, count: int) -> bytes:
        return await self.reader.readexactly(count)

    async def close(self) -> None:
        try:
            self.writer.write(bytes([0x88, 0x80]) + os.urandom(4))
            await self.writer.drain()
        except Exception:                                     # noqa: BLE001
            pass
        self.writer.close()


# ---------------------------------------------------------------------------
# The browser itself
# ---------------------------------------------------------------------------

class Browser:
    """One headless browser and one page, kept alive between tool calls.

    Deliberately one page. A Resident that opened tabs it then had to keep
    track of would spend its turns on bookkeeping; every tool here acts on
    "the page", which is the thing it was just looking at.
    """

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.socket: WebSocket | None = None
        self.profile: Path | None = None
        #: The row this engine has in AWORG's process ledger, when it was
        #: given one. That ledger is what lets the next Aworg kill an engine
        #: this one was killed before it could stop -- see start().
        self.record: Any = None
        self.processes: Any = None
        #: Which page we are driving, so a second one can be told apart.
        self.target_id: str = ""
        self.next_id = 0
        self.url = ""
        self.title = ""
        #: What the page said about itself while it was loading: console
        #: lines, page errors, and requests that failed. The most valuable
        #: thing here for a Resident debugging its own application, and the
        #: half of a browser that a screenshot cannot show.
        self.console: list[str] = []
        self.failures: list[str] = []
        #: Every request this page made, in order, with what came back.
        #: Not shown unless asked for -- see the page_requests tool -- because
        #: a list of ninety assets is not what most calls are about.
        self.requests: list[dict[str, Any]] = []
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle ------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self, processes: Any = None) -> str:
        """Launch the engine and attach to its first page.

        `processes` is AWORG's process table, handed in by whichever tool
        started this. Registering there costs nothing and buys the one thing
        atexit cannot: an Aworg that was killed rather than closed leaves an
        engine running, and the next one reads the ledger and clears it out.
        """
        engine = find_engine()
        port = _free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="aworg-browser-"))
        # The headless shell is already headless and rejects the flag that
        # asks a full browser to be; a full Chromium needs it. Told apart by
        # the name Google gives the binary, which is the only thing that
        # distinguishes them from out here.
        flags = [] if "headless-shell" in engine.name or "headless_shell" in engine.name \
            else ["--headless=new"]
        self.process = await asyncio.create_subprocess_exec(
            str(engine),
            *flags,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--mute-audio",
            "--window-size=1280,900",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            # Its own process group, so that everything Chromium starts can
            # be signalled together. Windows has no groups worth using here
            # and gets taskkill /T instead; see _kill_tree.
            **({"start_new_session": True} if os.name != "nt" else {}),
        )

        if processes is not None:
            self.processes = processes
            try:
                self.record = processes.add(
                    self.process,
                    command=f"{engine.name} --remote-debugging-port={port}",
                    label="Chromium (browser capability)",
                    cwd=str(engine.parent),
                )
            except Exception:                                 # noqa: BLE001
                # A ledger that would not take it is not a reason to have no
                # browser. Worse orphan handling, still a working tool.
                self.record = None

        target, self.target_id = await self._wait_for_page(port)
        self.socket = await WebSocket.connect(target)
        self._reader_task = asyncio.ensure_future(self._read_forever())
        for domain in ("Page", "Runtime", "Log", "Network"):
            await self.command(f"{domain}.enable")
        return str(engine)

    async def _wait_for_page(self, port: int) -> tuple[str, str]:
        deadline = asyncio.get_event_loop().time() + START_TIMEOUT
        async with httpx.AsyncClient(timeout=3) as client:
            while asyncio.get_event_loop().time() < deadline:
                if not self.running:
                    raise BrowserError(
                        "Chromium exited immediately. On a server this is "
                        "usually a missing shared library; try running the "
                        "binary by hand to see what it says."
                    )
                try:
                    reply = await client.get(f"http://127.0.0.1:{port}/json/list")
                    for target in reply.json():
                        if target.get("type") == "page":
                            return (target["webSocketDebuggerUrl"],
                                    target.get("id", ""))
                except Exception:                             # noqa: BLE001
                    pass
                await asyncio.sleep(0.2)
        raise BrowserError(
            f"The browser did not answer on its debugging port within "
            f"{START_TIMEOUT} seconds."
        )

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self.socket is not None:
            await self.socket.close()
            self.socket = None
        if self.record is not None and self.processes is not None:
            # Through the table when it owns the row, so the ledger is
            # rewritten and the Living Log hears about it exactly once.
            with contextlib.suppress(Exception):
                await self.processes.stop(self.record.id)
            self.record = None
        if self.process is not None and self.process.returncode is None:
            # The tree, not the process. Chromium's renderer and GPU children
            # outlive their parent on Windows, and nothing in AWORG would
            # ever mention them again.
            _kill_tree(self.process.pid)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                with_kill = getattr(self.process, "kill", None)
                if with_kill is not None:
                    with_kill()
        self.process = None
        if self.profile is not None:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None
        self.url = self.title = ""
        self.console.clear()
        self.failures.clear()

    # -- protocol -------------------------------------------------------

    async def _read_forever(self) -> None:
        """One reader for the socket, because two would race for frames."""
        while self.socket is not None:
            try:
                message = json.loads(await self.socket.recv())
            except asyncio.CancelledError:
                raise
            except Exception as exc:                          # noqa: BLE001
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(BrowserError(str(exc)))
                self._pending.clear()
                return
            if "id" in message:
                future = self._pending.pop(message["id"], None)
                if future is not None and not future.done():
                    future.set_result(message)
            else:
                self._note(message)

    def _note(self, message: dict) -> None:
        """Keep the few events worth telling the Resident about."""
        method = message.get("method", "")
        params = message.get("params") or {}
        if method == "Runtime.consoleAPICalled":
            args = " ".join(
                str(arg.get("value", arg.get("description", "")))
                for arg in params.get("args", [])
            )
            self._remember(self.console, f"{params.get('type', 'log')}: {args}")
        elif method == "Runtime.exceptionThrown":
            detail = params.get("exceptionDetails") or {}
            text = (detail.get("exception") or {}).get("description") \
                or detail.get("text") or "script error"
            self._remember(self.console, f"error: {text.splitlines()[0]}")
        elif method == "Log.entryAdded":
            entry = params.get("entry") or {}
            if entry.get("level") in ("error", "warning"):
                self._remember(
                    self.console, f"{entry['level']}: {entry.get('text', '')}"
                )
        elif method == "Network.requestWillBeSent":
            request = params.get("request") or {}
            self.requests.append({
                "id": params.get("requestId"),
                "method": request.get("method", "GET"),
                "url": request.get("url", ""),
                "type": params.get("type", ""),
                "status": None,
                "mime": "",
                "bytes": None,
                "error": "",
            })
            del self.requests[:-KEEP_REQUESTS]
        elif method == "Network.loadingFailed":
            self._against(params.get("requestId"),
                          error=params.get("errorText", "failed"))
            if not params.get("canceled"):
                self._remember(
                    self.failures,
                    f"{params.get('type', 'request')} failed: "
                    f"{params.get('errorText', 'unknown error')}"
                )
        elif method == "Network.loadingFinished":
            self._against(params.get("requestId"),
                          bytes=params.get("encodedDataLength"))
        elif method == "Network.responseReceived":
            response = params.get("response") or {}
            self._against(
                params.get("requestId"),
                status=response.get("status"),
                mime=response.get("mimeType", ""),
            )
            if response.get("status", 0) >= 400:
                self._remember(
                    self.failures,
                    f"{response['status']} {response.get('url', '')[:120]}"
                )

    def _against(self, request_id: Any, **fields: Any) -> None:
        """Fill in what came back, on the request that asked for it.

        Searched from the end because the answer to a request almost always
        arrives while it is still the most recent thing, and a page with a
        hundred and fifty of them should not be scanned from the front on
        every event.
        """
        if not request_id:
            return
        for record in reversed(self.requests):
            if record["id"] == request_id:
                record.update({k: v for k, v in fields.items() if v is not None})
                return

    @staticmethod
    def _remember(where: list[str], line: str) -> None:
        if line not in where:
            where.append(line)
        del where[:-KEEP_MESSAGES]

    async def command(self, method: str, params: dict | None = None) -> dict:
        if self.socket is None:
            raise BrowserError("The browser is not open.")
        async with self._lock:
            self.next_id += 1
            message_id = self.next_id
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[message_id] = future
            await self.socket.send(json.dumps(
                {"id": message_id, "method": method, "params": params or {}}
            ))
        try:
            reply = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError as exc:
            self._pending.pop(message_id, None)
            raise BrowserError(f"{method} did not answer in {COMMAND_TIMEOUT}s.") from exc
        if "error" in reply:
            raise BrowserError(
                f"{method} failed: {reply['error'].get('message', reply['error'])}"
            )
        return reply.get("result", {})

    # -- the things the tools actually ask for --------------------------

    async def emulate(
        self,
        width: int | None = None,
        height: int | None = None,
        mobile: bool = False,
        dark: bool | None = None,
    ) -> None:
        """Make the page believe it is somewhere else.

        A phone-sized viewport is not a narrow window: `mobile` also sets the
        touch flag and the device pixel ratio, so a page that asks whether it
        is on a touch device gets the answer the emulation implies rather
        than the one the desktop engine would give.
        """
        if width or height:
            await self.command("Emulation.setDeviceMetricsOverride", {
                "width": int(width or 1280),
                "height": int(height or 900),
                "deviceScaleFactor": 2 if mobile else 1,
                "mobile": bool(mobile),
            })
            # maxTouchPoints must be 1-16 even when the answer is "none":
            # the protocol refuses 0, and passing it made every switch back
            # to a desktop viewport fail.
            await self.command("Emulation.setTouchEmulationEnabled", {
                "enabled": bool(mobile),
                "maxTouchPoints": 5 if mobile else 1,
            })
        if dark is not None:
            await self.command("Emulation.setEmulatedMedia", {
                "features": [
                    {"name": "prefers-color-scheme",
                     "value": "dark" if dark else "light"},
                ],
            })

    async def navigate(self, url: str, settle: float = 0.6) -> None:
        self.console.clear()
        self.failures.clear()
        self.requests.clear()
        loaded = asyncio.get_event_loop().create_future()

        # Page.loadEventFired arrives as an event, and events go to _note.
        # Rather than teach _note about futures, the wait is done by polling
        # readyState, which is also true for pages that never fire load.
        await self.command("Page.navigate", {"url": url})
        deadline = asyncio.get_event_loop().time() + LOAD_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            state = await self.evaluate("document.readyState")
            if state in ("interactive", "complete"):
                break
            await asyncio.sleep(0.15)
        del loaded
        # A moment more for the scripts that run after load and write the
        # page the owner would actually see.
        await asyncio.sleep(settle)
        self.url = await self.evaluate("location.href") or url
        self.title = await self.evaluate("document.title") or ""

    async def popup(self) -> str | None:
        """A page this click opened in a new tab, if there is one.

        Asked for rather than watched: attaching to every target that opens
        would mean holding several pages and deciding which one the Resident
        means, which is tab management. This answers the question that
        actually comes up -- something opened, do you want to follow it --
        and the answer is one URL.
        """
        try:
            targets = await self.command("Target.getTargets")
        except BrowserError:
            return None
        for info in targets.get("targetInfos", []):
            if (
                info.get("type") == "page"
                and info.get("targetId") != self.target_id
                and (info.get("url") or "") not in ("", "about:blank")
            ):
                return info["url"]
        return None

    async def follow(self, url: str) -> None:
        """Go to a page that opened in a tab, in the one page we drive.

        The tab itself is left behind and closed: two live pages is the
        thing this capability deliberately does not have, and a Resident
        that has been shown the popup's content has what it opened it for.
        """
        try:
            targets = await self.command("Target.getTargets")
            for info in targets.get("targetInfos", []):
                if (
                    info.get("type") == "page"
                    and info.get("targetId") != self.target_id
                    and info.get("url") == url
                ):
                    await self.command("Target.closeTarget",
                                       {"targetId": info["targetId"]})
        except BrowserError:
            pass
        await self.navigate(url)

    async def evaluate(self, expression: str):
        """Run JavaScript in the page and bring back a plain value."""
        result = await self.command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        })
        details = result.get("exceptionDetails")
        if details:
            text = (details.get("exception") or {}).get("description") \
                or details.get("text", "script error")
            raise BrowserError(text.splitlines()[0])
        return (result.get("result") or {}).get("value")


def _kill_tree(pid: int) -> None:
    """Kill a process and everything it started.

    Both halves are best-effort and silent: this runs while something is
    already being torn down, and a tidy-up that raises is worse than one
    that misses.
    """
    if os.name == "nt":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return
    with contextlib.suppress(Exception):
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    with contextlib.suppress(Exception):
        os.kill(pid, signal.SIGTERM)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


#: One browser per Aworg, held here because an installed capability runs in
#: AWORG's own process and can therefore keep something alive between calls.
#: That is the whole reason a page stays open from one tool to the next.
_browser = Browser()


async def browser(start_if_needed: bool = True, processes: Any = None) -> Browser:
    if not _browser.running:
        if not start_if_needed:
            raise BrowserError("No page is open. Use open_page first.")
        await _browser.start(processes)
    return _browser


def _kill_on_exit() -> None:
    """Never leave a headless browser behind.

    An orphaned engine holds a profile directory and a few hundred megabytes
    of memory, and it is invisible -- there is no window to notice. atexit
    rather than the process ledger because this one belongs to AWORG itself
    rather than to something the Resident started.
    """
    process = _browser.process
    if process is not None and process.returncode is None:
        _kill_tree(process.pid)
    if _browser.profile is not None:
        shutil.rmtree(_browser.profile, ignore_errors=True)


atexit.register(_kill_on_exit)


async def unload() -> None:
    """Called by AWORG before it drops this capability's modules to load a
    new version. The engine is closed here because nothing after the reload
    could reach it: the new modules start with a fresh, empty Browser, and
    this one would go on running with nobody holding its handle. Safe to
    call more than once, and every tool module that imported it may be
    asked to."""
    if _browser.running or _browser.profile is not None:
        await _browser.stop()
    atexit.unregister(_kill_on_exit)

"""Talking to a real browser, with nothing that is not already here.

The Resident can fetch a URL and read the HTML that came back. What it cannot
do is see what that HTML *becomes*: a page whose content arrives from
JavaScript is, to http_request, an empty shell with a script tag in it. So a
Resident building anything modern is building blind, and the owner is its
eyes. That is the single largest thing missing from what it can reach.

This drives a browser that is already on the machine -- Chrome, Chromium or
Edge -- over the Chrome DevTools Protocol. CDP is how every one of them is
automated; the protocol is one WebSocket carrying JSON.

Nothing is imported that AWORG does not already have. The WebSocket client
below is about a hundred lines because the protocol needs about a hundred
lines, and a capability that made an owner install a package to read a page
would be a capability most owners do not install. The engine itself is not
bundled either: a browser is a hundred megabytes, most machines have three,
and a capability that shipped its own would be shipping the largest thing in
AWORG to save a lookup in Program Files.

An engine *may* be bundled, though, and that is looked for first: drop a
Chromium into `chromium/` inside this capability's folder and it is used in
preference to anything installed. That is what makes this capability
self-contained on a machine with no browser at all, without making every
other machine pay for it.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
from pathlib import Path
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


class BrowserError(Exception):
    """Something the caller should be told in words rather than a traceback."""


# ---------------------------------------------------------------------------
# Finding an engine
# ---------------------------------------------------------------------------

#: Where a bundled engine goes, relative to this capability's own folder.
#: Looked at first, so that a capability carrying its own Chromium works on a
#: machine with none installed.
BUNDLED = ("chromium", "chrome-headless-shell", "engine")

WINDOWS_CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Chromium\Application\chrome.exe",
)

MAC_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

LINUX_NAMES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable",
)


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

    here = Path(__file__).parent
    for folder in BUNDLED:
        root = here / folder
        if not root.is_dir():
            continue
        for name in ("chrome.exe", "headless_shell.exe", "chrome",
                     "headless_shell", "chrome-headless-shell"):
            for found in root.rglob(name):
                if found.is_file():
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
        "No browser was found to drive. Install Chrome, Chromium or Edge, or "
        "set AWORG_BROWSER to the path of one, or put a Chromium in the "
        "chromium/ folder inside this capability."
    )


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
        self.next_id = 0
        self.url = ""
        self.title = ""
        #: What the page said about itself while it was loading: console
        #: lines, page errors, and requests that failed. The most valuable
        #: thing here for a Resident debugging its own application, and the
        #: half of a browser that a screenshot cannot show.
        self.console: list[str] = []
        self.failures: list[str] = []
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle ------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> str:
        """Launch the engine and attach to its first page."""
        engine = find_engine()
        port = _free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="aworg-browser-"))
        self.process = await asyncio.create_subprocess_exec(
            str(engine),
            "--headless=new",
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
        )

        target = await self._wait_for_page(port)
        self.socket = await WebSocket.connect(target)
        self._reader_task = asyncio.ensure_future(self._read_forever())
        for domain in ("Page", "Runtime", "Log", "Network"):
            await self.command(f"{domain}.enable")
        return str(engine)

    async def _wait_for_page(self, port: int) -> str:
        deadline = asyncio.get_event_loop().time() + START_TIMEOUT
        async with httpx.AsyncClient(timeout=3) as client:
            while asyncio.get_event_loop().time() < deadline:
                if not self.running:
                    raise BrowserError(
                        "The browser exited immediately. On a server this is "
                        "usually a missing library; try running it by hand to "
                        "see what it says."
                    )
                try:
                    reply = await client.get(f"http://127.0.0.1:{port}/json/list")
                    for target in reply.json():
                        if target.get("type") == "page":
                            return target["webSocketDebuggerUrl"]
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
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
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
        elif method == "Network.loadingFailed":
            if not params.get("canceled"):
                self._remember(
                    self.failures,
                    f"{params.get('type', 'request')} failed: "
                    f"{params.get('errorText', 'unknown error')}"
                )
        elif method == "Network.responseReceived":
            response = params.get("response") or {}
            if response.get("status", 0) >= 400:
                self._remember(
                    self.failures,
                    f"{response['status']} {response.get('url', '')[:120]}"
                )

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

    async def navigate(self, url: str, settle: float = 0.6) -> None:
        self.console.clear()
        self.failures.clear()
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


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


#: One browser per Aworg, held here because an installed capability runs in
#: AWORG's own process and can therefore keep something alive between calls.
#: That is the whole reason a page stays open from one tool to the next.
_browser = Browser()


async def browser(start_if_needed: bool = True) -> Browser:
    if not _browser.running:
        if not start_if_needed:
            raise BrowserError("No page is open. Use open_page first.")
        await _browser.start()
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
        try:
            process.kill()
        except Exception:                                     # noqa: BLE001
            pass
    if _browser.profile is not None:
        shutil.rmtree(_browser.profile, ignore_errors=True)


atexit.register(_kill_on_exit)

"""Search the web, with no key and no account.

DuckDuckGo publishes no free search API, so this reads the plain HTML results
page a browser without JavaScript is given -- the same page, the same
results. It is unofficial: heavy use gets rate-limited, and a change to that
page breaks the parser here, which then says so rather than returning
nothing.

Only the standard library and httpx, which AWORG already depends on.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from aworg.tools.base import ToolContext, ToolError, ToolResult


NAME = "web_search"

DESCRIPTION = (
    "Search the web and get back titles, addresses and short snippets of the "
    "top results. Read a result's page with a tool that fetches pages."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to search for."},
        "count": {
            "type": "integer",
            "description": "How many results, 1 to 20. Defaults to 8.",
        },
        "region": {
            "type": "string",
            "description": (
                "A DuckDuckGo region code to bias results, like 'us-en', "
                "'uk-en' or 'de-de'. Defaults to no region."
            ),
        },
    },
    "required": ["query"],
}

ENDPOINT = "https://html.duckduckgo.com/html/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
}


class _Results(HTMLParser):
    """Pulls (title, href, snippet) out of the results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._field: str | None = None
        self._current: dict[str, str] | None = None
        self.blocked = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "anomaly-modal" in " ".join(classes) or a.get("id") == "challenge-form":
            self.blocked = True
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": _real_url(a.get("href", "")), "snippet": ""}
            self.results.append(self._current)
            self._field = "title"
        elif tag in ("a", "div") and "result__snippet" in classes and self._current is not None:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div") and self._field:
            self._field = None

    def handle_data(self, data):
        if self._field and self._current is not None:
            self._current[self._field] += data


def _real_url(href: str) -> str:
    """Result links go through DuckDuckGo's redirect; take the target out."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


async def run(context: ToolContext, query: str = "", count: int = 8, region: str = "") -> ToolResult:
    query = str(query).strip()
    if not query:
        raise ToolError("No query was given.")
    try:
        count = max(1, min(20, int(count or 8)))
    except (TypeError, ValueError):
        count = 8

    form = {"q": query}
    if region:
        form["kl"] = str(region).strip()
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            response = await client.post(ENDPOINT, data=form)
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach DuckDuckGo: {exc}") from None

    if response.status_code in (202, 403, 429):
        raise ToolError(
            f"DuckDuckGo refused the search (HTTP {response.status_code}), which "
            "it does when searches come too fast. Wait a minute and try again."
        )
    if response.status_code != 200:
        raise ToolError(f"DuckDuckGo answered HTTP {response.status_code}.")

    parser = _Results()
    parser.feed(response.text)
    if parser.blocked:
        raise ToolError(
            "DuckDuckGo asked for a human check instead of answering, which it "
            "does when searches come too fast. Wait a minute and try again."
        )
    results = [
        {k: " ".join(v.split()) for k, v in r.items()}
        for r in parser.results
        if r["url"].startswith("http") and "duckduckgo.com/y.js" not in r["url"]
    ][:count]
    if not results:
        if "result__a" not in response.text and "No results" not in response.text:
            raise ToolError(
                "DuckDuckGo's results page came back in a shape this tool does "
                "not recognise, so nothing could be read from it."
            )
        return ToolResult(text=f"No results for {query!r}.", summary="no results")

    lines = [f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}" for i, r in enumerate(results, 1)]
    return ToolResult(
        text=f"Results for {query!r}:\n\n" + "\n\n".join(lines),
        summary=f"{len(results)} results",
    )

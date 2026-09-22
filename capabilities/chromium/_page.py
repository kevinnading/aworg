"""What to read off a page, and how to say it back.

Shared by every tool here so that a page described after a click reads the
same as one described after opening it -- the Resident should not have to
learn two formats for the same fact.

Text first, deliberately. A screenshot costs thousands of tokens and a model
reads it worse than it reads words; what a Resident checking its own work
needs to know is what the page says, which controls exist, and what the
console complained about. Screenshots stay available for the one case they
win at, which is showing the owner something.
"""

from __future__ import annotations

#: How much page text to hand back. Generous enough for a documentation page,
#: bounded because some pages are books.
TEXT_LIMIT = 6000
#: Links and controls are listed rather than counted -- a Resident cannot
#: click what it has not been told exists -- but a navigation-heavy page can
#: carry hundreds.
MAX_LINKS = 40
MAX_CONTROLS = 30

#: Pulled out of the page in one round trip. innerText rather than textContent
#: because innerText is what a person would see: it honours display:none and
#: collapses whitespace the way the layout does.
EXTRACT = """
(() => {
  const clean = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const main = document.querySelector("main, article, [role=main]") || document.body;
  const links = [...document.querySelectorAll("a[href]")]
    .map((a) => ({ text: clean(a.innerText).slice(0, 80), href: a.href }))
    .filter((l) => l.text || l.href);
  const controls = [...document.querySelectorAll(
      "button, input, select, textarea, [role=button], [contenteditable=true]")]
    .map((el) => {
      const label = clean(
        el.getAttribute("aria-label") || el.getAttribute("placeholder") ||
        el.innerText || el.value || el.name || el.id || "");
      const kind = el.tagName.toLowerCase() +
        (el.type ? `[${el.type}]` : "");
      const where = el.id ? `#${el.id}` : (el.name ? `[name="${el.name}"]` : "");
      return { kind, label: label.slice(0, 60), selector: where };
    });
  return {
    title: document.title || "",
    url: location.href,
    text: (main.innerText || "").replace(/\\n{3,}/g, "\\n\\n").trim(),
    links, controls,
    forms: document.forms.length,
  };
})()
"""


async def extract(browser) -> dict:
    found = await browser.evaluate(EXTRACT)
    return found if isinstance(found, dict) else {}


def describe(browser, page: dict, want_links: bool = True) -> str:
    """One page, in the shape every tool here reports it.

    The console and the failed requests come last and only when there are
    any. They are the half of a browser that http_request could never give
    the Resident, and the reason this capability is worth its tokens: a page
    that renders perfectly and throws in the console is the exact case that
    was previously invisible.
    """
    text = page.get("text") or ""
    clipped = len(text) > TEXT_LIMIT
    if clipped:
        text = text[:TEXT_LIMIT].rstrip()

    lines = [f"{page.get('title') or '(no title)'} -- {page.get('url') or browser.url}"]
    lines.append("")
    lines.append(text or "(the page has no readable text)")
    if clipped:
        lines.append(f"... [first {TEXT_LIMIT} characters of the page text]")

    if want_links:
        links = page.get("links") or []
        if links:
            lines.append("")
            lines.append(f"Links ({len(links)}):")
            for link in links[:MAX_LINKS]:
                lines.append(f"  {link.get('text') or '(no text)'} -> {link.get('href')}")
            if len(links) > MAX_LINKS:
                lines.append(f"  ... and {len(links) - MAX_LINKS} more")

        controls = page.get("controls") or []
        if controls:
            lines.append("")
            lines.append(f"Controls ({len(controls)}):")
            for control in controls[:MAX_CONTROLS]:
                where = control.get("selector") or ""
                lines.append(
                    f"  {control.get('kind')} {control.get('label') or ''}"
                    + (f"  {where}" if where else "")
                )
            if len(controls) > MAX_CONTROLS:
                lines.append(f"  ... and {len(controls) - MAX_CONTROLS} more")

    if browser.console:
        lines.append("")
        lines.append("Console:")
        lines.extend(f"  {line}" for line in browser.console)
    if browser.failures:
        lines.append("")
        lines.append("Requests that failed:")
        lines.extend(f"  {line}" for line in browser.failures)
    return "\n".join(lines)


def summary(browser, page: dict) -> str:
    """The one line the Activities panel gets."""
    trouble = len(browser.console) + len(browser.failures)
    title = (page.get("title") or browser.url or "page")[:40]
    return f"{title}" + (f", {trouble} problem(s)" if trouble else "")

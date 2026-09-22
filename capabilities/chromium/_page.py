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
  // Handles. Kept on the page rather than derived from a selector, so that
  // "that one" survives two buttons with the same words on them. The array
  // is rebuilt on every read and dies with the document, which is what makes
  // a stale ref a stale ref rather than a wrong click.
  window.__aworg_refs = [];
  const handle = (el) => (window.__aworg_refs.push(el) - 1);
  const links = [...document.querySelectorAll("a[href]")]
    .map((a) => ({ text: clean(a.innerText).slice(0, 80), href: a.href,
                   ref: handle(a),
                   blank: a.target === "_blank" }))
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
      return { kind, label: label.slice(0, 60), selector: where,
               ref: handle(el), disabled: !!el.disabled };
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


#: The page's shape rather than its words: what a screen reader would walk.
#: Roles are taken from the element's own role attribute where it has one and
#: inferred from the tag where it does not -- the same inference a browser
#: makes, done here because reading it out of Chromium's accessibility tree
#: would mean resolving backend node ids for every entry to get a handle
#: back, and this is the half that is actually useful.
OUTLINE = """
(() => {
  const clean = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const ROLES = {
    MAIN: "main", NAV: "navigation", HEADER: "banner", FOOTER: "contentinfo",
    ASIDE: "complementary", FORM: "form", SECTION: "region",
    ARTICLE: "article", H1: "heading", H2: "heading", H3: "heading",
    H4: "heading", H5: "heading", H6: "heading", BUTTON: "button",
    A: "link", INPUT: "textbox", SELECT: "combobox", TEXTAREA: "textbox",
    UL: "list", OL: "list", LI: "listitem", TABLE: "table", IMG: "image",
    DIALOG: "dialog",
  };
  window.__aworg_refs = window.__aworg_refs || [];
  const out = [];
  const walk = (node, depth) => {
    if (depth > 12) return;
    for (const el of node.children) {
      const role = el.getAttribute("role") || ROLES[el.tagName] || "";
      const hidden = el.hidden || el.getAttribute("aria-hidden") === "true";
      if (!hidden && role) {
        const name = clean(
          el.getAttribute("aria-label") ||
          (el.tagName.startsWith("H") && el.tagName.length === 2
            ? el.innerText : "") ||
          el.getAttribute("alt") || el.getAttribute("title") ||
          (el.children.length === 0 ? el.innerText : "")
        ).slice(0, 70);
        const ref = window.__aworg_refs.push(el) - 1;
        out.push({ depth, role, name,
                   tag: el.tagName.toLowerCase(), ref });
      }
      walk(el, hidden || !role ? depth : depth + 1);
    }
  };
  walk(document.body, 0);
  return out;
})()
"""

#: A page's structure is long before it is useful. This is about two screens.
MAX_OUTLINE = 120


async def outline(browser) -> list:
    found = await browser.evaluate(OUTLINE)
    return found if isinstance(found, list) else []


def describe_outline(rows: list) -> str:
    """The shape of the page, indented the way it is nested."""
    if not rows:
        return "(nothing with a role on this page)"
    lines = []
    for row in rows[:MAX_OUTLINE]:
        name = row.get("name") or ""
        lines.append(
            "  " * min(int(row.get("depth") or 0), 10)
            + f"[ref_{row.get('ref')}] {row.get('role')}"
            + (f" {name!r}" if name else "")
        )
    if len(rows) > MAX_OUTLINE:
        lines.append(f"... and {len(rows) - MAX_OUTLINE} more")
    return "\n".join(lines)


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
                lines.append(
                    f"  [ref_{link.get('ref')}] {link.get('text') or '(no text)'}"
                    f" -> {link.get('href')}"
                    + ("  (opens a new tab)" if link.get("blank") else "")
                )
            if len(links) > MAX_LINKS:
                lines.append(f"  ... and {len(links) - MAX_LINKS} more")

        controls = page.get("controls") or []
        if controls:
            lines.append("")
            lines.append(f"Controls ({len(controls)}):")
            for control in controls[:MAX_CONTROLS]:
                where = control.get("selector") or ""
                lines.append(
                    f"  [ref_{control.get('ref')}] {control.get('kind')} "
                    f"{control.get('label') or ''}"
                    + (f"  {where}" if where else "")
                    + ("  (disabled)" if control.get("disabled") else "")
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

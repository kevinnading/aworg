"""Run JavaScript in the open page and bring back what it returns.

The debugging tool. read_page says what a page shows; this says what it *is*
-- the value of a variable, what a function returns when called directly, the
computed style of an element, whether the thing that should have been in
localStorage is in localStorage. A Resident that has built something and
cannot work out why it misbehaves is usually one question away from knowing,
and the question is almost never answerable from the rendered text.

It runs arbitrary code in the page, which is what it is for. That page is
whatever the Resident opened; nothing here reaches AWORG or the machine, and
anything that did would be reaching it through the browser's own sandbox.
"""

from __future__ import annotations

import json

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser


NAME = "page_eval"

DESCRIPTION = (
    "Run JavaScript in the page that is open and get the result back. For "
    "finding out what a page is doing rather than what it shows: inspect a "
    "variable, call a function, read an element's computed style, check "
    "localStorage. A single expression is the result; for several statements "
    "end with `return`. await works."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "script": {
            "type": "string",
            "description": (
                "The JavaScript to run. A single expression comes back as "
                "its value -- 'document.querySelectorAll(\"li\").length', "
                "'getComputedStyle(document.body).backgroundColor'. Several "
                "statements run as a function body, so end with an explicit "
                "`return`. Ask for a small, specific value rather than a "
                "whole object graph."
            ),
        },
    },
    "required": ["script"],
}

#: A result is JSON on the way back, and a page can hand over something
#: enormous -- `document.body.innerHTML` on a long page, or an array of every
#: element. Cut with an explanation rather than refused, so the model can
#: narrow the question instead of guessing what happened.
MAX_RESULT = 6000


async def run(context: ToolContext, script: str) -> ToolResult:
    script = (script or "").strip()
    if not script:
        raise ToolError("page_eval needs some JavaScript to run.")

    try:
        page_browser = await browser(start_if_needed=False)
        # One expression is evaluated as itself; anything longer runs as a
        # function body, where a `return` is what comes back. Working out
        # where to insert one automatically would mean parsing JavaScript,
        # and a parser here would be wrong on the day it mattered.
        value = await page_browser.evaluate(
            script if _is_expression(script) else f"(() => {{ {script} }})()"
        )
    except BrowserError as exc:
        # A script error is the answer to the question, not a failure of the
        # tool -- "x is not defined" is exactly what the Resident needed to
        # know -- but it is flagged so the model does not read it as a value.
        raise ToolError(f"The script did not run: {exc}") from exc

    try:
        shown = json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        shown = str(value)
    clipped = len(shown) > MAX_RESULT
    if clipped:
        shown = shown[:MAX_RESULT].rstrip() + (
            f"\n... [cut at {MAX_RESULT} characters; ask for something "
            "narrower]"
        )

    return ToolResult(
        text=shown if shown.strip() not in ("null", "") else
        "The script ran and returned nothing (undefined or null)."
        + ("" if _is_expression(script) else
           " Several statements run as a function body -- add a `return` if "
           "you meant to get a value back."),
        payload=value,
        summary=_summarise(value),
    )


def _is_expression(script: str) -> bool:
    """Whether this can be evaluated as-is rather than wrapped in a body.

    Crude on purpose: anything with a statement keyword or a semicolon in it
    goes in a function body, everything else is evaluated directly so that a
    bare object literal is an object rather than a block.
    """
    if ";" in script or "\n" in script:
        return False
    first = script.split(" ", 1)[0]
    return first not in (
        "const", "let", "var", "return", "if", "for", "while", "function",
        "class", "try", "switch", "do",
    )


def _summarise(value) -> str:
    if isinstance(value, (list, tuple)):
        return f"{len(value)} item(s)"
    if isinstance(value, dict):
        return f"{len(value)} key(s)"
    if value is None:
        return "nothing"
    text = str(value)
    return text[:40] + ("…" if len(text) > 40 else "")

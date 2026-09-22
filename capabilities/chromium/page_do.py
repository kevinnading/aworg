"""Do things on the open page: click, type, press, scroll, wait."""

from __future__ import annotations

import asyncio
import json

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser
from ._page import describe, extract, summary


NAME = "page_do"

DESCRIPTION = (
    "Act on the page that is open: click something, type into a field, press "
    "a key, scroll, or wait for something to appear. Takes a list of steps "
    "and does them in order, then reads the page back to you -- so a whole "
    "form is one call rather than six. Elements are found by CSS selector or "
    "by the text on them."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "description": "The steps to carry out, in order.",
            "items": {
                "type": "object",
                "properties": {
                    "do": {
                        "type": "string",
                        "description": (
                            "click, type, press, scroll, or wait."
                        ),
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector of the element to act on, for "
                            "click, type and wait."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "For click: the visible text to find it by, "
                            "instead of a selector. For type: what to type. "
                            "For press: the key, such as Enter or Tab."
                        ),
                    },
                    "seconds": {
                        "type": "number",
                        "description": "For wait: how long, up to 15.",
                    },
                    "to": {
                        "type": "string",
                        "description": (
                            "For scroll: top, bottom, or a selector to bring "
                            "into view."
                        ),
                    },
                },
                "required": ["do"],
            },
        },
        "links": {
            "type": "boolean",
            "description": (
                "Include links and controls in what comes back. Defaults to "
                "true."
            ),
        },
    },
    "required": ["steps"],
}

MAX_STEPS = 20
MAX_WAIT = 15
#: Keys worth naming. Anything else is typed as a character, which is what a
#: single-character `text` means.
KEYS = {
    "enter": ("Enter", "Enter", 13, "\r"),
    "tab": ("Tab", "Tab", 9, "\t"),
    "escape": ("Escape", "Escape", 27, ""),
    "backspace": ("Backspace", "Backspace", 8, ""),
    "delete": ("Delete", "Delete", 46, ""),
    "arrowup": ("ArrowUp", "ArrowUp", 38, ""),
    "arrowdown": ("ArrowDown", "ArrowDown", 40, ""),
    "arrowleft": ("ArrowLeft", "ArrowLeft", 37, ""),
    "arrowright": ("ArrowRight", "ArrowRight", 39, ""),
}

#: Clicking and typing are done in the page rather than by aiming a mouse at
#: coordinates. A coordinate needs a screenshot, a screenshot costs thousands
#: of tokens, and the result is wrong the moment the layout moves. A
#: selector or the words on the button survive both.
CLICK = """
(sel, label) => {
  const pick = () => {
    if (sel) return document.querySelector(sel);
    const wanted = (label || "").trim().toLowerCase();
    const candidates = [...document.querySelectorAll(
      "button, a, input[type=submit], input[type=button], [role=button], label")];
    return candidates.find((el) =>
      ((el.innerText || el.value || "").trim().toLowerCase() === wanted)) ||
      candidates.find((el) =>
        ((el.innerText || el.value || "").trim().toLowerCase().includes(wanted)));
  };
  const el = pick();
  if (!el) return "nothing matched";
  el.scrollIntoView({ block: "center" });
  el.click();
  return "";
}
"""

#: Setting .value directly does not tell a framework anything happened, so
#: the native setter is called and the events a real keystroke would raise
#: are dispatched. Without this, React and friends keep their own state and
#: the field reverts the moment anything re-renders.
TYPE = """
(sel, value) => {
  const el = sel ? document.querySelector(sel) : document.activeElement;
  if (!el) return "nothing matched";
  el.focus();
  if (el.isContentEditable) {
    el.textContent = value;
  } else {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) setter.set.call(el, value);
    else el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return "";
}
"""

SCROLL = """
(where) => {
  if (where === "top") { window.scrollTo(0, 0); return ""; }
  if (where === "bottom") { window.scrollTo(0, document.body.scrollHeight); return ""; }
  const el = document.querySelector(where);
  if (!el) return "nothing matched";
  el.scrollIntoView({ block: "center" });
  return "";
}
"""


async def run(
    context: ToolContext,
    steps: list | None = None,
    links: bool = True,
) -> ToolResult:
    if not isinstance(steps, list) or not steps:
        raise ToolError(
            "page_do needs a list of steps, each with a 'do' of click, type, "
            "press, scroll or wait."
        )
    if len(steps) > MAX_STEPS:
        raise ToolError(f"page_do takes at most {MAX_STEPS} steps at a time.")

    done: list[str] = []
    try:
        page_browser = await browser(start_if_needed=False)
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ToolError(f"Step {index} is not an object.")
            await _step(page_browser, index, step, done, context)
        page = await extract(page_browser)
    except BrowserError as exc:
        raise ToolError(
            (f"Did: {'; '.join(done)}. Then it failed: " if done else "") + str(exc)
        ) from exc

    return ToolResult(
        text="Did: " + "; ".join(done) + "\n\n" + describe(page_browser, page, links),
        payload={"did": done, "page": page},
        summary=f"{len(done)} step(s), " + summary(page_browser, page),
    )


async def _step(page_browser, index, step, done, context) -> None:
    action = str(step.get("do", "")).strip().lower()
    selector = step.get("selector")
    text = step.get("text")

    if context.activity is not None:
        context.activity.progress = f"step {index}: {action}"

    if action == "click":
        if not selector and not text:
            raise ToolError(f"Step {index}: click needs a selector or text.")
        problem = await _call(page_browser, CLICK, selector, text)
        if problem:
            raise ToolError(
                f"Step {index}: nothing on the page matches "
                f"{selector or text!r}. Use read_page to see what is there."
            )
        done.append(f"clicked {selector or text!r}")
        # A click is usually meant to change something, and what it changed
        # is the point of the call.
        await asyncio.sleep(0.4)

    elif action == "type":
        if text is None:
            raise ToolError(f"Step {index}: type needs text.")
        problem = await _call(page_browser, TYPE, selector, text)
        if problem:
            raise ToolError(
                f"Step {index}: nothing on the page matches {selector!r}."
            )
        done.append(f"typed into {selector or 'the focused field'}")

    elif action == "press":
        key = str(text or "").strip()
        if not key:
            raise ToolError(f"Step {index}: press needs a key, such as Enter.")
        await _press(page_browser, key)
        done.append(f"pressed {key}")
        await asyncio.sleep(0.4)

    elif action == "scroll":
        where = str(step.get("to") or selector or "bottom")
        problem = await page_browser.evaluate(
            f"({SCROLL})({json.dumps(where)})"
        )
        if problem:
            raise ToolError(f"Step {index}: nothing matches {where!r} to scroll to.")
        done.append(f"scrolled to {where}")

    elif action == "wait":
        if selector:
            await _wait_for(page_browser, selector, step.get("seconds"))
            done.append(f"waited for {selector}")
        else:
            seconds = max(0.0, min(float(step.get("seconds") or 1), MAX_WAIT))
            await asyncio.sleep(seconds)
            done.append(f"waited {seconds}s")

    else:
        raise ToolError(
            f"Step {index}: {action!r} is not something page_do can do. It "
            "can click, type, press, scroll and wait."
        )


async def _call(page_browser, function: str, *arguments) -> str:
    """Run one of the page functions above with JSON-safe arguments."""
    packed = ", ".join(json.dumps(argument) for argument in arguments)
    return await page_browser.evaluate(f"({function})({packed})") or ""


async def _press(page_browser, key: str) -> None:
    """A real key event, because forms listen for keys rather than clicks."""
    named = KEYS.get(key.strip().lower())
    if named:
        code, dom_key, code_number, char = named
    elif len(key) == 1:
        code, dom_key, code_number, char = key, key, ord(key.upper()), key
    else:
        raise ToolError(
            f"{key!r} is not a key page_do knows. It knows "
            + ", ".join(sorted(KEYS)) + ", and any single character."
        )
    base = {"windowsVirtualKeyCode": code_number, "key": dom_key, "code": code}
    await page_browser.command("Input.dispatchKeyEvent", {
        "type": "rawKeyDown", **base,
    })
    if char:
        await page_browser.command("Input.dispatchKeyEvent", {
            "type": "char", "text": char, **base,
        })
    await page_browser.command("Input.dispatchKeyEvent", {"type": "keyUp", **base})


async def _wait_for(page_browser, selector: str, seconds) -> None:
    limit = max(0.5, min(float(seconds or 10), MAX_WAIT))
    loop = asyncio.get_event_loop()
    deadline = loop.time() + limit
    while loop.time() < deadline:
        if await page_browser.evaluate(
            f"!!document.querySelector({json.dumps(selector)})"
        ):
            return
        await asyncio.sleep(0.2)
    raise ToolError(
        f"{selector!r} did not appear within {limit:g} seconds. "
        "Use read_page to see what the page is showing instead."
    )

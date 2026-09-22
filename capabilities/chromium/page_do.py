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
                            "click, type, press, hover, drag, scroll, or "
                            "wait."
                        ),
                    },
                    "ref": {
                        "type": "string",
                        "description": (
                            "A handle from the last read of the page, like "
                            "'ref_12'. The surest way to name an element: it "
                            "is the exact thing you were shown, where a "
                            "selector can match two of them. Goes stale when "
                            "the page navigates -- read it again for fresh "
                            "ones."
                        ),
                    },
                    "to_ref": {
                        "type": "string",
                        "description": "For drag: the handle to drag onto.",
                    },
                    "keys": {
                        "type": "string",
                        "description": (
                            "Modifiers held down for this step, joined by "
                            "'+': ctrl, shift, alt, meta. 'ctrl+shift'."
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
        "follow_popup": {
            "type": "boolean",
            "description": (
                "If a step opens a new tab, follow it and report that page "
                "instead. Defaults to true; turn it off to stay where you "
                "are."
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
(sel, label, ref) => {
  const pick = () => {
    if (ref !== null && ref !== undefined) return (window.__aworg_refs || [])[ref];
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
  // Focus as well as click. A real click does both, and without this a
  // field that was clicked is not the field a following keystroke reaches.
  if (el.focus) { try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); } }
  el.click();
  return "";
}
"""

#: Setting .value directly does not tell a framework anything happened, so
#: the native setter is called and the events a real keystroke would raise
#: are dispatched. Without this, React and friends keep their own state and
#: the field reverts the moment anything re-renders.
TYPE = """
(sel, value, ref) => {
  const el = (ref !== null && ref !== undefined)
    ? (window.__aworg_refs || [])[ref]
    : (sel ? document.querySelector(sel) : document.activeElement);
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
    follow_popup: bool = True,
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
        before = page_browser.url
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ToolError(f"Step {index} is not an object.")
            await _step(page_browser, index, step, done, context)

        # A click that opened a tab. The page under the Resident is
        # unchanged, which is exactly what makes this invisible otherwise:
        # it reads the old page back and concludes nothing happened.
        popped = await page_browser.popup()
        if popped and follow_popup:
            await page_browser.follow(popped)
            done.append(f"followed a new tab to {popped}")
        elif popped:
            done.append(f"a new tab opened at {popped}, not followed")

        page = await extract(page_browser)
        del before
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
    ref = _ref(step.get("ref"), index)
    modifiers = _modifiers(step.get("keys"), index)

    if context.activity is not None:
        context.activity.progress = f"step {index}: {action}"

    if action == "click":
        if ref is None and not selector and not text:
            raise ToolError(
                f"Step {index}: click needs a ref, a selector or some text."
            )
        if modifiers:
            await _mouse(page_browser, index, ref, selector, "click", modifiers)
        else:
            problem = await _call(page_browser, CLICK, selector, text, ref)
            if problem:
                raise ToolError(
                    f"Step {index}: nothing on the page matches "
                    f"{step.get('ref') or selector or text!r}. Read the page "
                    "again -- handles go stale when it navigates."
                )
        done.append(f"clicked {step.get('ref') or selector or text!r}")
        # A click is usually meant to change something, and what it changed
        # is the point of the call.
        await asyncio.sleep(0.4)

    elif action == "type":
        if text is None:
            raise ToolError(f"Step {index}: type needs text.")
        problem = await _call(page_browser, TYPE, selector, text, ref)
        if problem:
            raise ToolError(
                f"Step {index}: nothing on the page matches "
                f"{step.get('ref') or selector!r}."
            )
        done.append(
            f"typed into {step.get('ref') or selector or 'the focused field'}"
        )

    elif action == "hover":
        if ref is None and not selector:
            raise ToolError(f"Step {index}: hover needs a ref or a selector.")
        await _mouse(page_browser, index, ref, selector, "hover", modifiers)
        done.append(f"hovered {step.get('ref') or selector!r}")
        # Menus that open on hover take a moment to open.
        await asyncio.sleep(0.3)

    elif action == "drag":
        to_ref = _ref(step.get("to_ref"), index)
        if (ref is None and not selector) or (to_ref is None and not step.get("to")):
            raise ToolError(
                f"Step {index}: drag needs something to drag (ref or "
                "selector) and somewhere to drop it (to_ref or to)."
            )
        await _drag(page_browser, index, ref, selector, to_ref, step.get("to"))
        done.append(
            f"dragged {step.get('ref') or selector!r} onto "
            f"{step.get('to_ref') or step.get('to')!r}"
        )
        await asyncio.sleep(0.3)

    elif action == "press":
        key = str(text or "").strip()
        if not key:
            raise ToolError(f"Step {index}: press needs a key, such as Enter.")
        await _press(page_browser, key, modifiers)
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
            "can click, type, press, hover, drag, scroll and wait."
        )


async def _call(page_browser, function: str, *arguments) -> str:
    """Run one of the page functions above with JSON-safe arguments."""
    packed = ", ".join(json.dumps(argument) for argument in arguments)
    return await page_browser.evaluate(f"({function})({packed})") or ""


#: Modifier bits, as the protocol counts them.
MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4,
             "command": 4, "shift": 8}


def _modifiers(keys, index: int) -> int:
    if not keys:
        return 0
    total = 0
    for part in str(keys).replace(",", "+").split("+"):
        name = part.strip().lower()
        if not name:
            continue
        if name not in MODIFIERS:
            raise ToolError(
                f"Step {index}: {part!r} is not a modifier. They are "
                + ", ".join(sorted(set(MODIFIERS))) + "."
            )
        total |= MODIFIERS[name]
    return total


def _ref(value, index: int):
    """'ref_12' as the number 12, or None if there was no ref."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.startswith("ref_"):
        text = text[4:]
    if not text.isdigit():
        raise ToolError(
            f"Step {index}: {value!r} is not a handle. They look like "
            "'ref_12' and come from reading the page."
        )
    return int(text)


#: Bring something into view. Separate from measuring it, because a scroll
#: is not necessarily finished when the call that asked for it returns, and
#: a position read in the same breath can be the position it was leaving.
SCROLL_TO = """
(sel, ref, sel2, ref2) => {
  const pick = (s, r) => (r === null || r === undefined)
    ? (s ? document.querySelector(s) : null)
    : (window.__aworg_refs || [])[r];
  const first = pick(sel, ref);
  if (!first) return "nothing matched";
  const second = pick(sel2, ref2);
  first.scrollIntoView({ block: "center" });
  if (second) {
    const b = second.getBoundingClientRect();
    const seen = b.bottom > 0 && b.top < innerHeight &&
                 b.right > 0 && b.left < innerWidth;
    // Only if the other end is off screen: bringing it into view when it is
    // already visible would move the first one for no reason.
    if (!seen) second.scrollIntoView({ block: "center" });
  }
  return "";
}
"""

#: Where things are, measured and nothing else.
MEASURE = """
(sel, ref, sel2, ref2) => {
  const pick = (s, r) => (r === null || r === undefined)
    ? (s ? document.querySelector(s) : null)
    : (window.__aworg_refs || [])[r];
  const centre = (el) => {
    if (!el || !el.getBoundingClientRect) return null;
    const b = el.getBoundingClientRect();
    if (!b.width && !b.height) return null;
    return { x: b.left + b.width / 2, y: b.top + b.height / 2,
             seen: b.bottom > 0 && b.top < innerHeight &&
                   b.right > 0 && b.left < innerWidth };
  };
  return { from: centre(pick(sel, ref)), to: centre(pick(sel2, ref2)) };
}
"""

#: How long to let a scroll land before believing a coordinate.
SETTLE = 0.12


async def _positions(page_browser, index, ref, selector,
                     to_ref=None, to_selector=None, what="act on"):
    """Scroll, wait, then measure -- in that order and never fewer steps."""
    moved = await _call(page_browser, SCROLL_TO, selector, ref,
                        to_selector, to_ref)
    if moved == "nothing matched":
        raise ToolError(
            f"Step {index}: nothing to {what} -- "
            f"{step_name(ref, selector)} is not on the page. Read the page "
            "again for fresh handles."
        )
    await asyncio.sleep(SETTLE)
    where = await _call_json(page_browser, MEASURE, selector, ref,
                             to_selector, to_ref)
    if not where or not where.get("from"):
        raise ToolError(
            f"Step {index}: nothing to {what} -- "
            f"{step_name(ref, selector)} is not on the page, or has no size."
        )
    return where


async def _where(page_browser, index, ref, selector, what="act on"):
    return (await _positions(page_browser, index, ref, selector,
                             what=what))["from"]


async def _call_json(page_browser, function: str, *arguments):
    packed = ", ".join(json.dumps(argument) for argument in arguments)
    return await page_browser.evaluate(f"({function})({packed})")


def step_name(ref, selector) -> str:
    """Whichever way the caller named an element, for saying it back."""
    return f"ref_{ref}" if ref is not None else repr(selector)


async def _mouse(page_browser, index, ref, selector, kind, modifiers) -> None:
    """A real mouse event at the element's own position.

    Coordinates rather than el.click(), because a modifier-click and a hover
    are mouse state rather than a method call -- and the coordinates come
    from the element, so nothing here needs a screenshot to aim with.

    Aimed twice. Moving the pointer changes the page: a menu opens, a banner
    collapses, and what was being pointed at is now somewhere else. So the
    pointer moves, the target is measured again, and the press uses that.
    """
    spot = await _where(page_browser, index, ref, selector,
                        "hover" if kind == "hover" else "click")
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": spot["x"], "y": spot["y"],
        "modifiers": modifiers,
    })
    if kind == "hover":
        return

    spot = await _aim(page_browser, ref, selector, spot)
    base = {"x": spot["x"], "y": spot["y"], "modifiers": modifiers}
    await page_browser.command("Input.dispatchMouseEvent",
                               {"type": "mouseMoved", **base})
    for kind_of_event in ("mousePressed", "mouseReleased"):
        await page_browser.command("Input.dispatchMouseEvent", {
            "type": kind_of_event, "button": "left", "clickCount": 1, **base,
        })


#: How far something may have moved before it is worth correcting for. Two
#: pixels is sub-pixel layout and rounding; ten is a page that moved.
DRIFT = 3


async def _aim(page_browser, ref, selector, was):
    """Where the target is now, if that is not where it was.

    Falls back to the earlier position rather than failing: an element that
    has just vanished is a case the click itself will report, in better
    words than a measurement could.
    """
    now = await _call_json(page_browser, MEASURE, selector, ref, None, None)
    spot = (now or {}).get("from")
    if not spot:
        return was
    if abs(spot["x"] - was["x"]) < DRIFT and abs(spot["y"] - was["y"]) < DRIFT:
        return was
    return spot


#: HTML5 drag-and-drop, which synthetic mouse events cannot drive: the
#: browser takes over on mousedown and the mouseup never arrives. Dispatched
#: as the events the API itself defines, sharing one DataTransfer so that a
#: handler reading what was dropped finds what was dragged.
NATIVE_DRAG = """
(fromSel, fromRef, toSel, toRef) => {
  const pick = (sel, ref) => (ref === null || ref === undefined)
    ? document.querySelector(sel)
    : (window.__aworg_refs || [])[ref];
  const from = pick(fromSel, fromRef);
  const onto = pick(toSel, toRef);
  if (!from || !onto) return "nothing matched";
  if (!from.draggable) return "not native";
  const data = new DataTransfer();
  const fire = (el, type) => el.dispatchEvent(new DragEvent(type, {
    bubbles: true, cancelable: true, dataTransfer: data,
  }));
  from.scrollIntoView({ block: "center" });
  fire(from, "dragstart");
  fire(onto, "dragenter");
  fire(onto, "dragover");
  fire(onto, "drop");
  fire(from, "dragend");
  return "";
}
"""


async def _drag(page_browser, index, ref, selector, to_ref, to_selector) -> None:
    # The native API first, because an element that declares itself
    # draggable is telling us which of the two kinds of drag it is.
    native = await _call(page_browser, NATIVE_DRAG,
                         selector, ref, to_selector, to_ref)
    if native == "nothing matched":
        raise ToolError(
            f"Step {index}: nothing to drag -- "
            f"{step_name(ref, selector)} or {step_name(to_ref, to_selector)} "
            "is not on the page."
        )
    if native == "":
        return

    where = await _positions(page_browser, index, ref, selector,
                             to_ref, to_selector, "drag")
    start, end = where["from"], where.get("to")
    if not end:
        raise ToolError(
            f"Step {index}: nothing to drop onto -- "
            f"{step_name(to_ref, to_selector)} is not on the page."
        )
    if not start.get("seen") or not end.get("seen"):
        raise ToolError(
            f"Step {index}: {step_name(ref, selector)} and "
            f"{step_name(to_ref, to_selector)} cannot both be on screen at "
            "once, so there is no gesture that goes from one to the other. "
            "Scroll first, or drag to something nearer."
        )
    # Move first, then look again, then press. Moving the pointer here is
    # what closes whatever the pointer was on before, and that is usually
    # what was holding the page in a different shape.
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": start["x"], "y": start["y"], "modifiers": 0,
    })
    start = await _aim(page_browser, ref, selector, start)
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": start["x"], "y": start["y"], "modifiers": 0,
    })
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mousePressed", "button": "left", "clickCount": 1,
        "x": start["x"], "y": start["y"], "modifiers": 0,
    })
    # In steps, because a drag handler that only listens for the drop will
    # take a single jump, and one that tracks movement will not follow at
    # all without something to track.
    for step in range(1, 6):
        await page_browser.command("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "button": "left", "modifiers": 0,
            "x": start["x"] + (end["x"] - start["x"]) * step / 5,
            "y": start["y"] + (end["y"] - start["y"]) * step / 5,
        })
        await asyncio.sleep(0.03)

    # And aim again before letting go. The pointer has crossed the page to
    # get here, and anything that reacts to a pointer has had its say.
    end = await _aim(page_browser, to_ref, to_selector, end)
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "button": "left", "modifiers": 0,
        "x": end["x"], "y": end["y"],
    })
    await page_browser.command("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "button": "left", "clickCount": 1,
        "x": end["x"], "y": end["y"], "modifiers": 0,
    })


async def _press(page_browser, key: str, modifiers: int = 0) -> None:
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
    base = {"windowsVirtualKeyCode": code_number, "key": dom_key, "code": code,
            "modifiers": modifiers}
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

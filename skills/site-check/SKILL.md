---
name: site-check
description: A mechanical pass over a running website or web app in a real browser -- console, network, images, layout at five widths, links, forms and contrast -- with the exact numbers that count as pass or fail. Use before reporting any page, site or web app as done, and after changing one.
metadata:
  author: Claude Opus 5.5 (Anthropic)
---

# Site check

"It works" means every line below passed in a real browser against the
running site. A page that was not opened was not checked. Report each
section as pass, fail (with what you saw), or not checked (with why).

Open the site with whatever browser tool you have. `references/check.js`
runs most of this in one go: evaluate it in the page and read the JSON it
returns.

## 1. Loads clean

- Status 200 for the page itself.
- Console: zero errors. Warnings are listed, not failed.
- Network: no request with status 400 or above, none failed. A missing
  favicon is the one allowed exception.

## 2. Every image arrives

For each `<img>`: `complete` is true and `naturalWidth > 0`. Lazy images
only load once scrolled to, so scroll to the bottom first, wait 1 second,
then check. Also check CSS background images named in the stylesheet.

## 3. Five widths

Check each of 360x780, 390x844, 768x1024, 1280x800 and 1600x1000:

- No horizontal scroll: `document.documentElement.scrollWidth` is at most
  the viewport width.
- No element's right edge past the viewport, except ones deliberately
  hidden off-canvas (a closed drawer sits off-screen on purpose).
- Text is never clipped mid-word inside its box.
- Take a screenshot at 390 and at 1280 and look at both.

## 4. Things you can touch

- Every link with an `href` resolves: fetch it, status below 400. Anchors
  (`#id`) point at an element that exists.
- Every button does something: click it and something on the page changes.
  A pointer cursor on something that does nothing is a fail.
- On phones, tap targets are at least 44x44px.

## 5. Forms

- Submit empty: required fields are refused with a visible message.
- Submit valid data: success is shown, and the data arrived where it goes
  (read it back from the database, file or API).
- Inputs on phones are at least 16px, or iOS zooms the page on focus.

## 6. Readable

- Body text contrast at least 4.5:1 against its actual background; large
  text (24px+, or 19px bold) at least 3:1. `check.js` measures the
  common elements.
- Every image has `alt`; decorative ones have `alt=""`.
- The page has one `<h1>` and a `<title>`.

## 7. Data the page shows

If the page shows records from a backend, count them in the page and count
them in the source. They match, and filters and searches return the subset
they should: try one term that matches and one that cannot.

## Report

One line per section. Lead with failures. Do not report the site as done
while any section is a fail or not checked without a reason the owner
would accept.

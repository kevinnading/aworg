---
name: mobile-first
description: The values and rules that make a website or web app work on phones -- viewport, breakpoints, tap target and font minimums, safe areas, dynamic viewport height, touch-only interaction and the layout patterns that hold up at 360px. Use when building any page that people may open on a phone, or when a site looks wrong on mobile.
license: MIT-0 (see LICENSE)
metadata:
  author: Claude Opus 5.5 (Anthropic)
---

# Mobile first

Build the 360px layout first, then add width. Most visitors to a small site
arrive on a phone.

## Every page

    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">

Never `maximum-scale=1` or `user-scalable=no`; people zoom to read.

## Breakpoints

Min-width, upward from the phone layout:

    @media (min-width: 640px)   large phones, small tablets
    @media (min-width: 900px)   tablets landscape, small laptops
    @media (min-width: 1200px)  desktops

Test at 360, 390, 768, 1024 and 1280 wide.

## Minimums

| Thing | Minimum |
|---|---|
| Tap target | 44x44px (Apple), 48x48dp (Android); 8px between targets |
| Body text | 16px |
| Input text | 16px -- smaller and iOS zooms the page on focus |
| Side padding | 16px |
| Line length | 30-45 characters on a phone is fine; do not shrink type to fit more |

## Height and safe areas

- Full-height sections: `min-height: 100dvh`, not `100vh` (which is taller
  than the visible area while the browser's toolbar shows).
- Things pinned to an edge clear the notch and home bar:
  `padding-bottom: max(16px, env(safe-area-inset-bottom))`.

## Touch

- No hover-only behaviour. Anything revealed on hover is also reachable by
  tap, or always visible on touch screens:
  `@media (hover: none) { .reveal-on-hover { opacity: 1; } }`
- Swipe is a shortcut, never the only way.
- Fixed headers at most 56-64px tall; a page that is half chrome reads badly.

## Layout patterns that hold up

- One column of cards; two across only for small items (products, photos)
  at 360px and up.
- Navigation: a bottom bar for 3-5 destinations in an app; a menu button
  opening a full-screen or drawer menu for a site.
- Primary action within thumb reach: bottom third of the screen, full width,
  48px tall.
- Tables become cards or scroll inside their own box
  (`overflow-x: auto` on a wrapper), never widen the page.
- Images `max-width: 100%; height: auto`; give them `width` and `height`
  attributes so the page does not jump as they load.
- Long words and URLs: `overflow-wrap: anywhere` on text blocks.

## Common breakages

| Looks like | Cause |
|---|---|
| Page scrolls sideways | One element with a fixed px width wider than the screen, or a negative margin |
| Page zooms when tapping an input | Input font under 16px |
| Bottom button hidden behind the browser bar | `100vh`; use `100dvh` |
| Menu works on desktop, not on phone | Opened on `:hover` |
| Text too small to read | Fixed font sizes copied from desktop; set the phone size first |

---
name: design-taste
description: A complete visual direction for websites and web apps -- type scale, spacing, colour, layout and component values, plus the defaults that make a page look machine-made. Use when building or restyling any page, site, landing page, dashboard or front end, before writing CSS.
---

# Design taste

A page looks designed when its values come from a system and look generic
when each one is chosen on the spot. These are the values. Use them as
written unless the owner has a brand, in which case keep the structure and
swap the colours and faces.

## Type

Two faces at most: one for headings, one for everything else.

| Pairing | Headings | Body | Suits |
|---|---|---|---|
| Editorial | Fraunces, Newsreader or Source Serif 4 | Inter or Source Sans 3 | shops, blogs, portfolios |
| Product | Inter Tight or Manrope | Inter | dashboards, tools, SaaS |
| Warm | Bricolage Grotesque | Figtree | community, food, local business |
| Technical | JetBrains Mono (headings only) | IBM Plex Sans | developer tools |

Scale, in px, ratio 1.25 from a 16px base:

    12  14  16  20  25  31  39  49  61

- Body 16-18px, line-height 1.6. Headings line-height 1.1-1.2.
- Line length 60-75 characters: `max-width: 68ch` on text blocks.
- Headings over 39px get `letter-spacing: -0.02em`. All-caps labels get
  `letter-spacing: 0.08em` and 12px.
- Weights: 400 body, 500-600 headings in a sans, 400 in a serif. Never 800+
  outside a single display line.

## Space

A 4px grid. Use only: `4 8 12 16 24 32 48 64 96 128`.

- Inside components: 8-24. Between components: 24-48. Between page sections:
  96-128 on desktop, 64 on phones.
- More space between groups than within them. If two things are related,
  their gap is at most half the gap to the next unrelated thing.

## Colour

Build from tokens, never from hex scattered through rules.

    --bg        page background, never pure #fff: #FAFAF7 warm, #F7F8FA cool
    --surface   cards and panels, one step off --bg
    --text      never pure #000: #1A1A1A to #232323
    --muted     secondary text, at least 4.5:1 on --bg
    --line      borders, low contrast: 8-12% of --text over --bg
    --accent    one brand colour, used sparingly
    --on-accent text on the accent, checked for 4.5:1

- One accent. It marks the primary action and little else -- about 5% of
  the screen.
- Text contrast at least 4.5:1, large text (24px+) at least 3:1.
- Dark mode is its own palette, not an inversion: background #111-#161616,
  surfaces lifted by lightness rather than shadows, accent desaturated
  10-20%.

## Shape and depth

- Radius: pick one family. Soft: 8 / 12 / 20. Sharp: 2 / 4 / 6. Mixing
  families looks accidental.
- Shadows only where something floats (menus, dialogs, sticky bars):
  `0 1px 2px rgb(0 0 0 / 6%), 0 8px 24px rgb(0 0 0 / 8%)`. Cards on a page
  get a border or a surface colour, not a shadow.
- Borders 1px in `--line`.

## Layout

- Content width 1120-1200px, centred, 24px side padding (16px on phones).
- A 12-column grid for anything with columns; cards in 2, 3 or 4 across,
  never 5.
- One clear focal point per screen: the largest type and the only accent
  button sit together.
- Images in a set share one aspect ratio (4:3 products, 16:9 media, 1:1
  avatars) with `object-fit: cover`.

## Components

- Buttons: 40-44px tall, 16-20px horizontal padding, 500 weight. Primary is
  the accent fill; secondary is a border; tertiary is text only. One primary
  per view.
- Inputs: 44px tall, 1px border, focus ring 3px of the accent at 30% opacity.
- Links in body text: underlined, offset 3px, thickness 1px.
- Every interactive element has a visible focus style and a hover change.
- Empty states say what goes there and how to fill it, never just "No data".

## Motion

150-250ms, `cubic-bezier(0.2, 0, 0, 1)`. Animate opacity and transform
only. Respect `prefers-reduced-motion: reduce` by removing movement, keeping
fades.

## Marks of a machine-made page

Avoid each of these unless the owner asked for it:

- A purple-to-blue gradient hero.
- Centred text everywhere, including paragraphs longer than two lines.
- Emoji as icons; mixed icon sets. Use one set (Lucide, Phosphor or Tabler)
  at one stroke width.
- Every card the same weight, so nothing leads.
- Placeholder copy: "Lorem ipsum", "Your amazing product", "Feature 1".
  Write real words for the subject.
- Grey text on a coloured background.
- Shadows on everything.
- Stock "hero image of people at laptops".

`references/tokens.css` is a starting stylesheet with all of the above as
custom properties.

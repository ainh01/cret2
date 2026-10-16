# Cret2 — palette re-skin report

Re-skin of the four pages (`static/home.html`, `static/settings.html`, `static/configure.html`, `quiz.html`)
onto the required four-hue palette. Styling only: no markup restructuring, no class renames, no content or
JavaScript-behaviour changes.

> **Part 1** below covers the original light palette. **Part 2** (further down) adds the dark theme, which is
> now the default, plus the light/dark switch. Read Part 2 for the current state of the app.

**Files changed**

| File | Change |
| --- | --- |
| `static/style.css` | Rewritten. Palette token block first, then shared base + all interactive states, then a section per page, then the legacy workspace surface. Part 2 adds the dark token block and the switch. |
| `static/home.html` | Inline dark-purple `<style>` block replaced by `<link rel="stylesheet" href="/static/style.css">`. Markup and script untouched. Part 2 adds `data-theme`, the theme script and the switch. |
| `static/settings.html` | Same substitution, same Part 2 additions. |
| `static/configure.html` | Same substitution, same Part 2 additions. |
| `quiz.html` | Added the stylesheet link. Three `outputText.classList` lines added — the only JS change — so the page's error state has a styling hook (it had none). Part 2 adds `data-theme`, the theme script and the switch. |
| `static/theme.js` | New (Part 2): remembers the chosen theme and wires the switch. |
| `PALETTE-REPORT.md` | This report. |

**Palette and role map**

| Token | Value | RGB | Role | Where it is used |
| --- | --- | --- | --- | --- |
| `--brand` | `#0081C9` | `rgb(0, 129, 201)` | primary brand | brand mark (`h1 span`, `.brand-icon`), checkbox/selected fills, status dot, link hover, blockquote rule, control hover borders |
| `--brand-soft` | `#5BC0F8` | `rgb(91, 192, 248)` | secondary / highlight | secondary buttons (`Thêm file`, `Paste`, `Copy Output`), hover fills, selected tab, step-highlight dot, `mark.current` |
| `--brand-pale` | `#86E5FF` | `rgb(134, 229, 255)` | subtle surface | configure step panels, info/status banners, table stripes, disabled fills, inline code, empty-mark |
| `--accent` | `#FFC93C` | `rgb(255, 201, 60)` | accent / attention | attachment badges, error + warning banners, success/CTA panel edge, focus accent, `mark`, toast edge |

**Derived values** (shades/tints of the four hues, plus near-black/near-white neutrals — no fifth hue)

| Token | Value | Why it exists |
| --- | --- | --- |
| `--brand-strong` | `#0074B4` | `--brand` darkened: white-on-fill and fill-on-white are both 4.21:1, which fails 4.5:1 for normal text. Used for primary button fills and link text. |
| `--brand-deep` | `#005E93` | hover/active of primary fills (6.95:1 with white). |
| `--brand-soft-deep` | `#2E9FE4` | pressed state of soft fills (5.48:1 with ink). |
| `--accent-ink` | `#8A6400` | accent used as text or as a border (5.38:1 on white). `--accent` itself as text is 1.54:1 and is never used for text. |
| `--accent-wash` | `#FFF2D2` | accent tint for invalid fields / error output (14.39:1 with ink). |
| `--surface-soft` | `#E4F4FF` | pale-cyan tint for large surfaces (toolbar, code blocks) where full `#86E5FF` would be loud. |
| `--ink` | `#0D2430` | body text, near-black. |
| `--muted` | `#3E5866` | secondary text — dark enough (7.52:1 on white, 5.25:1 on `#86E5FF`) to sit on pale panels too. |
| `--bg` / `--surface` | `#F2FAFE` / `#FFFFFF` | page background / cards and fields. |
| `--line` | `#C7DCE8` | decorative separators (no 3:1 duty). |
| `--line-strong` | `#3E6E8A` | control borders: 5.52:1 on white, 3.86:1 on pale panels. |
| `--green` | → `var(--brand-strong)` | legacy token name kept and remapped; `--line` and `--muted` keep their names with new values. |

**Contrast checks** (WCAG 2.1 relative-luminance, computed and re-verified against the rendered pages)

Text pairs — threshold 4.5:1 (normal) / 3:1 (large ≥24px or ≥18.66px bold):

| Pair | Ratio | Verdict |
| --- | --- | --- |
| ink on white | 16.00:1 | AA |
| ink on `--bg` | 15.15:1 | AA |
| ink on `--surface-soft` | 14.24:1 | AA |
| ink on `--brand-pale` | 11.18:1 | AA |
| ink on `--accent` | 10.42:1 | AA |
| ink on `--brand-soft` | 7.88:1 | AA |
| muted on white | 7.52:1 | AA |
| muted on `--bg` | 7.12:1 | AA |
| muted on `--surface-soft` | 6.69:1 | AA |
| muted on `--brand-pale` | 5.25:1 | AA |
| `--brand-strong` link on white | 5.05:1 | AA |
| `--brand-strong` link on `--bg` | 4.78:1 | AA |
| `--accent-ink` on white | 5.38:1 | AA |
| muted on `--accent` | 4.90:1 | AA |
| white on `--brand-strong` (button label) | 5.05:1 | AA |
| white on `--brand-deep` (hover label) | 6.95:1 | AA |
| white on `--ink` (toast) | 16.00:1 | AA |
| white on `--accent-ink` | 5.38:1 | AA |
| **`--brand` `#0081C9` brand mark on white** | **4.21:1** | **AA large text only** — used solely on the 24px `h1 span`; passes the 3:1 large-text threshold |
| **white on `--brand` `#0081C9`** | **4.21:1** | **not used for normal-size text** see traps below |

UI components / boundaries — threshold 3:1:

| Pair | Ratio | Verdict |
| --- | --- | --- |
| input border `--line-strong` on white | 5.52:1 | passes |
| input border on pale panel | 3.86:1 | passes |
| primary fill vs white | 5.05:1 | passes |
| secondary button **border** vs white | 5.52:1 | passes |
| hover secondary border (`--brand-deep`) vs white | 6.95:1 | passes |
| hover border `--brand` on white | 4.21:1 | passes |
| checkbox fill `--brand` vs white | 4.21:1 | passes |
| `--accent-ink` badge/step border on pale panel | 3.76:1 | passes |
| focus ring outer `--ink` on white / `--bg` / pale | 16.0 / 15.15 / 11.18:1 | passes |
| focus accent `--accent` vs `--ink` ring | 10.42:1 | passes |
| step dot / badge fill vs adjacent pale panel | 1.42 / 1.07:1 | fails alone — carried by their `--line-strong` / `--accent-ink` border (3.86 / 3.76:1) |
| `--brand-soft` fill vs white | 2.03:1 | fails alone — carried by the 5.52:1 button border |

**Contrast traps handled**

- `#0081C9` is 4.21:1 against white in both directions. It therefore stays on the **brand mark (24px, passes 3:1 large text)**,
  UI indicators, selected/checked fills and borders, while normal-size text and button fills use the derived
  `--brand-strong` `#0074B4` (5.05:1) — the "darken the fill slightly" route the brief allows.
- `#5BC0F8` (2.03:1), `#86E5FF` (1.43:1) and `#FFC93C` (1.54:1) never take white text. All three carry
  `--ink` text (7.88:1 / 11.18:1 / 10.42:1).
- `#FFC93C` is never used as text; `--accent-ink` `#8A6400` (5.38:1) is the accent *text* colour.
- The focus indicator is two-tone: 2px `--accent` edged by 2px `--ink`, so the ring is visible against light
  surfaces (ink edge) and against brand fills (accent/ink are both ≥3:1 there). A transparent outline is also set
  so forced-colors mode still shows a focus indicator.

**Interactive state coverage**

| State | How it is styled |
| --- | --- |
| default | light `--bg`, white fields with `--line-strong` borders, brand-strong primary, brand-soft secondary |
| hover | primary → `--brand-deep`; secondary → `--brand-soft-deep` + `--brand-deep` border; fields → `--brand` border; remove button → `--accent` fill with ink text; links → `--brand-deep` |
| focus-visible | two-tone accent/ink ring on buttons, inputs, selects, textareas, links and `[tabindex]` |
| active | darker fill + 1px press offset; checkbox `accent-color` deepens |
| disabled | `--brand-pale` fill, `--muted` text, `not-allowed` cursor (buttons *and* fields) |
| loading | `.loading` keeps the brand fill so the white spinner stays visible; `#status` becomes a pale info banner |
| error / invalid | `#error` / `.fail` / `#message.fail` become `--accent` banners with ink text and an `--accent-ink` edge; invalid fields get `--accent-wash` + 2px `--accent-ink`; quiz output field via `.is-error` |
| empty | empty banners/status keep their reserved `min-height` and render nothing; `#attachments[hidden]` collapses; placeholders use `--muted` |
| success | `.ok` and `#link:not(:empty)` use a pale panel with a brand or accent edge |

**Verification performed**

- **Rendered and inspected**: 30 screenshots across the four pages at 1440×900 and 390×844 (default, hover,
  focus-visible, active, disabled, loading, error, invalid, success and populated-list states), driven with real
  hover/keyboard/click events in headless Chrome. Screenshots live outside the repo in
  `%TEMP%\cret2-verify\shots`; the two defects found this way were fixed and re-shot:
  quiz's label/textarea column did not centre (inline-block textareas ignore auto margins) and long attachment
  names overflowed the grid on mobile (`minmax(0, 1fr)`).
- **Layout sweep**: no horizontal overflow on any page at 360 / 390 / 768 / 1024 / 1440 / 1920 px.
- **Palette audit**: 38/38 assertions on computed styles — the four tokens resolve to the exact required values,
  each role lands on the intended element (primary/secondary fills, banners, panels, borders, checkbox, focus
  ring), and **no legacy green/cream or purple value is computed on any page**.
- **Source sweep**: `static/style.css` contains only the four palette values, their derived shades/tints,
  `#fff`/`#FFFFFF`; the HTML pages contain zero colour literals and no `<style>` blocks.
- **Existing tests** (unchanged by this work): `test_settings.py`, `test_material.py`, `test_txt.py` all pass
  (`test_config.py` is a help/config module, not a test).
- **Not verified**: the legacy `.studio` workspace rules (`.app-header`, `#prompt`, `#output` …) have no markup
  in this repo — no route serves them — so they were re-skinned to the same tokens and scoped under `.studio`
  to stop their element selectors bleeding into the four pages, but they were not rendered.

**Notes**

- `quiz.html` had no styling at all before this change; it now uses the same base, so it is a visible change
  beyond a recolour (still the same elements, ids, order and script).
- `--brand-pale` at full strength is used for panels, banners, stripes and disabled fills, exactly as the role
  map asks. It reads as a saturated cyan on large surfaces; the derived `--surface-soft` is used only where a
  quieter tint is needed (toolbar, code blocks).

---

# Part 2 — dark theme (now the default) + light/dark switch

**Dark palette as given:** `#5003C0` `rgb(80, 3, 192)` · `#AB03A9` `rgb(171, 3, 169)` · `#FF467A` `rgb(255, 70, 122)` · `#FFD51E` `rgb(255, 213, 30)`.

Dark is the default on first paint: the markup carries `data-theme="dark"` on `<html>`, so the page is dark
with no JS and no flash even if scripts are off. `static/theme.js` only re-applies a remembered choice
(`localStorage['cret2-theme']`) before the body parses, and wires the switch.

**The switch** — one control per page, top-right of the content column:

```html
<div class="theme-bar">
  <button class="theme-toggle" id="themeToggle" type="button" role="switch" aria-checked="true">Chế độ tối</button>
</div>
```

It is a *switch*, not a label swap: the text stays `Chế độ tối`, `aria-checked` and `.is-on` report the state,
and the dot turns accent-yellow while dark is on. Going back to light is a click away, and the choice survives
a reload.

**Dark role map** — same token names and the same jobs as Part 1, re-answered for a dark surface:

| Given colour | Dark role | Where it is used |
| --- | --- | --- |
| `#5003C0` | **base surface** (the page itself) | page background; the app reads as this purple |
| `#AB03A9` | **primary** | primary buttons (`Học`, `Lưu`, `Parse and Random`), checked fills, active states |
| `#FF467A` | **secondary / highlight** | secondary buttons (`Thêm file`, `Paste`, `Copy Output`), hover fills, selected items, step dot |
| `#FFD51E` | **accent / attention** | badges, error + warning banners, key metrics, focus accent, accent-as-text |

**Derived dark values** (shades/tints of the same hues, plus white/lavender neutrals — no fifth hue):

| Token | Value | Why it exists |
| --- | --- | --- |
| `--brand-pale` / `--surface-soft` / `--fill-info` | `#3A0191` | panel/banner/stripe layer, **darker** than the page |
| `--surface` / `--fill-disabled` | `#2A0170` | field, code and output wells |
| `--ink` | `#FFFFFF` | text |
| `--muted` | `#CFC0F5` | secondary text (5.91:1 on the page) |
| `--brand` | `#C9A8FF` | brand hue lightened so it reads on dark (4.98:1) — brand mark, indicators |
| `--brand-strong` | `#D6BCFF` | links (5.91:1) |
| `--brand-deep` | `#C704C4` | primary hover fill (white 4.95:1) |
| `--edge-primary` | `#C7B2FF` | **the edge that makes a primary button exist** (see below) |
| `--on-bright` | `#2A0413` | text on `#FF467A` (5.70:1) and on `#FFD51E` (13.14:1) |
| `--line` / `--line-strong` | `#7B45E0` / `#C7B2FF` | separators / control borders (5.31:1 on the page) |
| `--accent-wash` | `#4A0F3C` | invalid-field tint (white on it 14.74:1) |
| `--inverse-surface` / `--shadow` | `#2A0170` / `rgba(0,0,0,.5)` | toast surface and depth |

**Two design problems this palette creates, and how they are solved**

1. **`#5003C0` and `#AB03A9` have nearly the same luminance (0.106 vs 0.116).** A magenta primary button on
   the purple page is therefore invisible as a *shape*: 1.57:1. Every primary fill now carries
   `--edge-primary` (light violet, 5.31:1 on the page) as its border, which is what identifies the control.
   In light mode `--edge-primary` is `transparent`, so nothing about the light theme changed.
2. **`#5003C0` is already bright, so panels cannot go lighter and stay distinct.** Lightening it barely moves
   the ratio (a lighter violet only reaches ~1.2:1). The layers therefore go *darker*: page `#5003C0` →
   panel `#3A0191` (2.30:1) → well `#2A0170` (1.93:1 from the panel, with a 1px light border for crispness).

**Dark contrast checks** (computed, then re-verified against the rendered pages)

Text — 4.5:1 normal / 3:1 large:

| Pair | Ratio | | Pair | Ratio |
| --- | --- | --- | --- | --- |
| ink on page | 9.93:1 | | ink on panel | 13.18:1 |
| ink on well | 15.71:1 | | muted on page | 5.91:1 |
| muted on panel | 7.85:1 | | muted on well | 9.36:1 |
| link `#D6BCFF` on page | 5.91:1 | | link on panel | 7.84:1 |
| accent-as-text on page | 6.99:1 | | accent-as-text on panel | 9.28:1 |
| white on primary `#AB03A9` | 6.33:1 | | white on primary hover | 4.95:1 |
| dark text on `#FF467A` | 5.70:1 | | dark text on `#FFD51E` | 13.14:1 |
| white on toast | 15.71:1 | | muted on disabled fill | 9.36:1 |
| brand mark `#C9A8FF` on page | 4.98:1 (large text) | | ink on invalid wash | 14.74:1 |

UI components / boundaries — 3:1:

| Pair | Ratio | Verdict |
| --- | --- | --- |
| primary edge `#C7B2FF` on page / panel | 5.31 / 7.06:1 | passes |
| control border on well | 8.41:1 | passes |
| focus accent on page | 6.99:1 | passes |
| focus white edge on page / pill / magenta | 9.93 / 3.28 / 6.33:1 | passes |
| invalid border `#FF467A` on the wash | 4.50:1 | passes |
| yellow badge vs page | 6.99:1 | passes |
| `#AB03A9` fill alone on page | 1.57:1 | **fails alone** → carried by `--edge-primary` (5.31:1) |
| `#FF467A` fill alone on page | 3.03:1 | passes, and its own border is a stronger 5.31:1 |
| white text on `#FFD51E` / on `#FF467A` | 1.42 / 3.28:1 | **never used** — those fills take `--on-bright` |
| focus yellow band on a pink button | 2.31:1 | fails alone → the white outer edge (3.28:1) carries the ring |

**Dark-only rule change:** the native checkbox (`appearance: auto`) paints a neutral grey box that reads muddy
olive against the purple, and it ignores `background`/`border`. Dark therefore draws its own checkbox
(`appearance: none`, well fill, light border, white check on the magenta fill). Light keeps the native control,
so the only light-mode change in Part 2 is the checkbox `accent-color`, which moved from `#0081C9` to the
primary fill `#0074B4` so the white checkmark works in both themes (white-check contrast improves 4.21 → 5.05).

**Part 2 verification**

- **Switch behaviour**: on all four pages — default `data-theme="dark"` with `color-scheme: dark`, clicking it
  switches to `data-theme="light"` / `color-scheme: light`, `aria-checked` and `.is-on` follow, the choice is
  stored and survives a reload, and a second click returns to dark.
- **Rendered and inspected**: dark screenshots of all four pages plus the state set (error, loading, disabled,
  focus on button and field, attachments, hover, invalid field, mobile) and light regression shots, at
  1440×900 and 390×844.
- **Palette audit**: 49/49 dark assertions on computed styles — the four given values land in their roles
  (`--bg` `#5003C0`, primary `#AB03A9`, highlight `#FF467A`, accent `#FFD51E`), every derived token resolves as
  planned, and the light theme still resolves to its Part 1 values (`#0081C9` / `#5BC0F8` / `#86E5FF` /
  `#FFC93C`, page `#F2FAFE`, focus ring unchanged) — light regression audit 38/38.
- **Layout sweep** re-run in dark: no horizontal overflow at 360 / 390 / 768 / 1024 / 1440 / 1920 px.
- **Existing tests**: `test_settings.py`, `test_material.py`, `test_txt.py` still pass.

**Part 2 notes**

- The switch adds visible UI to every page and a new file (`static/theme.js`) — both were explicitly requested,
  and they are the only additions beyond styling.
- Panels sit *darker* than the page in dark mode, the inverse of the light theme. That is forced by the maths
  above, not a preference.
- `#FF467A` and `#FFD51E` are bright surfaces: they always carry `--on-bright` text, never white.


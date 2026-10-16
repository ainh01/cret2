# Cret2 — palette re-skin report

Re-skin of the four pages (`static/home.html`, `static/settings.html`, `static/configure.html`, `quiz.html`)
onto the required four-hue palette. Styling only: no markup restructuring, no class renames, no content or
JavaScript-behaviour changes.

**Files changed**

| File | Change |
| --- | --- |
| `static/style.css` | Rewritten. Palette token block first, then shared base + all interactive states, then a section per page, then the legacy workspace surface. |
| `static/home.html` | Inline dark-purple `<style>` block replaced by `<link rel="stylesheet" href="/static/style.css">`. Markup and script untouched. |
| `static/settings.html` | Same substitution. |
| `static/configure.html` | Same substitution. |
| `quiz.html` | Added the stylesheet link. Three `outputText.classList` lines added — the only JS change — so the page's error state has a styling hook (it had none). |
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

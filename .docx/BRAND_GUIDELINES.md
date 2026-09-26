# GenQ Analytics — Brand Guidelines

## Brand Identity

**Product Name:** GenQ Analytics  
**Tagline:** Academic & Autonomous Intelligence  
**Positioning:** An elite autonomous data analytics and research synthesis platform that feels like an executive research library and senior quantitative consultancy from the future — warm, authoritative, trustworthy, and deeply intelligent.

---

## Logo & Wordmark

- **Wordmark:** `GenQ` — set in a bold serif or semi-bold humanist sans. The `Q` carries weight and distinction.
- **Sub-brand label:** `Analytics` appears in regular weight directly beneath or adjacent, styled with distinction.
- **Supporting descriptor:** `Academic & Autonomous Intelligence` — set in a muted, small-caps or light weight style beneath the brand name.
- **Brand Mark:** Refined scholar / geometric spark icon in `#8B6F3E` (primary) or `#1A1208`.

---

## Color Palette

Sourced directly from the Cognitive Heritage design system:

| Token | Hex | Usage |
|---|---|---|
| Primary | `#8B6F3E` | CTAs, active nav items, primary buttons, icons, highlights |
| Secondary | `#EDE4D0` | Card backgrounds, section fills, hover states |
| Tertiary | `#D4C9B0` | Borders, dividers, subtle backgrounds |
| Neutral / Text | `#1A1208` | Primary text, headings, dark backgrounds |
| Background | `#F2EDE3` | Main page background (warm off-white / parchment) |
| Surface | `#FDFAF5` | Card surfaces, sidebar, elevated panels |
| Muted Text | `#9B8E7A` | Secondary labels, metadata, captions, placeholder text |
| Success | `#5C6E3E` | Positive insights, confirmation, validated models |
| Warning | `#B8860B` | Skeptic debate warnings, quality cautions, anomalies |
| Error | `#8B3A3A` | Critical failures, risk flags |
| Info / Accent | `#755C3B` | Supplementary analyst notes, breadcrumbs |

### Color Principles
- The palette is warm and archival — evokes aged paper, fine leather, and scholarly materials.
- **Never** use cold blues, purples, cyans, neon gradients, or stark pure white (`#FFFFFF`) as primary backgrounds.
- Primary brown (`#8B6F3E`) is used with purpose — for interactive elements, highlights, and emphasis.
- All UI surfaces should feel "warm parchment" and scholarly — never clinical, sterile, or generic SaaS.

---

## Typography

### Type Scale

| Role | Font Family | Weight | Notes |
|---|---|---|---|
| Headline / Display | `Noto Serif` | 400–700 | Used for document titles, page headings, large display text |
| Body | `Manrope` | 400 | Primary reading font for paragraphs, descriptions, findings |
| Label | `Manrope` | 500–600 | Buttons, nav items, tags, metadata labels |
| Caption | `Manrope` | 400 | Small metadata, timestamps, helper text |
| Monospace | `JetBrains Mono` | 400–500 | Code, query blocks, statistical metrics, confidence scores |

### Typography Principles
- Headings use `Noto Serif` for a scholarly, editorial feel.
- UI chrome, general body copy, and narrative text use `Manrope` — clean, geometric, modern, highly legible.
- Monospace (`JetBrains Mono`) is strictly for data tables, metrics, code, and statistical readouts — **never** as the default app-wide body font.
- Line height: 1.5–1.7 for body, 1.2–1.3 for headings.
- Letter spacing: slightly loose on uppercase labels (`0.08em` to `0.1em`).

---

## Iconography

- **Style:** Clean rounded line icons, 1.5px stroke, minimal fill — consistent with Lucide icon sets.
- **Color:** Icons default to `#8B6F3E` (primary) on active states, `#9B8E7A` (muted) on idle, `#1A1208` on light surfaces.
- **Sizes:** 16px (inline), 20px (nav), 24px (feature icons), 40–48px (empty states / hero icons).
- Icon backgrounds: Soft rounded squares (`border-radius: 8px` or `10px`) filled with `#EDE4D0` for featured/section icons.

---

## UI Component Principles

### Buttons
| Variant | Background | Text | Border |
|---|---|---|---|
| Primary | `#8B6F3E` | `#FDFAF5` | None |
| Secondary | `#EDE4D0` | `#8B6F3E` | None |
| Inverted | `#1A1208` | `#FDFAF5` | None |
| Outlined | Transparent | `#8B6F3E` | `1px solid #8B6F3E` |

- Border radius: `8px` for standard buttons, `6px` for small/compact buttons.
- No harsh box shadows — use subtle `box-shadow: 0 1px 3px rgba(26,18,8,0.08)`.
- No rounded pill buttons (`rounded-full`) for primary actions.

### Cards
- Background: `#FDFAF5` (elevated card surface) or `#EDE4D0` (section card)
- Border: `1px solid #D4C9B0`
- Border radius: `12px`
- Padding: `20–24px`
- Hover: slight subtle lift and border accentuation.

### Sidebar / Navigation
- Background: `#F2EDE3` or elevated `#FDFAF5` with `1px solid #D4C9B0` divider
- Active nav item: `#EDE4D0` background pill/box, `#8B6F3E` text and icon, or left accent bar
- Idle nav items: `#9B8E7A` text, hover `#1A1208`
- Brand header: `GenQ` with `Analytics` and `Academic & Autonomous Intelligence` subtitle

### Input Fields & Selects
- Background: `#FDFAF5`
- Border: `1px solid #D4C9B0`
- Focus border: `#8B6F3E`
- Text: `#1A1208`
- Placeholder: `#9B8E7A`
- Border radius: `8px`

### Tags / Badges
- Category / Status tags: `#EDE4D0` background, `#8B6F3E` text, `4px` or `6px` border radius, `10px–11px` font size, uppercase, letter-spaced.
- AI Verification: `GENQ AI` badge in `#EDE4D0` with `#8B6F3E` text.

---

## Tone of Voice

- **Scholarly, authoritative, precise** — vocabulary that reflects rigorous analytical synthesis.
- Use evocative terms: "Deposit Dataset", "Initiate Autonomous Synthesis", "Deliberation Scratchpad", "Skeptic Debate", "Extraction Confidence", "Strategic Recommendations".
- Avoid generic SaaS tropes: not "Upload File", not "Submit Query", not neon gradient badges.

---

## Don'ts

- ❌ No purple, blue, cyan, or neon gradients (e.g. `bg-gradient-to-r from-blue-600 to-indigo-600`, `from-purple-500`)
- ❌ No DM Mono, Inter, or system-ui as primary body fonts
- ❌ No clinical pure white (`#FFFFFF`) backgrounds; use `#FDFAF5` for surfaces and `#F2EDE3` for page background
- ❌ No dark mode clinical black; use `#1A1208` deep warm neutral
- ❌ No emoji in core UI chrome and navigation
- ❌ No circular pills for standard buttons (use `rounded-lg` / 8px)

# Grupo DDM — Design System

Tecnologia financeira para instituições de ensino.
A B2B fintech serving Brazilian schools and universities, helping them recover overdue tuition, manage payment flows, and offer credit to students.

> "Tenha seu setor financeiro mais sustentável: Mais Tempo para o que realmente Importa: Educar."

---

## Sources

This system was reverse-engineered from the public website. Treat it as a faithful approximation, not the canonical source — there is no Figma, no codebase access in this project, and no official brand guidelines were provided.

| Resource | Location | How used |
|---|---|---|
| Marketing site | https://grupoddm.tech/ | Visual + copy reference (homepage). Built on Hostinger Website Builder (Zyro). |
| Subpages referenced (not deep-fetched) | `/quem-somos`, `/recuperacao-de-debitos`, `/servicos-de-credito`, `/data-analise`, `/gesdu`, `/contato`, `/ddmacademy`, `/trabalhe-conosco`, `/conformidade`, `/ddm-empresarial` | URL structure / product naming |
| Student-facing platform | https://www.ddmpay.com.br/ | "Sou Aluno" entry — referenced, not designed here |
| Social | instagram.com/grupoddm · linkedin.com/company/grupoddm |  |

If you have access to internal Figma libraries, brand books, or the source CSS for the marketing site, drop them in the project — this README is the place to update once you do.

---

## Products

Grupo DDM is the parent brand. Five sub-products are referenced on the marketing site, each with its own "*Edu" suffix:

1. **RecuperEdu** — recovery of overdue tuition. The headline product ("Eficiência na Recuperação Financeira").
2. **GesEdu** (sometimes "Gesdu") — institutional payment-flow management dashboard.
3. **CreditEdu** — credit lines for educational institutions.
4. **InvesEdu** — investment / receivables anticipation, paired with CreditEdu.
5. **Data Análise** — analytics for retention + loyalty.

Adjacent surfaces:

- **DDMpay** (ddmpay.com.br) — student-facing payment portal (pix / boleto / card).
- **DDM Empresarial** (`/ddm-empresarial`) — corporate-services arm, separate site.
- **DDMacademy** (`/ddmacademy`) — internal training / careers content.

The sub-product names are presented as wordmarks in display weight throughout the site. Treat "DDM" (uppercase, white-on-orange) as the master mark; treat the "*Edu" wordmarks as product names rendered in the same font as section headings.

---

## File index

```
README.md                   ← you are here
SKILL.md                    ← Agent-skill manifest (works in Claude Code too)
colors_and_type.css         ← CSS custom properties: colors, type, spacing, radii, shadow, motion
assets/                     ← logo, illustrations, photos, partner badges (downloaded from grupoddm.tech)
preview/                    ← design-system cards rendered in the Design System tab
ui_kits/website/            ← high-fidelity recreation of the marketing site
```

`fonts/` is intentionally empty — the production site uses non-disclosed webfonts loaded by the Zyro page builder. We substitute Poppins (display) + Inter (body) from Google Fonts. **See "Fonts" below — this is the single biggest open question in this system.**

---

## Content fundamentals

**Language.** Brazilian Portuguese, exclusively. All copy on the marketing site is pt-BR. Don't translate — generate Portuguese directly when writing for this brand.

**Voice.** Confident, plainspoken, audience-aware. The institution (IE — instituição de ensino) is the hero; DDM is the operator behind the scenes. The headline pattern is consistent:

> *Nós operacionalizamos, você controla.*
> *Tempo livre, apenas controle.*
> *Eficiência na **Recuperação Financeira**.*

Short clauses, separated by line breaks or bold. The brand makes operational promises ("eliminamos todos os atritos") and backs them with concrete metrics ("Mais de 38% Do Market Share educacional", "897 milhões já negociados", "+ R$30MM em receitas antecipadas").

**Pronouns.** "Sua instituição", "seu aluno", "você" (formal-but-warm). The brand uses "nós" / "conosco" for itself ("Já ajudamos mais de 150 instituições"). Never "vocês" or "v.sa.".

**Casing.**
- **Headlines:** Sentence case with a Bold Highlight Word at the end ("Mais Tempo para o que realmente Importa: **Educar.**"). The bolded word is often the punchline.
- **Section eyebrows:** Title Case, short ("Produtos exclusivos", "Para sua instituição", "Para seu aluno").
- **Buttons:** Sentence case with a verb ("Sou aluno", "Sou instituição", "Agendar reunião", "Ver mais", "Enviar").
- **Stats:** mixed — large numbers ("Mais de 38%", "897 milhões", "+ R$30MM") followed by a full-sentence explainer underneath.

**Tone calibration.**
- ✅ "Tenha uma cobrança de mensalidades atrasadas com eficiência e altas taxas de recuperação."
- ✅ "Pensados justamente para ajudar toda a jornada de crescimento de sua instituição."
- ❌ Slangy / hype copy ("revolucionário!", "🚀 Disruptivo!").
- ❌ Tech jargon without translation. The site explicitly defines ERP for the reader: *"Um ERP (Enterprise Resource Planning) é um software que auxilia na administração…"* — assume the reader is a school administrator, not a CTO.

**Emoji.** Not used. The brand expresses warmth through illustrations and orange color, not glyphs.

**Numbers.** Brazilian conventions — `R$30MM` with the currency prefix, `38%` no space, `2.9 milhões` with period as thousands separator (in copy; never as a decimal in financial figures). `Av. Ayrton Senna, 5500, Bl 2, terceiro andar.`

---

## Visual foundations

### Color
Single dominant brand color: **`#FF5706`** orange. Used aggressively — logo, CTA buttons, scribbled underlines on hero words, the squircle backgrounds behind hero photography, illustration accents, and stat callouts. There is no secondary brand color competing with it.

Neutrals lean cool-warm gray (`#939598` for the wordmark "GRUPO" beside the logo, used as the muted-text default). Backgrounds are white or a warm cream. No dark mode is exposed on the marketing site.

### Type
Geometric humanist sans throughout. Headlines are heavy (600–700 weight), tight-tracked, sentence-cased with one **bold word** doing the work. Body is the same family in regular. **No serif anywhere on the marketing site.** No mono (the brand has no developer-facing surface).

### Layout
- Site is wide (~1366–1440 content), with generous vertical spacing between sections (96–128px gaps).
- Section headers center-aligned; product cards alternate between left- and right-aligned text-with-illustration pairs.
- Sticky top nav, full-width footer with three columns + LGPD/ESG badges.
- Mobile collapses to a single column with the same illustrations stacked.

### Imagery
**Two distinct families of imagery, used together:**

1. **Photography** — bright lifestyle shots of people (often students or young professionals) using phones, on a **pure white background**, with a vivid orange squircle cropped behind the subject. Always warm, smiling, never corporate-serious. The orange shape is part of the composition, not a frame around it.

2. **Vector illustrations** — flat, friendly, human characters at desks / phones / laptops in a limited palette (orange, light gray, navy accents, soft pastels). Style is consistent with the Storyset / Pixeltrue family. They are *not* hand-drawn or sketchy — they are clean vector with simple shading.

A scribbled orange underline (`underline-scribble.png`) is used to hand-mark single words in headlines. This is the only "hand" element in the brand.

### Backgrounds
White is the default. Warm cream (`#FAF7F4`) appears for alternate sections. No gradients. No textured / patterned backgrounds. The corporate page (`/ddm-empresarial`) intro uses a single full-bleed photo as a hero background — that's the only photographic background on the site.

### Cards & containers
Generously rounded — `--r-xl` (32px) is the default card corner radius; `--r-2xl` (48px) appears on hero photo crops. No borders on cards by default; subtle shadows (`shadow-md`) on hover only. The orange CTA button is fully pilled (`--r-pill`).

### Shadow + elevation
The site is mostly flat. Drop-shadow appears under: the orange CTA button (orange-tinted, lifts the button off the page), interactive cards (neutral, on hover), and the dashboard mockup screenshot. There is no inner-shadow vocabulary.

### Borders
Only on form inputs and the ghost button. Hairline (`1px solid var(--border)`) — no thick rules.

### Motion
The Zyro builder default — content fades + slides up on scroll-into-view. Buttons get a small `translateY(-1px)` lift on hover. No bounces, no parallax, no scroll-jacking. Logo and illustrations do not animate.

### Hover / press
- **Hover:** buttons darken (orange → orange-600), text links underline, cards gain `shadow-md`. No scale.
- **Pressed:** further darken (orange-700) and revert the hover lift. No scale-down.

### Transparency / blur
Not used. The brand is solid, opaque, confident. No frosted glass, no backdrop-filter, no semi-transparent overlays except a subtle dark-on-image gradient on the corporate hero.

### Corner radii
`6 / 12 / 20 / 32 / 48 / pill`. Ascend from inputs (md) → cards (xl) → photo crops (2xl) → buttons (pill).

### "Protection" gradients vs capsules
The brand uses **capsules** (orange squircles behind photography) rather than darkening gradients to call out subjects. Stat callouts and CTAs use a solid orange capsule + white text — never an orange→pink gradient.

---

## Iconography

**There is no in-house icon system on the marketing site.** What appears is:

- **Right-arrow asset** (`assets/right-arrow.png`) — used as the "Ver mais" link affordance on product cards. It's a flat orange arrow rendered as an image, not an SVG icon.
- **Social icons** — Instagram + LinkedIn brand glyphs in the footer; standard versions, not custom.
- **Compliance badges** — LGPD seal + ESG seal in the footer (`badge-lgpd.png`, `badge-esg.png`) — supplied by the certifying bodies.
- **No emoji.** None. Not in copy, not in CTAs.
- **No unicode glyphs as icons** (no ★, ✓, →, etc.).
- **No icon font** is loaded by the page.

When extending this system, prefer **Lucide** (https://lucide.dev) at stroke-weight 1.5 in `currentColor` for any new UI icons (sidebars, dashboard chrome, settings). It matches the friendly geometric tone of the rest of the brand. **Flagged substitution** — replace with the real set if internal icons exist.

When iconography would compete with illustration (hero, product cards, marketing pages), prefer the vector illustrations in `assets/` instead.

---

## Fonts — flagged substitution

The marketing site is built on Hostinger's Zyro page builder, which loads its own font CSS we cannot inspect in plain text. Visual inspection of the logo wordmark ("GRUPO") and section headings suggests a **geometric humanist sans** in the Poppins / Montserrat / DM Sans family.

This system uses **Poppins** (display) + **Inter** (body) loaded from Google Fonts as a stand-in. Both are open and reasonably close in feel.

> **Action requested from the user:** if you have the canonical font for Grupo DDM, please drop the .woff2 files into `fonts/` and update the `--font-display` / `--font-body` variables in `colors_and_type.css`. Until then, treat anything rendered in this system as an approximation — the typography will be the most visible difference from the real brand.

---

## UI kits

- `ui_kits/website/` — recreation of the public marketing site (homepage + key sections). See `ui_kits/website/README.md` for the included screens.

---

## Quickstart for designers using this system

1. Link `colors_and_type.css` from any HTML file you create.
2. Use `--ddm-orange` for accents and CTAs; never invent a second brand color.
3. Headlines: `font-family: var(--font-display)`, weight 600–700, with one bolded word per heading where the brand convention applies.
4. Photography: subject on white, with an orange squircle behind. Never put a photo on a non-white background unless it's the corporate-page hero.
5. Copy in pt-BR. Confident, short, school-admin audience.
6. Iconography: Lucide stroke-1.5, or a vector illustration from `assets/`.

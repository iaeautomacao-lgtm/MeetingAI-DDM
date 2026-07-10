---
name: grupo-ddm-design
description: Use this skill to generate well-branded interfaces and assets for Grupo DDM (Brazilian fintech for educational institutions — RecuperEdu, GesEdu, CreditEdu, InvesEdu, Data Análise), either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

Key files in this skill:
- `README.md` — brand context, content fundamentals, visual foundations, iconography
- `colors_and_type.css` — CSS custom properties (colors, type, spacing, radii, shadow, motion)
- `assets/` — logo, illustrations, photography, partner badges, compliance seals
- `ui_kits/website/` — HTML/JSX recreation of the marketing site at grupoddm.tech
- `preview/` — visual specimen cards for the design system

Critical brand rules:
- Single dominant color: `#FF5706` orange. Don't invent a second brand color.
- Copy is **always Brazilian Portuguese**. Confident, plainspoken, school-admin audience.
- Headlines follow the pattern "*Lead phrase ... **with a bold punchline word**.*"
- Photography is always lifestyle people on white with an **orange squircle** behind them.
- No emoji, no gradients, no glassmorphism. Solid orange + white + warm cream + flat illustrations.
- Iconography: Lucide stroke-1.5 OR a vector illustration from `assets/`.
- Fonts are a flagged substitution (Poppins + Inter from Google) — replace with the real ones if you have them.

# Grupo DDM — Website UI Kit

High-fidelity recreation of the marketing site at https://grupoddm.tech/.

This kit is a **visual recreation**, not a port of the source code (the production site is built on Hostinger Website Builder / Zyro and we don't have access to its source). Components are simplified for reuse — the goal is pixel-fidelity to the live site, not behavioural parity with the page builder.

## Files
- `index.html` — homepage recreation, assembled from the components below
- `NavBar.jsx` — sticky top nav with the master logo + product menu + social glyphs
- `Hero.jsx` — split hero: headline with scribbled "Recuperação" word + dual CTAs ("Sou aluno" / "Sou instituição") + photography with orange squircle
- `StatRow.jsx` — three big-number stats ("Mais de 38%", "897 milhões", "+R$30MM")
- `ProductGrid.jsx` — four product cards (RecuperEdu, GesEdu, CreditEdu, Data Análise) with arrow-circle "Ver mais"
- `FeatureBand.jsx` — three-column feature row with circular illustrations
- `EmpresarialBand.jsx` — corporate-services callout with full-bleed photo
- `ContactForm.jsx` — bottom form with school-or-college radio toggle
- `Footer.jsx` — three-column footer + LGPD/ESG seals

## Coverage / known gaps
- ✅ Above-fold hero with brand-correct color, typography hierarchy, photo treatment
- ✅ Stat callouts and product card grid
- ✅ Feature highlights and ERP-integrations band
- ✅ Contact form with radio chips
- ✅ Three-column footer
- ❌ Per-product subpages (`/recuperacao-de-debitos`, `/gesdu`, etc.) — not built; navigate to them by clicking nav items, but they 404 in this kit
- ❌ Mobile breakpoint — desktop only at 1280–1440 width
- ❌ Fonts are flagged substitution (Poppins + Inter)

Click "Ver mais", "Sou instituição" or any nav link to see a friendly fallback message in this prototype.

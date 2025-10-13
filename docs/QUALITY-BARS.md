1) HTML semantics & robustness

Use native semantic elements (header, main, footer, nav, section, article, aside, figure/figcaption, ul/ol/li, table/thead/tbody/th/td).

Exactly one <h1> per page; no heading level skips (h2→h3…).

Links are real <a> with clear purpose; buttons are <button> (no <div> pretending).

Tables only for data (with scope or headers association).

Valid, well-formed HTML (Nu HTML checker clean).

2) Accessibility (WCAG 2.2 AA + WAI-ARIA APG for any widgets)

Text alternatives for non-text content (alt or alt="" when purely decorative).

Landmarks present (header/main/nav/footer), skip link, logical reading/focus order.

Keyboard: all interactive controls reachable/operable; no traps; visible focus.

Color/contrast meets AA, respects prefers-reduced-motion.

Forms: explicit <label>/for, helpful errors (aria-describedby), autocomplete tokens.

Name/Role/Value correct for any interactive pattern (follow APG); don’t over-ARIA native elements.

3) Internationalization (i18n)

lang on <html> (and on snippets if mixed languages); UTF-8; directional text where needed (dir).

Content avoids locale-ambiguous formats (clear date/time/units).

hreflang and canonical for translated pages.

4) Metadata & machine-readability

<title>, <meta name="description">, canonical, robots; Open Graph/Twitter cards as needed.

JSON-LD 1.1 for each type (Article/BlogPosting, Product, Organization/WebSite, LocalBusiness/HowTo/FAQ as relevant).

Publish sitemap.xml, robots.txt, feeds (RSS or JSON Feed), and an AgentMap (compact JSON index of page types/relations).

5) Images & media

Responsive <picture> with AVIF/WebP sources; correct sizes/srcset; real width/height (prevents CLS).

loading="lazy" (except LCP image); decoding="async".

Captions/transcripts for audio/video; text alternatives for media.

6) Performance & delivery

Budgets: HTML ≤ 30KB, CSS ≤ 10KB, JS = 0 on read-only pages.

Inline only critical CSS (if needed); otherwise one small CSS file, no blocking scripts.

Preload only what measurably helps LCP (e.g., hero image/font subset); cautious preconnect.

Cache static assets with long Cache-Control and hashed filenames.

7) Privacy & security

Serve over secure contexts (HTTPS); strong CSP, HSTS, Referrer-Policy.

No third-party scripts by default; explicit allow-list if you must add one.

Respect DNT/consent; minimal, privacy-first analytics.

8) Progressive enhancement & resilience

Content and critical actions work without JS.

No information hidden behind client rendering; agents must get the same facts from HTML/JSON-LD.

Graceful degradation for slow networks and reduced-motion users.

9) Quality gates (automated)

axe: 0 critical violations; WCAG checks pass.

Lighthouse (mobile lab): Performance ≥95, Accessibility ≥98, Best-Practices/SEO =100 on representative pages.

Link checker clean; HTML validator clean.
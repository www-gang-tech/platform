---
title: "Manifesto"
summary: "Our principles for building the web: semantic, accessible, fast, and AI-first"
date: 2025-01-11
jsonld: {}
seo:
  description: null
  title: null
---

# Manifesto

**Documents, not apps.** The web was built on hyperlinked documents. We're bringing that back.

## Why We Exist

Modern web publishing has lost its way. Websites that should be simple documents have become bloated JavaScript applications. Publishing platforms force creators into proprietary ecosystems. The fundamental simplicity and accessibility of HTML has been buried under layers of complexity.

**GANG is different.** We believe in:

* **Static-first:** Pre-rendered HTML, no server required
* **Semantic HTML:** Meaningful markup that machines and humans understand
* **Zero JavaScript:** For content pages. If it doesn't need interaction, it doesn't need JS
* **AI-assisted:** Let AI handle the boring parts (alt text, JSON-LD, SEO metadata)
* **Standards-compliant:** Follow W3C specs, not framework opinions
* **Performance budgets:** HTML ≤30KB, CSS ≤10KB per page
* **Accessibility by default:** WCAG 2.2 AA is the baseline, not a feature

## Our Quality Bars

Every page published with GANG meets these standards:

### 1\. HTML Semantics & Robustness

* Use native semantic elements (`<header>`, `<main>`, `<footer>`, `<nav>`, `<article>`, `<section>`)
* Exactly one `<h1>` per page; no heading level skips
* Real `<a>` links with clear purpose; `<button>` for actions (no `<div>` pretending)
* Tables only for data with proper scope/headers
* Valid, well-formed HTML (Nu HTML checker clean)

### 2\. Accessibility \(WCAG 2\.2 AA \+ WAI\-ARIA APG\)

* Text alternatives for all non-text content (meaningful `alt` or `alt=""` for decorative)
* Proper landmarks (`header`/`main`/`nav`/`footer`), skip link, logical reading order
* **Keyboard:** All interactive controls reachable and operable; no keyboard traps; visible focus
* **Color/contrast:** Meets AA standards; respects `prefers-reduced-motion`
* **Forms:** Explicit `<label>`/`for`; helpful errors with `aria-describedby`; autocomplete tokens
* Correct Name/Role/Value for interactive patterns (follow APG); don't over-ARIA native elements

### 3\. Internationalization \(i18n\)

* `lang` attribute on `<html>` (and on snippets for mixed languages)
* UTF-8 encoding; directional text support where needed
* Avoid locale-ambiguous formats for dates, times, and units
* `hreflang` and canonical links for translated pages

### 4\. Metadata & Machine\-Readability

* Complete `<title>`, `<meta name="description">`, canonical, robots meta
* Open Graph and Twitter Card tags
* **JSON-LD 1.1** for structured data (Article, Product, Organization, etc.)
* Publish `sitemap.xml`, `robots.txt`, feeds (JSON Feed), and **AgentMap**
* Make your content discoverable by AI agents and search engines

### 5\. Images & Media

* Responsive `<picture>` elements with AVIF/WebP sources
* Correct `sizes` and `srcset` attributes
* Real `width` and `height` attributes (prevents CLS)
* `loading="lazy"` (except LCP image); `decoding="async"`
* Captions and transcripts for audio/video

### 6\. Performance & Delivery

* **Budgets enforced:** HTML ≤30KB, CSS ≤10KB, JS=0 on content pages
* Inline only critical CSS; one small CSS file, no blocking scripts
* Preload only what measurably helps LCP (e.g., hero image, font subset)
* Cache static assets with long `Cache-Control` and hashed filenames
* **Lighthouse scores:** Performance ≥95, Accessibility ≥98, Best Practices/SEO =100

### 7\. Privacy & Security

* Serve over HTTPS; strong CSP, HSTS, Referrer-Policy headers
* **No third-party scripts by default**; explicit allow-list only
* Respect Do Not Track and consent
* Privacy-first analytics (or none at all)

### 8\. Progressive Enhancement & Resilience

* Content and critical actions work **without JavaScript**
* No information hidden behind client rendering
* Agents get the same facts from HTML and JSON-LD
* Graceful degradation for slow networks and reduced-motion users

### 9\. Quality Gates \(Automated\)

We don't just recommend these standards—we enforce them:

* **axe:** 0 critical violations; all WCAG checks pass
* **Lighthouse (mobile lab):** Performance ≥95, Accessibility ≥98, Best-Practices/SEO =100
* Link checker clean; HTML validator clean
* **CI blocks merges** on failures

## The AI-First Difference

Traditional CMSs make you fill out 50 form fields for every post. GANG is different:

1. **Write your content** in Markdown
2. **Run `gang optimize`** — AI fills in:
    * SEO titles and descriptions
    * Image alt text
    * JSON-LD structured data
    * OpenGraph metadata
3. **Run `gang build`** — Get a perfect, standards-compliant static site

The AI is your assistant, not your master. It fills in the tedious metadata, but you maintain complete control over your content.

## Documents, Not Apps

We're opinionated about what the web should be:

**For reading:** Just HTML and CSS. No JavaScript. Fast, accessible, and works everywhere.

**For interaction:** Progressive enhancement. Start with working HTML, enhance carefully with minimal JS.

**For publishing:** Static generation. Pre-render everything. Deploy to a CDN. Sleep well knowing your site won't crash.

## Join Us

GANG is open source. Use it, extend it, fork it. Our only demand: **respect the quality bars.**

Build the web we deserve.

***

**Start building:** `pip install gang-cli && gang init`

**Read more:** [Documentation](/pages/about/) · [GitHub](https://github.com/www-gang-tech/platform)
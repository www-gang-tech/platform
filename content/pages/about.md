---
date: 2025-01-11
jsonld: {}
seo:
  description: Learn about GANG, the AI-first static publishing platform that builds
    semantic, accessible, and fast websites. Zero JavaScript, WCAG AA compliant.
  title: About - AI-First Static Publishing
status: published
summary: Learn about GANG, the AI-first static publishing platform that builds semantic,
  accessible, and fast websites. Zero JavaScript, WCAG AA compliant.
title: About GANG Platform - AI-First Static Publishing
---


# About

**GANG Website** is an AI-first static publishing platform that builds the web we deserve: semantic, accessible, and fast.

## Mission

We believe the web should be built on documents, not apps. Modern web publishing has lost its way with bloated JavaScript applications and proprietary ecosystems. GANG brings back the fundamental simplicity and accessibility of HTML while adding AI-powered intelligence.

## Features

### **Requirements**
- **Static-first:** Pre-rendered HTML, no server required
- **Semantic HTML:** Meaningful markup that machines and humans understand  
- **Zero JavaScript:** For content pages. If it doesn't need interaction, it doesn't need JS
- **AI-assisted:** Let AI handle the boring parts (alt text, JSON-LD, SEO metadata)
- **Standards-compliant:** Follow W3C specs, not framework opinions

### **Performance**
- **Enforced budgets:** HTML ≤30KB, CSS ≤10KB, JS=0 on content pages
- **Lighthouse scores:** Performance ≥95, Accessibility ≥98, Best Practices/SEO =100
- **Core Web Vitals:** Sub-2.5s LCP, minimal CLS, fast INP
- **Progressive enhancement:** Works without JavaScript, enhanced with minimal JS

### **Accessibility**
- **WCAG 2.2 AA compliance** by default, not as an afterthought
- **Semantic HTML** with proper landmarks and heading structure
- **Keyboard navigation** and screen reader support
- **Color contrast** that meets AA standards
- **No information hidden** behind client rendering

## Enforcements

Every page published with GANG meets these standards:

1. **HTML Semantics & Robustness** - Native semantic elements, valid markup
2. **Accessibility (WCAG 2.2 AA)** - Complete keyboard navigation, proper ARIA
3. **Internationalization** - UTF-8, language attributes, locale-aware formats
4. **Metadata & Machine-Readability** - Complete meta tags, JSON-LD, sitemaps
5. **Images & Media** - Responsive pictures, proper alt text, lazy loading
6. **Performance & Delivery** - Enforced budgets, optimized assets
7. **Privacy & Security** - Strong CSP, no third-party scripts by default
8. **Progressive Enhancement** - Works without JS, graceful degradation

## Approach

Traditional CMSs make you fill out 50 form fields for every post. GANG is different:

1. **Write your content** in Markdown
2. **Run `gang optimize`** — AI fills in:
   - SEO titles and descriptions
   - Image alt text
   - JSON-LD structured data
   - OpenGraph metadata
3. **Run `gang build`** — Get a perfect, standards-compliant static site

The AI is your assistant, not your master. It fills in the tedious metadata, but you maintain complete control over your content.

## Built for the Future

GANG is designed for:
- **Content creators** who want to focus on writing, not technical setup
- **Developers** who need a fast, reliable publishing platform
- **Businesses** that require performance, accessibility, and SEO
- **Anyone** who believes the web should be fast, accessible, and semantic

## Open Source

GANG is open source and available on [GitHub](https://github.com/www-gang-tech/platform). Use it, extend it, fork it. Our only demand: **respect the quality bars.**

## Get Started

Ready to build the web we deserve?

```bash
# Install GANG CLI
pip install gang-cli

# Initialize a new site
gang init

# Start building
gang serve
```

**Learn more:** [Documentation](/pages/about/) · [GitHub](https://github.com/www-gang-tech/platform) · [Contact](/pages/contact/)
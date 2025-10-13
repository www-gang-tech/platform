---
title: Frequently Asked Questions
date: 2025-10-12
author: GANG Team
summary: Common questions about the GANG platform
---

# Frequently Asked Questions

## General Questions

### What is GANG?

GANG is an AI-first static publishing platform that prioritizes accessibility, performance, and machine legibility. We build the smallest possible website that guarantees these core principles, then add only features that measurably improve comprehension, trust, or conversion.

### Who is GANG for?

GANG is designed for content creators, publishers, and businesses who want:
- Lightning-fast websites
- Perfect accessibility scores
- SEO and AI optimization
- E-commerce integration
- Complete control over their content

### Is GANG open source?

Yes! GANG is open source and available on [GitHub](https://github.com/www-gang-tech/platform).

## Technical Questions

### What technologies does GANG use?

- **Backend:** Python with Click CLI
- **Templates:** Jinja2
- **Content:** Markdown with YAML frontmatter
- **Frontend:** Semantic HTML5, modern CSS, minimal JavaScript
- **Build:** Static site generation

### What are the performance budgets?

- **HTML:** ≤30KB per page
- **CSS:** ≤10KB (currently ~9KB minified)
- **JavaScript:** ≤10KB (currently ~6KB minified)
- **Lighthouse Scores:** Performance ≥95, Accessibility ≥98, Best Practices 100, SEO 100

### Does GANG require JavaScript?

No! All core functionality works without JavaScript. JavaScript is used only for progressive enhancement:
- Shopping cart state management
- Product variant switching
- Real-time form updates

### What accessibility standards does GANG follow?

GANG is fully conformant with **WCAG 2.2 Level AA**. This includes:
- Semantic HTML structure
- Proper heading hierarchy
- Keyboard navigation
- Screen reader support
- Color contrast compliance
- Focus indicators
- Alt text for images

## Content & Publishing

### How do I create content?

Content is written in Markdown with YAML frontmatter:

```markdown
---
title: My Article
date: 2025-10-12
author: Your Name
category: Tutorial
tags: [Web Development, Accessibility]
---

# My Article

Your content here...
```

### Can I schedule content?

Yes! Use the `publish_date` field in frontmatter:

```yaml
---
title: Future Post
publish_date: 2025-12-01
---
```

Run `gang build` and only published content will appear.

### How does the taxonomy system work?

GANG uses a Notion-style hierarchical taxonomy:
- **Categories:** Product → Font, Tutorial → Development
- **Tags:** Open Source, Typography, SEO
- **Commands:** `gang taxonomy list`, `gang taxonomy add-category`

## E-commerce

### What platforms does GANG support?

Currently:
- **Shopify** (fully integrated)
- **Stripe** (planned)
- **Gumroad** (planned)

### How does the shopping cart work?

- **Storage:** localStorage (client-side)
- **Add to Cart:** Form submission with JavaScript enhancement
- **Checkout:** Direct to Shopify checkout
- **No server required:** Fully static

### Can I track inventory?

Yes! GANG syncs with Shopify's inventory system and shows real-time stock status on product pages.

## SEO & AI

### How is GANG optimized for AI?

- **AgentMap.json:** Machine-readable site navigation
- **JSON-LD:** Structured data on every page
- **Content API:** JSON endpoints for all content
- **Semantic HTML:** Proper document structure
- **RSS Feed:** JSON Feed format

### What structured data does GANG include?

- **Articles:** Blog posts with author, date, tags
- **Products:** Full product schema with variants
- **Organization:** Company information
- **Breadcrumbs:** Navigation hierarchy
- **CollectionPage:** Category and list pages

## Performance

### How fast is GANG?

- **First Contentful Paint:** <1s
- **Time to Interactive:** <2s
- **Total Page Weight:** <30KB (HTML + CSS + JS)
- **Lighthouse Performance:** 95-100

### What optimizations does GANG use?

- **HTML Minification:** ~18% reduction
- **CSS Minification:** ~35% reduction
- **JavaScript Minification:** ~41% reduction
- **Resource Hints:** Preload, preconnect
- **Deferred Scripts:** Non-blocking JavaScript
- **Image Optimization:** AVIF/WebP with fallbacks

## Support

### How do I get help?

- **Documentation:** Check our [GitHub repository](https://github.com/www-gang-tech/platform)
- **Issues:** Report bugs on GitHub
- **Email:** support@gang.tech
- **Community:** Join our discussions

### Can I contribute?

Absolutely! We welcome contributions:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request
4. Follow our code style and accessibility guidelines

## Pricing

### Is GANG free?

Yes! GANG is open source and free to use. You only pay for:
- Hosting (Cloudflare Pages, Netlify, etc.)
- Optional services (Shopify, Klaviyo, etc.)
- Media storage (Cloudflare R2, S3, etc.)

### What are the hosting costs?

Typical costs:
- **Cloudflare Pages:** Free tier available
- **Cloudflare R2:** $0.015/GB/month
- **Domain:** ~$10-15/year

For most sites: **<$5/month total**

---

*Have more questions? [Contact us](/pages/contact/)*

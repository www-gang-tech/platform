---
title: Features
date: 2025-10-21
summary: Complete list of GANG platform features and capabilities
status: published
---

# Platform Features

A comprehensive overview of all features available in the GANG platform.

## Core Publishing Features

### Static Site Generation
- ✅ Markdown with YAML frontmatter
- ✅ Jinja2 templating engine
- ✅ Hot reload development server (`gang serve`)
- ✅ Incremental builds with performance profiling
- ✅ Build caching system (MD5-based)
- ✅ HTML minification (18% reduction)
- ✅ CSS minification (35% reduction)
- ✅ JavaScript minification (36% reduction)

### Content Management System (Studio)
- ✅ Web-based editor (Toast UI)
- ✅ Live markdown editing
- ✅ File browser with content organization
- ✅ Save/publish workflow
- ✅ Real-time preview
- ✅ SEO preview pane (infrastructure ready)
- ✅ Slug management UI

## Content Types

- ✅ **Posts** - Blog articles with dates and tags
- ✅ **Pages** - Static pages (About, Contact, Manifesto, FAQ, WCAG)
- ✅ **Projects** - Portfolio items
- ✅ **Newsletters** - Email archive with public listing
- ✅ **Products** - E-commerce (Shopify integration)

## Content Management Features

### Content Quality & Analysis
- ✅ Content Quality Analyzer (`gang analyze`)
  - Readability scoring (Flesch-Kincaid)
  - SEO analysis
  - Structure validation
  - Accessibility checks
  - Batch analysis mode
  - JSON output for CI/CD
  - Minimum score enforcement (default: 85)

### Link Management
- ✅ Link Validator (`gang validate --links`)
  - Internal link checking
  - External HTTP validation
  - Broken link detection
  - Whitelist for git remotes
  - JSON output
- ✅ AI-Powered Link Fixer (`gang fix`)
  - Suggests fixes for broken links
  - Semantic similarity matching
  - Git commit integration

### Content Scheduling
- ✅ Publish Date Support
  - Future-dated content
  - Draft/scheduled/published states
  - `gang schedule` - View schedule
  - `gang set-schedule` - Set publish dates
  - Build-time filtering

### Content Versioning
- ✅ Git-Based History
  - `gang history <file>` - View changes
  - `gang restore <file> <commit>` - Restore version
  - `gang changes` - Recent changes
  - Full diff support

### Slug Management
- ✅ Slug Checker (`gang slugs`)
  - Uniqueness validation
  - Integrated into build process
  - Conflict detection
- ✅ Slug Renaming (`gang rename-slug`)
  - Safe renaming with file moves
  - Optional 301 redirect creation
  - CLI and CMS UI support

### Taxonomy System
- ✅ Hierarchical Categories
  - Product → Font, Design, Software, Hardware
  - Tutorial → Development, Design, Marketing
  - News → Announcement, Release, Update
  - Opinion → Essay, Review, Analysis
- ✅ Tag Management
  - `gang taxonomy list` - View all
  - `gang taxonomy add-category` - Add categories
  - `gang taxonomy add-tag` - Add tags
  - `gang taxonomy analyze` - Usage analysis
  - SEO-friendly breadcrumbs
  - Related content suggestions

### Content Import
- ✅ Multi-Source Import (`gang import-content`)
  - File upload
  - Clipboard paste
  - Image extraction
  - Image compression
  - Cloudflare R2 upload
  - AI alt text generation
  - AI category suggestion
  - Slug uniqueness checking

## E-Commerce Features

### Product Management
- ✅ Multi-Platform Aggregation
  - Shopify (fully integrated via Admin REST API)
  - Stripe (infrastructure ready)
  - Gumroad (infrastructure ready)
  - Product sync (`gang products sync`)
  - Status filtering (Draft/Active/Archived)
- ✅ Product Pages
  - Product Listing Page (PLP)
  - Product Detail Pages (PDP)
  - Variant support (colors, sizes)
  - Real-time inventory tracking
  - Schema.org Product JSON-LD
  - Image galleries (6 images per product)
  - Dynamic forms with variant selection

### Shopping Cart
- ✅ Client-Side Cart (localStorage)
  - Add to cart from PDP
  - Cart page (`/cart/`)
  - Update quantities (JavaScript)
  - Remove items (JavaScript)
  - Cart count badge (all pages)
  - Persistent across sessions
  - Works without JS (progressive enhancement)
- ✅ Checkout
  - Direct to Shopify checkout
  - Variant-specific URLs
  - Quantity handling
  - No server required (fully static)

### Inventory Management
- ✅ Real-time stock status
- ✅ Out-of-stock detection
- ✅ Variant-level inventory
- ✅ Button disable when out of stock
- ✅ Visual indicators (✓ In Stock / ✗ Out of Stock)

## Email & Newsletter Features

### Email System (Multi-ESP)
- ✅ Supported ESPs:
  - Klaviyo (recommended for e-commerce)
  - Buttondown (simple newsletters)
  - ConvertKit
  - MailerLite
  - Postmark
  - SendGrid
- ✅ Email Templates
  - Minimal, accessible HTML
  - Single column, 600px max-width
  - Semantic structure
  - 16px base font, system fonts
  - High contrast (WCAG AA)
  - Alt text on images
  - Plain text version included

### Klaviyo Integration
- ✅ Campaign Management
  - `gang email klaviyo-create` - Create from post
  - `gang email klaviyo-lists` - View lists
  - `gang email klaviyo-campaigns` - View campaigns
  - Native Shopify sync
  - Revenue attribution
  - Customer segmentation
- ✅ E-Commerce Flows (templates ready)
  - Abandoned cart recovery
  - Welcome series
  - Post-purchase
  - Browse abandonment
  - Win-back campaigns
  - Product launches

### Newsletter Archive
- ✅ Public Newsletter Listing
  - `/newsletters/` - Archive page
  - Individual newsletter pages with slugs
  - Automatic from Klaviyo campaigns
  - Chronological listing
  - Search indexing
  - RSS feed inclusion

### Deliverability Tools
- ✅ DNS Checker (`gang email check-deliverability`)
  - SPF record validation
  - DKIM checking
  - DMARC verification
  - MX record lookup
  - Setup guide generation

## SEO & Discovery Features

### Search Engine Optimization
- ✅ Meta Tags
  - Title, description on every page
  - Canonical URLs
  - Open Graph (Facebook, LinkedIn)
  - Twitter Cards
  - Language tags
- ✅ Structured Data (JSON-LD)
  - Article schema (posts)
  - Product schema (e-commerce)
  - Organization schema
  - Breadcrumb navigation
  - CollectionPage (listings)
  - WebSite schema
- ✅ Sitemaps
  - XML sitemap (`sitemap.xml`)
  - HTML sitemap (`/sitemap/`)
  - Automatic generation on build
  - All content types included
- ✅ RSS Feed
  - JSON Feed format (`/feed.json`)
  - Linked in footer
  - All posts included

### AI Optimization
- ✅ AgentMap.json
  - Machine-readable site navigation
  - Canonical URLs
  - Content types
  - Relationships mapping
  - API endpoints
- ✅ Content API
  - JSON endpoints for all content
  - `/api/content.json`
  - `/api/products.json`
  - Programmatic access
- ✅ Auto-Generated Metadata
  - AI alt text for images
  - AI category suggestions
  - AI content optimization
  - AI link suggestions

### Static Site Search
- ✅ Client-side search index
- ✅ Search page (`/search/`)
- ✅ Full-text indexing
- ✅ No server required

## Accessibility Features

### WCAG 2.2 Level AA Compliance
- ✅ Semantic HTML (proper landmarks)
- ✅ Single H1 per page
- ✅ No heading skips
- ✅ Color contrast (AA compliant)
  - Text: #1a1a1a on #ffffff
  - Links: #0052a3 (sufficient contrast)
  - Muted: #595959
- ✅ Link distinguishability (underlines)
- ✅ Keyboard navigation
- ✅ Focus indicators
- ✅ Alt text on images
- ✅ Form labels and descriptions
- ✅ ARIA attributes where needed

### WCAG Conformance Statement
- ✅ Published at `/pages/wcag-conformance/`
- ✅ Full conformance details
- ✅ Assessment approach
- ✅ Feedback mechanism
- ✅ Compatibility information

## Performance Features

### Performance Budgets
- ✅ Enforced Limits:
  - HTML: ≤30KB per page
  - CSS: ≤10KB (currently ~9KB minified)
  - JS: ≤10KB (currently ~6KB minified)
  - Lighthouse: Perf ≥95, A11y ≥98, BP 100, SEO 100

### Optimization
- ✅ Resource Hints
  - Preload for CSS
  - Preconnect for CDNs
  - DNS-prefetch optimization
- ✅ Progressive Enhancement
  - Works without JavaScript
  - Deferred script loading
  - Non-blocking resources

### Performance Monitoring
- ✅ Build performance profiling
- ✅ Page size tracking (shown in footer)
- ✅ Lighthouse score display (all 100s)
- ✅ Last updated timestamps

## Media Management

### Cloudflare R2 Integration
- ✅ Commands:
  - `gang media upload` - Upload files
  - `gang media list` - List objects
  - `gang media sync` - Sync directory
  - `gang media delete` - Remove objects
- ✅ Image Processing:
  - Resize images
  - Format conversion (AVIF, WebP)
  - Compression
  - Automatic optimization

## Security & Privacy

### Security Headers
- ✅ Content Security Policy (CSP)
- ✅ Referrer Policy
- ✅ External link security (`rel="noopener noreferrer"`)
- ✅ Automatic external link processing
- ✅ Form action validation

### Privacy-First
- ✅ No tracking pixels in emails
- ✅ No third-party analytics scripts
- ✅ Server-side analytics ready (Cloudflare)
- ✅ GDPR-friendly email workflow

## Design & UI Features

### Design System
- ✅ Layout:
  - 800px max-width (centered)
  - Consistent spacing
  - Responsive grid
  - Mobile-first
- ✅ Typography:
  - System fonts (no web fonts)
  - 16px base
  - 1.6 line-height
  - Proper heading hierarchy
- ✅ Color System:
  - CSS custom properties
  - Light/dark mode toggle
  - High contrast
  - AA-compliant colors
- ✅ Components:
  - Minimal, clean aesthetic
  - Accessible forms
  - Semantic buttons

### Dark Mode
- ✅ CSS-only toggle (`:has()` selector)
- ✅ Site-wide persistence
- ✅ Respects system preference
- ✅ Smooth transitions
- ✅ All pages supported

## Comments & Reviews

### Comment System
- ✅ Database-free comments (static YAML files)
- ✅ Comment forms on posts and products
- ✅ Manual approval workflow
- ✅ n8n webhook integration
- ✅ GitHub issue-based approval queue
- ✅ Privacy-focused (email hashing)
- ✅ Spam protection (honeypot)
- ✅ Progressive enhancement
- ✅ CLI management (`gang comments`)

## Build & Deploy Features

### Build Process
- ✅ Commands:
  - `gang build` - Full build
  - `gang build --profile` - With profiling
  - `gang build --check-quality` - With quality gates
  - `gang build --validate-links` - With link validation
  - `gang serve` - Dev server with live reload
- ✅ Quality Gates:
  - Slug uniqueness checking
  - Content quality scoring (min: 85)
  - Link validation (optional)
  - Lighthouse assertions
- ✅ Outputs:
  - Static HTML files
  - Minified CSS/JS
  - Sitemap (XML + HTML)
  - RSS feed (JSON Feed)
  - AgentMap.json
  - robots.txt
  - Search index
  - Product pages
  - Newsletter archive

### 301 Redirects
- ✅ Redirect Management (`gang redirects`)
  - Add redirects
  - Remove redirects
  - List all redirects
  - Validate redirects
  - Platform-specific generation:
    - Cloudflare (`_redirects`)
    - Nginx (`redirects.conf`)
    - Netlify (`_redirects`)

## CLI Commands

### Content Management
- `gang serve` - Dev server with live reload
- `gang build` - Build static site
- `gang optimize` - AI content optimization
- `gang analyze` - Content quality analysis
- `gang validate` - Link validation
- `gang fix` - AI-powered link fixing

### Content Scheduling & Versioning
- `gang schedule` - View schedule
- `gang set-schedule` - Schedule post
- `gang history` - View version history
- `gang restore` - Restore to version
- `gang changes` - Recent changes

### E-Commerce
- `gang products sync` - Sync products
- `gang products list` - List products

### Email Marketing
- `gang email klaviyo-create` - Create from post
- `gang email klaviyo-lists` - View lists
- `gang email klaviyo-campaigns` - View campaigns

### Media Management
- `gang media upload` - Upload files
- `gang media list` - List objects
- `gang media sync` - Sync directory
- `gang media delete` - Remove objects

### Quality & Performance
- `gang check` - Validate contracts
- `gang performance` - View build performance history
- `gang slugs` - Check slug uniqueness

### Comments
- `gang comments list` - List comments
- `gang comments approve` - Approve comment
- `gang comments reject` - Reject comment
- `gang comments delete` - Delete comment
- `gang comments stats` - View statistics

## Technical Specifications

### Frontend Stack
- ✅ HTML: Semantic HTML5
- ✅ CSS: Single external file (9KB minified)
- ✅ JavaScript: Minimal vanilla JS (6KB minified)
- ✅ Images: AVIF/WebP with fallbacks
- ✅ Fonts: System fonts only

### Backend Stack
- ✅ Language: Python 3.13
- ✅ CLI: Click framework
- ✅ Templates: Jinja2
- ✅ Markdown: Python-Markdown with extensions
- ✅ YAML: PyYAML for frontmatter
- ✅ HTTP: Requests for API calls
- ✅ File watching: Watchdog

### External Integrations
- ✅ Shopify: Admin REST API
- ✅ Klaviyo: v2024-10-15 API
- ✅ Cloudflare R2: S3-compatible
- ✅ Anthropic API: Claude for AI features
- ✅ ESPs: 6 providers supported

## Quality Metrics

### Performance Achievements
- **HTML:** ~8KB average (30KB budget)
- **CSS:** 9KB minified (10KB budget)
- **JavaScript:** 6KB total (10KB budget)
- **Total Page Weight:** ~23KB (well under budget)
- **Lighthouse Scores:** 100/100/100/100
- **Build Time:** ~2-3 seconds
- **Minification Savings:** ~12KB (37.9%)

### Content Scale
- **Posts:** Unlimited
- **Pages:** Unlimited
- **Projects:** Unlimited
- **Newsletters:** Unlimited
- **Products:** Unlimited (Shopify-synced)
- **Images:** Unlimited (R2 storage)

## Platform Statistics

- **Total Features:** 60+
- **CLI Commands:** 50+
- **Content Types:** 5
- **Templates:** 9
- **Core Modules:** 20+
- **ESP Integrations:** 6
- **Product Platforms:** 3 (Shopify active)
- **Lines of Code:** ~15,000+
- **Documentation Files:** 20+

---

**Status:** 🚀 Production Ready

*GANG Platform v1.0 - AI-first static publishing with e-commerce, newsletters, and comments*



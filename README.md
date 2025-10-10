# GANG - AI-First Static Publishing Platform

**Zero-compromise static publishing:** Semantic HTML, WCAG 2.2 AA, sub-2.5s LCP, 0 JS on content pages.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install CLI
cd cli/gang
pip install -e .
cd ../..

# Build your site
gang build

# Validate quality
gang check

# Start Studio CMS
gang studio

# Process images (optional)
gang image public/images/

# Optimize with AI (optional, requires API key)
export ANTHROPIC_API_KEY=sk-ant-...
gang optimize
```

## Features

✅ **Build-time AI** - Fills missing SEO, alt text, JSON-LD  
✅ **Template Contracts** - Enforces semantics, a11y, budgets  
✅ **Studio CMS** - Split-view editor with live preview  
✅ **Git-Based** - All content in Markdown, fully portable  
✅ **Performance First** - HTML ≤30KB, CSS ≤10KB, JS=0  
✅ **CI/CD Built-in** - Lighthouse + axe audits on every deploy  

## Project Structure

```
gang-platform/
├── cli/gang/              # CLI tool
├── content/               # Markdown content
├── templates/             # HTML templates
├── .github/workflows/     # CI/CD
└── gang.config.yml        # Configuration
```

## Configuration

Edit `gang.config.yml` to customize:
- Site metadata
- Performance budgets
- AI settings
- Content types

## Environment Variables

For AI optimization (optional):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

For Cloudflare deployment (set in GitHub Secrets):

```bash
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...
```

## Development Status

✅ **Full Feature Release** - All core features implemented and production-ready

- [x] Project structure
- [x] Configuration system
- [x] Sample content
- [x] CI/CD pipeline with Lighthouse + axe
- [x] Full CLI implementation
- [x] Studio CMS with live preview
- [x] Jinja2 template engine
- [x] AI optimization with Anthropic
- [x] Contract validation system
- [x] Image processing (responsive, AVIF/WebP)
- [x] Sitemap, robots.txt, feed.json generation
- [x] JSON-LD structured data

## CLI Commands

```bash
gang build                    # Build static site
gang check                    # Validate contracts
gang optimize                 # AI content optimization
gang image <dir>              # Process images
gang studio                   # Start CMS (port 3000)
gang --help                   # Show all commands
```

## Features

See [FEATURES.md](FEATURES.md) for complete feature documentation.

## Documentation

- `OPERATE.md` - Complete operating guide (to be created)
- `gang.config.yml` - All configuration options
- Sample content in `content/` directory

## License

MIT License

---

**Ready to build the future of static publishing!** 🚀

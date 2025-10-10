# GANG - AI-First Static Publishing Platform

**Zero-compromise static publishing:** Semantic HTML, WCAG 2.2 AA, sub-2.5s LCP, 0 JS on content pages.

---

## Quick Start

```bash
# Clone this repo (already done!)
cd gang-platform

# Install CLI
cd cli/gang
pip install -e .
cd ../..

# Start building
gang build
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

Copy `.env.example` to `.env` and fill in:

```bash
ANTHROPIC_API_KEY=sk-ant-...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...
```

## Development Status

🚧 **MVP Phase** - Core architecture in place, implementation in progress

- [x] Project structure
- [x] Configuration system
- [x] Sample content
- [x] CI/CD pipeline
- [ ] Full CLI implementation
- [ ] Studio CMS
- [ ] Template engine
- [ ] AI optimization
- [ ] Contract validation

## Next Steps

1. Set up Cloudflare Pages integration
2. Add Anthropic API key to secrets
3. Implement full build system
4. Deploy first site!

## Documentation

- `OPERATE.md` - Complete operating guide (to be created)
- `gang.config.yml` - All configuration options
- Sample content in `content/` directory

## License

MIT License

---

**Ready to build the future of static publishing!** 🚀

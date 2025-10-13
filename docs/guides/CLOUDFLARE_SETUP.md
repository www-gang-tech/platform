# Cloudflare Pages Setup Guide

This guide explains how to configure Cloudflare Pages to successfully deploy the GANG platform.

## Build Configuration

In your Cloudflare Pages project settings, configure the following:

### Build Settings

**Framework preset:** None

**Build command:**
```bash
bash build.sh
```

**Build output directory:**
```
dist
```

### Environment Variables

No environment variables are required for basic deployment. 

For AI optimization features (future), add:
- `ANTHROPIC_API_KEY` - Your Anthropic API key

### Python Version

Ensure Python 3.8+ is available in the build environment. Cloudflare Pages typically provides this by default.

## Current Build Process

The `build.sh` script performs these steps:

1. **Install dependencies** - Installs Python packages from `requirements.txt`
2. **Install GANG CLI** - Installs the CLI tool locally
3. **Build site** - Runs `gang build` to generate static HTML
4. **Output** - Creates the `dist/` directory with your site

## What Gets Built

The build system:
- Converts all Markdown files in `content/` to semantic HTML
- Creates index pages for posts, projects, and pages
- Copies public assets to `dist/assets/`
- Generates clean URLs with `/path/` structure
- Includes zero JavaScript, semantic HTML, and accessible markup

## Testing Locally

To test the build on your machine:

```bash
# Install dependencies
pip install -r requirements.txt

# Install CLI
cd cli/gang
pip install -e .
cd ../..

# Build
gang build

# Serve locally (optional)
python -m http.server 8000 --directory dist
```

Then visit `http://localhost:8000`

## Troubleshooting

### "Output directory 'dist' not found"

This error means the build command failed or didn't create the `dist` directory. Check:
1. Build command is set to `bash build.sh` (not `echo "Static files"`)
2. Python 3.8+ is available
3. All dependencies can be installed

### Build timeout

If builds take too long, you may need to:
1. Reduce the number of markdown files
2. Simplify content processing
3. Check for infinite loops in the build script

## Performance Features

Built-in features for optimal performance:
- HTML ≤30KB per page
- CSS inlined in `<style>` tags (≤10KB)
- Zero JavaScript on content pages
- Semantic HTML5 with proper landmarks
- WCAG 2.2 AA accessibility

## Next Steps

After successful deployment:
1. Configure custom domain
2. Set up preview branches
3. Add build notifications
4. Implement CI/CD audits (Lighthouse, axe)

---

**Questions?** Check the main README or open an issue on GitHub.


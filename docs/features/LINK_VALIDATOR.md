# Link Validator

**Validate internal and external links at build time to prevent broken links from going live.**

## Features

### 🔗 Comprehensive Link Checking

- ✓ **Internal links** - Validates links between your pages
- ✓ **External links** - HTTP checks for 404s, timeouts, etc.
- ✓ **Redirect detection** - Finds 301/302 redirects
- ✓ **Image validation** - Checks image URLs (warns on external)
- ✓ **Anchor links** - Smart handling of # fragments
- ✓ **Asset links** - Validates links to static files
- ✓ **Build integration** - Block builds with broken links
- ✓ **Performance** - Caches external URL checks

---

## Usage

### Validate All Links

```bash
gang validate --links
```

### Get AI-Powered Fix Suggestions

```bash
# Requires ANTHROPIC_API_KEY environment variable
export ANTHROPIC_API_KEY=sk-ant-...

# Get intelligent suggestions for broken links
gang validate --links --suggest-fixes
```

**AI analyzes:**
- Broken URLs and their context
- Link text to understand intent
- Available pages on your site  
- Error types and patterns

**AI suggests:**
- Best matching internal pages (with confidence)
- Alternative external URLs
- Web Archive links for dead pages
- Whether to remove outdated links

**Output:**
```
🔗 Validating links...
============================================================
🔗 Link Validation Report
============================================================

📊 SUMMARY
├─ Files scanned: 4
├─ Total links: 15
├─ Internal links: 8
└─ External links: 7

❌ BROKEN INTERNAL LINKS: 1
  pages/manifesto.md
  └─ [Documentation](/docs)

❌ BROKEN EXTERNAL LINKS: 1
  pages/manifesto.md
  └─ https://github.com/www-gang-tech/platform → HTTP 404

⚠️  REDIRECTS: 2
  posts/my-post.md
  └─ https://old-site.com/article → 301
     Redirects to: https://new-site.com/article

============================================================
Overall Status: FAILED ❌
Total broken links: 2
============================================================

Exit code: 1
```

---

### Internal Links Only (Fast)

```bash
# Skip external link checks (faster)
gang validate --links --internal-only
```

**When to use:**
- Quick pre-commit checks
- CI for every commit
- Local development

---

### Validate Links During Build

```bash
# Block build if broken links found
gang build --validate-links
```

**Output (on failure):**
```
🔨 Building site...
🔗 Validating links...
❌ Found 2 broken link(s):
  - pages/manifesto.md: /docs (internal)
  - pages/manifesto.md: https://github.com/... → HTTP 404

Run 'gang validate --links' for full report
Build aborted due to broken links

Exit code: 1 (build stops)
```

**Output (on success):**
```
🔨 Building site...
🔗 Validating links...
✓ All 15 links valid

📦 Copying public assets...
...
✅ Build complete!
```

---

### JSON Output (CI/CD)

```bash
gang validate --links --format json
```

**Output:**
```json
{
  "total_files": 4,
  "total_links": 15,
  "internal_links": 8,
  "external_links": 7,
  "broken_internal": [
    {
      "file": "pages/manifesto.md",
      "link_text": "Documentation",
      "url": "/docs"
    }
  ],
  "broken_external": [
    {
      "file": "pages/manifesto.md",
      "url": "https://github.com/www-gang-tech/platform",
      "status_code": 404,
      "error": "HTTP 404"
    }
  ],
  "redirects": [],
  "warnings": []
}
```

---

## What Gets Validated

### ✓ Internal Links
- `/pages/about/` → Checks if page exists
- `/posts/my-post/` → Validates against content
- `/assets/image.png` → Checks if file exists in dist
- Handles with/without trailing slashes

### ✓ External Links
- HTTP/HTTPS URLs → Sends HEAD request
- Status codes: 200-299 (OK), 300-399 (Redirect), 400-599 (Error)
- Timeout handling (10 seconds default)
- Caches results to avoid duplicate checks

### ✓ Special Cases
- `#anchor` → Skipped (fragment-only)
- `mailto:email@domain.com` → Skipped
- `tel:+1234567890` → Skipped
- Relative links → Assumed valid
- External images → Warning only

---

## Link Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200-299 | ✓ Success | None |
| 301 | ⚠️ Permanent Redirect | Consider updating link |
| 302 | ⚠️ Temporary Redirect | May want to update |
| 404 | ❌ Not Found | Fix immediately |
| 429 | ⚠️ Rate Limited | Retry later |
| 500-599 | ❌ Server Error | Check site status |
| Timeout | ❌ No Response | Check URL or network |

---

## Integration Examples

### GitHub Actions CI/CD

```yaml
name: Link Validation
on: [push, pull_request]

jobs:
  validate-links:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      # Fast internal check on every commit
      - name: Validate internal links
        run: gang validate --links --internal-only
      
      # Full external check on main branch only
      - name: Validate all links (main only)
        if: github.ref == 'refs/heads/main'
        run: gang validate --links
```

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Only check internal links (fast)
gang validate --links --internal-only || {
  echo "Fix broken internal links before committing"
  exit 1
}
```

### Scheduled Checks (Cron)

```bash
# Check external links weekly (they can break over time)
0 0 * * 0 cd /path/to/site && gang validate --links --format json > link-report.json
```

---

## Performance Considerations

### Internal Link Validation
- **Speed:** Very fast (~100ms for 100 pages)
- **When:** Every build, every commit
- **Cost:** Zero (no network)

### External Link Validation
- **Speed:** Depends on network (~1-5s per URL)
- **When:** Pre-production, scheduled checks
- **Cost:** Network requests
- **Optimization:** Results are cached during scan

### Recommendations

**Development:**
```bash
gang build  # No validation (fastest)
```

**Pre-commit:**
```bash
gang build --validate-links  # Internal only by default
# Or explicitly:
gang validate --links --internal-only
```

**Pre-deploy:**
```bash
gang build --validate-links  # Full validation
```

**Scheduled (weekly):**
```bash
gang validate --links  # Catch external link rot
```

---

## Common Issues & Solutions

### "Broken internal link: /page/"

**Problem:** Link points to non-existent page

**Solution:**
- Fix the link URL
- Create the missing page
- Remove the link

### "HTTP 404" on external link

**Problem:** External page doesn't exist

**Solution:**
- Update to correct URL
- Use Web Archive link
- Remove outdated link

### "Timeout" on external link

**Problem:** Site is slow or blocking bots

**Solution:**
- Check URL manually
- May be temporary (retry later)
- Consider if link is essential

### "External image" warning

**Problem:** Using externally hosted images

**Solution:**
- Download and host locally (better performance)
- Or ignore if it's from a CDN you control

---

## Configuration (Future)

Planned configuration options in `gang.config.yml`:

```yaml
link_validation:
  # External link checking
  external:
    enabled: true
    timeout: 10  # seconds
    user_agent: "GANG-LinkValidator/1.0"
    retry: 2
    
  # Ignore patterns
  ignore:
    - "https://example.com/*"  # Placeholder URLs
    - "#*"  # All anchors
    
  # Warnings vs errors
  strict_mode: true  # Fail on warnings too
```

---

## Best Practices

### 1. **Validate Early, Validate Often**
```bash
# Before every commit
gang validate --links --internal-only

# Before deploy
gang build --validate-links
```

### 2. **Fix Broken Links Immediately**
- Broken internal links → Never should happen
- Broken external links → Update or remove
- Redirects → Update to final URL

### 3. **Use Relative Links for Internal**
Good:
```markdown
[About](/pages/about/)
[Home](/)
```

Bad:
```markdown
[About](https://example.com/pages/about/)
```

### 4. **Monitor External Links**
External sites change. Run weekly:
```bash
gang validate --links > reports/links-$(date +%Y-%m-%d).txt
```

### 5. **CI/CD Integration**
```yaml
# Fast on every commit
- Internal links only

# Thorough before deploy
- All links (internal + external)
```

---

## Advanced Usage

### Validate Specific Files
Currently validates all `.md` files. Future enhancement could allow:
```bash
gang validate --links content/posts/my-post.md
```

### Parallel External Checking
Future optimization for faster external validation:
```python
# Check multiple URLs concurrently
# Current: Sequential (safe, slower)
# Future: Parallel (fast, requires threading)
```

### Link Analysis Dashboard
```bash
gang validate --links --format json | jq '.external_links'
# Count external domains
# Find most-linked sites
# Track link health over time
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All links valid ✓ |
| 1 | Broken links found ❌ |

Use in scripts:
```bash
if gang validate --links --internal-only; then
  echo "Links OK, proceeding..."
  gang build
else
  echo "Fix broken links first!"
  exit 1
fi
```

---

## Troubleshooting

### "Module 'requests' not found"

**Solution:**
```bash
pip install requests
# Or
pip install -r requirements.txt
```

### "Timeout on all external links"

**Problem:** Network issues or firewall

**Solution:**
- Check internet connection
- Use `--internal-only` for now
- Configure proxy if needed

### "False positives on internal links"

**Problem:** Valid links reported as broken

**Solution:**
- Ensure `gang build` was run first
- Check URL format (trailing slash?)
- Report issue with specific URL

---

## Philosophy

Link validator embodies GANG's core values:

✓ **Quality-first** - No broken links in production  
✓ **Fast feedback** - Internal checks in milliseconds  
✓ **CI-friendly** - JSON output, clear exit codes  
✓ **Non-blocking** - Optional gate, not mandatory  
✓ **Transparent** - Shows exactly what's broken and why

**Working links = working trust.**


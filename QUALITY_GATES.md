# Quality Gates Overview

**Comprehensive quality enforcement for content and links.**

## 🎯 Two-Layer Quality System

GANG provides two complementary quality gates:

1. **Content Quality Analyzer** - Readability, SEO, structure, accessibility
2. **Link Validator** - Internal and external link integrity

Both can be used independently or combined for maximum quality assurance.

---

## Quick Reference

### Individual Commands

```bash
# Content quality analysis
gang analyze content/posts/my-post.md  # Single file
gang analyze --all                      # All files
gang analyze --all --min-score 85       # With threshold

# Link validation
gang validate --links                   # Full validation
gang validate --links --internal-only   # Fast mode
```

### Build Integration

```bash
# Content quality gate
gang build --check-quality
gang build --check-quality --min-quality-score 85

# Link validation gate
gang build --validate-links

# Combined (recommended for production)
gang build --check-quality --validate-links --min-quality-score 85
```

---

## Quality Gate Flow

### Development Build (Fast)
```bash
gang build
```
- No quality checks
- Fastest build
- Good for rapid iteration

### Pre-commit (Fast Quality)
```bash
gang build --check-quality --min-quality-score 70
```
- Quality check only
- Skip link validation (faster)
- Catches content issues early

### Pre-deploy (Full Quality)
```bash
gang build --check-quality --validate-links --min-quality-score 85
```
- ✓ Content quality ≥ 85
- ✓ All internal links valid
- ✓ All external links valid
- ✓ No broken images
- Comprehensive quality assurance

### Scheduled Maintenance
```bash
# Weekly link check (external links can rot)
gang validate --links --format json > reports/links-$(date +%Y-%m-%d).json

# Monthly content audit
gang analyze --all --format json > reports/quality-$(date +%Y-%m-%d).json
```

---

## Example Workflow

### Day-to-Day Development

```bash
# 1. Write content
vim content/posts/new-article.md

# 2. Quick analysis
gang analyze content/posts/new-article.md

# 3. Fix issues, iterate

# 4. Build (no gates for speed)
gang build

# 5. Preview
gang serve
```

### Before Committing

```bash
# Run quality check
gang analyze --all --min-score 70

# Check internal links
gang validate --links --internal-only

# If passed, commit
git add .
git commit -m "Add new article"
```

### Before Deploying

```bash
# Full quality gate
gang build --check-quality --validate-links --min-quality-score 85

# If successful, deploy
./deploy.sh
```

---

## Quality Thresholds

### Recommended Minimums

| Environment | Content Score | Link Validation |
|-------------|---------------|-----------------|
| Development | None | None |
| Staging | 70+ | Internal only |
| Production | 85+ | Full (internal + external) |

### Score Interpretation

**Content Quality (0-100):**
- 90-100: Excellent 🌟
- 70-89: Good ✓
- 50-69: Needs improvement ⚠️
- < 50: Poor ✗

**Link Validation:**
- 0 broken: Perfect ✓
- 1-3 broken: Fix before deploy ⚠️
- 4+ broken: Urgent attention needed ❌

---

## CI/CD Integration

### GitHub Actions (Complete Example)

```yaml
name: Quality Gates
on: [push, pull_request]

jobs:
  quality-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      # Fast checks on every commit
      - name: Content quality check
        run: gang analyze --all --min-score 70
      
      - name: Internal link validation
        run: gang validate --links --internal-only
      
      # Full validation on main branch
      - name: Full link validation (main only)
        if: github.ref == 'refs/heads/main'
        run: gang validate --links
      
      # Build with gates
      - name: Build with quality gates
        run: gang build --check-quality --validate-links --min-quality-score 85
      
      # Upload reports
      - name: Generate quality report
        if: always()
        run: |
          gang analyze --all --format json > quality-report.json
          gang validate --links --format json > link-report.json || true
      
      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: quality-reports
          path: |
            quality-report.json
            link-report.json
```

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running quality gates..."

# Find staged markdown files
STAGED_MD=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$')

# If markdown files changed, run checks
if [ -n "$STAGED_MD" ]; then
  # Quick quality check
  echo "Checking content quality..."
  gang analyze --all --min-score 70 || exit 1
  
  # Quick link check
  echo "Validating internal links..."
  gang validate --links --internal-only || exit 1
fi

echo "✓ Quality gates passed"
```

Make executable:
```bash
chmod +x .git/hooks/pre-commit
```

---

## Reports & Metrics

### Daily Dashboard

```bash
#!/bin/bash
# reports/daily-check.sh

DATE=$(date +%Y-%m-%d)
mkdir -p reports/daily

# Content quality
gang analyze --all --format json > reports/daily/quality-$DATE.json

# Link validation
gang validate --links --format json > reports/daily/links-$DATE.json || true

# Generate HTML report (future enhancement)
# python scripts/generate-dashboard.py
```

### Trend Tracking

```bash
# Compare with last week
jq '.total_words' reports/daily/quality-$(date -d '7 days ago' +%Y-%m-%d).json
jq '.total_words' reports/daily/quality-$(date +%Y-%m-%d).json

# Track improvement
echo "Quality trend: +127 words this week"
```

---

## Configuration

### Current Settings

```yaml
# gang.config.yml

# Content Quality
content_quality:
  readability_grade: [6, 10]
  min_words: 300
  max_words: 3000

# Link Validation
link_validation:
  timeout: 10  # seconds
  cache_enabled: true
```

### Future Enhancements

```yaml
# Planned features
quality_gates:
  # Auto-fix mode
  auto_fix:
    enabled: false
    fixes: [alt_text, link_text, heading_hierarchy]
  
  # Progressive thresholds
  thresholds:
    draft: 50
    review: 70
    published: 85
  
  # Link monitoring
  link_check:
    schedule: "weekly"
    ignore_patterns: ["https://example.com/*"]
    retry: 3
```

---

## Best Practices

### 1. Layer Your Checks

```
Fast → Slow
Local → Network
Cheap → Expensive

Development: No gates (fast iteration)
      ↓
Pre-commit: Quality + Internal links (fast, local)
      ↓
Pre-deploy: Full validation (thorough)
      ↓
Scheduled: External link monitoring (catch rot)
```

### 2. Appropriate Thresholds

```bash
# Too strict = Developer frustration
gang build --check-quality --min-quality-score 95  # ❌ Too hard

# Too loose = Quality issues slip through  
gang build --check-quality --min-quality-score 40  # ❌ Too easy

# Just right = Consistent quality
gang build --check-quality --min-quality-score 85  # ✓ Good balance
```

### 3. Fail Fast

```bash
# Check quality BEFORE building
gang analyze --all --min-score 85 && \
gang validate --links --internal-only && \
gang build
```

### 4. Informative Failures

When quality gates fail, they tell you:
- ✓ Which files failed
- ✓ What the scores were
- ✓ How to get more details
- ✓ What to do next

### 5. JSON for Automation

```bash
# Store reports for trend analysis
gang analyze --all --format json > reports/quality.json
gang validate --links --format json > reports/links.json

# Extract metrics
jq '.total_files, .total_words' reports/quality.json
```

---

## Comparison Matrix

| Feature | Content Quality | Link Validator |
|---------|----------------|----------------|
| **Speed** | Very fast | Fast (internal), Slow (external) |
| **Network** | No | Yes (external only) |
| **Scope** | Text analysis | URL validation |
| **When** | Every build | Pre-deploy / Scheduled |
| **Exit on fail** | Optional | Optional |
| **JSON output** | ✓ | ✓ |
| **Batch mode** | ✓ | ✓ |

---

## Current Status of Your Content

Based on latest analysis:

### Content Quality
```
Total files: 4
Total words: 1,007
Avg SEO score: 79/100
Status: 3 Good, 1 Warning
```

**Action needed:**
- pages/about.md: 75/100 (boost to 85+)

### Link Validation
```
Total links: 2
Broken: 2 (1 internal, 1 external)
Status: FAILED
```

**Action needed:**
- Fix `/docs` link in manifesto.md
- Update GitHub repo URL in manifesto.md

---

## What's Next?

With quality gates in place, your workflow becomes:

```
Write → Analyze → Fix → Validate → Build → Deploy
  ↓        ↓       ↓        ↓         ↓        ↓
 .md     Score   Edit     Links    HTML    Live
        85+✓            Valid✓    
```

**Every page that goes live:**
- ✓ Meets readability standards
- ✓ SEO optimized
- ✓ Structurally sound
- ✓ Fully accessible
- ✓ No broken links

**This is the GANG way: Quality is not optional.**


# Content Quality Analyzer

**Analyze and enforce content quality standards across your entire site.**

## Features

### 📊 Comprehensive Analysis

Analyzes content across 4 key dimensions:

1. **Readability** - Flesch-Kincaid grade level, word count, reading time
2. **SEO** - Title/description optimization, images, headings, links  
3. **Structure** - Heading hierarchy, document organization
4. **Accessibility** - Alt text, link quality, semantic markup

### ✅ What's Included

- ✓ **Single file analysis** - Deep dive into one file
- ✓ **Batch analysis** - Analyze all content at once
- ✓ **Summary reports** - Aggregate stats across all files
- ✓ **Quality gates** - Block builds below quality threshold
- ✓ **JSON output** - For CI/CD integration
- ✓ **Min-score enforcement** - Set quality requirements

---

## Usage

### Analyze a Single File

```bash
gang analyze content/posts/my-post.md
```

**Output:**
```
============================================================
📊 Content Quality Report
File: content/posts/my-post.md
============================================================

📖 READABILITY ✓
├─ Word count: 1,247 words
├─ Reading time: ~5.5 min
├─ Grade level: 8.2 (target: 6-10)
├─ Words/sentence: 15.3
└─ Grade 8.2 is in target range (6-10)

🔍 SEO SCORE: 85/100 ✓
├─ Title: 54 chars (recommend 50-60)
├─ Description: 156 chars (recommend 150-160)
├─ Images: 2
├─ Headings: 5
└─ External links: 3

🏗️  STRUCTURE ✓
├─ Headings: 5
├─ Lists: 3
└─ Code blocks: 1

♿ ACCESSIBILITY ✓
├─ Images with alt text: 2/2
├─ Total links: 8
└─ Vague links: 0

============================================================
Overall Status: GOOD ✓
============================================================
```

---

### Analyze All Content (Batch Mode)

```bash
gang analyze --all
```

**Output:**
```
📊 Analyzing 4 files...

✓ pages/about.md
   └─ 71 words, SEO: 75/100, Grade: 8.1
✓ pages/manifesto.md
   └─ 754 words, SEO: 80/100, Grade: 12.1
⚠️ posts/qi2-launch.md
   └─ 97 words, SEO: 80/100, Grade: 12.5
✓ projects/design-system-rebuild.md
   └─ 85 words, SEO: 80/100, Grade: 9.0

============================================================
📊 SUMMARY REPORT
============================================================
Total files: 4
Total words: 1,007
Avg grade level: 10.4
Avg SEO score: 79/100

Status breakdown:
  ✓ Good: 3
  ⚠️  Warning: 1
  ✗ Poor: 0
```

---

### Enforce Minimum Quality Score

```bash
# Fail if any file scores below 80
gang analyze --all --min-score 80
```

**Output (if failures):**
```
⚠️  1 file(s) below minimum score (80):
  - pages/about.md: 75/100

Exit code: 1
```

---

### Quality Gate in Build Process

Prevent publishing low-quality content:

```bash
# Build with quality checks (default threshold: 70)
gang build --check-quality

# Custom threshold
gang build --check-quality --min-quality-score 80
```

**Output (if quality check fails):**
```
🔨 Building site...
🔍 Running content quality checks...

❌ Quality gate failed! 1 file(s) below minimum score (80):
  - pages/about.md: 75/100

Run 'gang analyze --all' for detailed report
Tip: Use --min-quality-score to adjust threshold or fix content issues

Exit code: 1 (build stops)
```

**Output (if quality check passes):**
```
🔨 Building site...
🔍 Running content quality checks...
✓ All 4 files pass quality threshold (80+)

📦 Copying public assets...
...
✅ Build complete!
```

---

### JSON Output (CI/CD Integration)

```bash
# Get machine-readable output
gang analyze --all --format json
```

**Output:**
```json
{
  "total_files": 4,
  "total_words": 1007,
  "files": [
    {
      "file": "content/pages/about.md",
      "frontmatter": {
        "title": "About GANG",
        "date": "2025-01-15"
      },
      "readability": {
        "word_count": 71,
        "grade_level": 8.1,
        "reading_time_minutes": 0.3,
        "status": "good"
      },
      "seo": {
        "score": 75,
        "status": "good",
        "title_length": 10,
        "description_length": 84,
        "issues": [...]
      },
      ...
    }
  ]
}
```

---

## Quality Metrics

### Readability Scoring

**Grade Level (Flesch-Kincaid):**
- Target: 6-10 (accessible to most readers)
- < 6: Too simple
- 6-10: Good ✓
- > 10: Too complex

**Calculation:**
```
0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
```

### SEO Scoring (0-100)

| Factor | Points | Optimal |
|--------|--------|---------|
| Title present | 20 | 50-60 chars |
| Title length | 5 | |
| Description present | 20 | 150-160 chars |
| Description length | 5 | |
| Has images | 10 | 1+ images |
| Image alt text | 10 | All images |
| Heading count | 10 | 2+ headings |
| External links | 5 | 1+ links |

### Structure Requirements

- ✓ Exactly one H1 heading
- ✓ No heading level skips (h1 → h2 → h3, not h1 → h3)
- ✓ Proper document hierarchy
- ✓ Semantic organization

### Accessibility Checks

- ✓ All images have alt text
- ✓ No vague link text ("click here", "read more")
- ✓ Semantic markup usage

---

## Integration Examples

### GitHub Actions CI/CD

```yaml
name: Quality Check
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Check content quality
        run: gang analyze --all --min-score 70 --format json > quality-report.json
      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: quality-report
          path: quality-report.json
```

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Find modified markdown files
FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$')

if [ -n "$FILES" ]; then
  echo "Analyzing modified content..."
  for FILE in $FILES; do
    gang analyze "$FILE" --min-score 70 || exit 1
  done
fi
```

### npm Scripts

```json
{
  "scripts": {
    "analyze": "gang analyze --all",
    "analyze:strict": "gang analyze --all --min-score 80",
    "build": "gang build --check-quality",
    "build:strict": "gang build --check-quality --min-quality-score 80"
  }
}
```

---

## Configuration

Quality targets can be customized in `gang.config.yml`:

```yaml
# Future: Custom quality thresholds
content_quality:
  readability:
    target_grade_min: 6
    target_grade_max: 10
  seo:
    min_title_length: 50
    max_title_length: 60
    min_description_length: 150
    max_description_length: 160
  structure:
    min_headings: 2
    require_h1: true
```

---

## Best Practices

### 1. **Run Before Every Build**
```bash
gang build --check-quality
```

### 2. **Review Weekly**
```bash
gang analyze --all --format summary > reports/weekly-$(date +%Y-%m-%d).txt
```

### 3. **Set Reasonable Thresholds**
- Development: `--min-quality-score 60`
- Staging: `--min-quality-score 70`
- Production: `--min-quality-score 80`

### 4. **Focus on Trends**
Track improvements over time:
```bash
# Before
Total files: 10
Avg SEO score: 72/100

# After improvements
Total files: 10
Avg SEO score: 84/100 (+12 points!)
```

### 5. **Fix Common Issues**

**Too short?** Add more detail, examples, context

**Grade too high?** Shorter sentences, simpler words

**Missing alt text?** Run `gang optimize` (AI-powered)

**Low SEO?** Add images, external links, better descriptions

---

## Troubleshooting

### "No content to analyze"

**Problem:** Empty or whitespace-only markdown file

**Solution:** Add content or remove the file

### "Heading skip detected"

**Problem:** Jumped from h1 to h3 (skipped h2)

**Solution:** Add proper heading hierarchy

### "Image missing alt text"

**Problem:** `![](image.jpg)` instead of `![Description](image.jpg)`

**Solution:** Add descriptive alt text or run `gang optimize`

---

## What's Next?

Future enhancements planned:
- AI-powered content suggestions
- Readability improvements recommendations
- Automated content fixes
- Historical tracking & trends
- Custom quality rules
- Per-category thresholds

---

## Philosophy

Content quality analyzer embodies GANG's core philosophy:

✓ **Quality-first** - Enforce standards, not suggestions  
✓ **Accessible** - WCAG AA compliance built-in  
✓ **Fast** - Pure Python, no network calls  
✓ **Transparent** - Clear metrics, actionable feedback  
✓ **Non-blocking** - Quality gates are optional

**Documents, not apps. Quality, not quantity.**


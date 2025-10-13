# AI-Powered Link Fix Suggestions

**Let AI suggest intelligent fixes for broken links automatically.**

## Overview

When you run `gang validate --links --suggest-fixes`, the AI analyzes:
- **Broken URLs** and their context
- **Link text** to understand intent
- **Available pages** on your site
- **Error types** (404, timeout, etc.)

Then suggests the most likely fix with confidence levels.

---

## Setup

```bash
# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Or add to ~/.zshrc or ~/.bashrc
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc
```

---

## Usage

### Basic AI Suggestions

```bash
gang validate --links --suggest-fixes
```

### Internal Links Only (Faster)

```bash
gang validate --links --internal-only --suggest-fixes
```

### JSON Output (For Automation)

```bash
gang validate --links --suggest-fixes --format json
```

---

## Example Output

### Scenario: Broken Internal Link

**Input:**
```markdown
[Documentation](/docs)
```

**Link Validator finds:**
```
❌ BROKEN INTERNAL LINKS: 1
  pages/manifesto.md
  └─ [Documentation](/docs)
```

**AI Suggests:**
```
🤖 AI-Powered Link Fix Suggestions
============================================================

📝 INTERNAL LINK FIXES (1)

File: pages/manifesto.md
  Broken: /docs
  ✨ Suggested: /pages/about/ (high confidence)
  💡 The link text "Documentation" and broken URL "/docs" most likely
     refers to the About page which contains documentation information.
     Alternatively, consider creating a dedicated /docs page.
```

---

### Scenario: Broken External Link (404)

**Input:**
```markdown
[GitHub Repo](https://github.com/old-org/old-repo)
```

**Link Validator finds:**
```
❌ BROKEN EXTERNAL LINKS: 1
  pages/manifesto.md
  └─ https://github.com/old-org/old-repo → HTTP 404
```

**AI Suggests:**
```
🌐 EXTERNAL LINK FIXES (1)

File: pages/manifesto.md
  Broken: https://github.com/old-org/old-repo
  Error: HTTP 404
  ✨ Action: MANUAL_CHECK
  Suggested URL: null
  💡 The repository appears to have been moved or deleted. Check if the
     organization/repo was renamed. If permanently gone, consider using
     Web Archive: https://web.archive.org/web/*/github.com/old-org/old-repo
```

---

### Scenario: Redirected Link (301)

**Link Validator finds:**
```
⚠️  REDIRECTS: 1
  posts/my-post.md
  └─ https://old-domain.com/article → 301
     Redirects to: https://new-domain.com/article
```

**AI Suggests:**
```
↪️  REDIRECT FIXES (1)

File: posts/my-post.md
  Current: https://old-domain.com/article
  ✨ Update to: https://new-domain.com/article
  💡 Update link to final destination to avoid redirect (301)
```

---

## AI Suggestion Types

### For Internal Links

The AI considers:
1. **URL similarity** - `/docs` → `/pages/documentation/`
2. **Link text meaning** - "Documentation" suggests docs-related pages
3. **Available pages** - What actually exists on your site
4. **Context** - Surrounding content and topic

**Confidence levels:**
- `high` - Very likely correct (>90%)
- `medium` - Probable match (70-90%)
- `low` - Best guess (<70%) or no match found

### For External Links

The AI suggests:
1. **Replace** - Alternative URL found
2. **Archive** - Use Web Archive version
3. **Remove** - Link is outdated/irrelevant
4. **Manual Check** - Needs human review

**Examples:**

| Error | AI Suggestion |
|-------|---------------|
| HTTP 404 | Check Web Archive or find replacement |
| Timeout | Retry manually, may be temporary |
| HTTP 403 | May be blocking bots, check manually |
| HTTP 500 | Server error, retry later |

---

## Complete Workflow

### 1. Find Broken Links

```bash
gang validate --links
```

### 2. Get AI Suggestions

```bash
gang validate --links --suggest-fixes
```

### 3. Review & Apply

**AI Output:**
```
File: pages/manifesto.md
  Broken: /docs
  ✨ Suggested: /pages/about/ (high confidence)
  💡 Based on link text and available pages
```

**You decide:**
- ✓ Looks good → Update manually
- ✗ Not quite right → Try different page
- ? Unsure → Review both options

### 4. Fix in Editor

```markdown
<!-- Before -->
[Documentation](/docs)

<!-- After (AI suggestion applied) -->
[Documentation](/pages/about/)
```

### 5. Validate Again

```bash
gang validate --links
# ✓ All links valid!
```

---

## JSON Output Example

```json
{
  "validation_results": {
    "total_files": 4,
    "broken_internal": [
      {
        "file": "pages/manifesto.md",
        "link_text": "Documentation",
        "url": "/docs"
      }
    ]
  },
  "ai_suggestions": {
    "internal": [
      {
        "file": "pages/manifesto.md",
        "broken_url": "/docs",
        "link_text": "Documentation",
        "suggested_url": "/pages/about/",
        "confidence": "high",
        "reasoning": "Link text matches About page content"
      }
    ],
    "external": [],
    "redirects": []
  }
}
```

---

## Performance & Cost

### Speed
- **Validation only:** 100-500ms (no AI)
- **With AI suggestions:** +2-5s per broken link
- **Caching:** Results cached during run

### API Costs
- **Per suggestion:** ~$0.001-0.002 (Claude Sonnet)
- **Batch suggestions:** Same cost (processed together)
- **Recommendation:** Use only when needed

### When to Use AI Suggestions

✓ **Use AI:**
- Pre-deploy checks
- Periodic maintenance
- After content migrations
- When uncertain about fixes

✗ **Skip AI:**
- Rapid development
- CI on every commit (too slow)
- When you know the fix
- No API key available

---

## Advanced Usage

### Automated Fix Application (Future)

```bash
# Coming soon: Auto-apply high-confidence suggestions
gang fix --links --auto-apply --min-confidence high

# Preview changes first
gang fix --links --dry-run
```

### CI/CD Integration

```yaml
# GitHub Actions
- name: Validate links with AI suggestions
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: |
    gang validate --links --suggest-fixes --format json > link-suggestions.json
    
- name: Comment on PR with suggestions
  uses: actions/github-script@v6
  with:
    script: |
      const fs = require('fs');
      const suggestions = JSON.parse(fs.readFileSync('link-suggestions.json'));
      // Post suggestions as PR comment
```

### Batch Processing

```bash
# Generate suggestions for all broken links
gang validate --links --suggest-fixes --format json | \
  jq '.ai_suggestions.internal[] | 
      "File: \(.file)\nBroken: \(.broken_url)\nSuggested: \(.suggested_url)"'
```

---

## How It Works

### Internal Link Suggestions

1. **Extract context:** Broken URL + link text
2. **Get valid pages:** All existing pages on your site
3. **AI analysis:** Match broken URL to most similar valid page
4. **Confidence scoring:** Based on URL/text similarity
5. **Return suggestion:** With reasoning

**AI Prompt (simplified):**
```
Broken link: /docs
Link text: "Documentation"
Available pages: [/pages/about/, /posts/, /projects/, ...]

Which page is the most likely match?
```

### External Link Suggestions

1. **Analyze error:** 404, timeout, server error, etc.
2. **Parse URL:** Domain, path, likely content type
3. **AI reasoning:** Determine best action
4. **Suggest solution:** Replace, archive, remove, or manual check

**AI Prompt (simplified):**
```
Broken URL: https://github.com/org/repo
Error: HTTP 404

What's the best way to fix this?
- Search for new URL?
- Use Web Archive?
- Remove as outdated?
```

---

## Fallback Behavior

### No API Key
```bash
gang validate --links --suggest-fixes

# Shows:
⚠️  ANTHROPIC_API_KEY not set
Set ANTHROPIC_API_KEY to enable AI suggestions

# Falls back to regular validation
```

### AI Error
```bash
# If AI fails (network, API issue, etc.)
# Shows reasoning with error message
💡 AI suggestion failed: [error details]
```

### No Broken Links
```bash
# If all links valid, AI suggestions are skipped
✓ All links valid
# No AI calls made (saves cost)
```

---

## Best Practices

### 1. Review AI Suggestions

**Always verify** AI suggestions before applying:
- AI is smart but not perfect
- Context matters
- You know your content best

### 2. Use Confidence Levels

```
High confidence → Likely safe to apply
Medium confidence → Review before applying
Low confidence → Definitely review or ignore
```

### 3. Combine with Link Text

```markdown
<!-- AI can use link text for context -->
[Our Documentation](/docs)  → Suggests docs-related page
[Contact Us](/contact)      → Suggests contact page
[Old Article](/archived)    → Suggests similar article
```

### 4. Learn from Patterns

If AI consistently suggests wrong fixes:
- URL structure might be confusing
- Link text might be vague
- Consider creating the missing page

---

## Limitations

### What AI Can't Do

❌ **Create pages** - Only suggests from existing pages
❌ **Fix typos in external URLs** - Can't guess correct domain
❌ **Know your intent** - Makes best guess from context
❌ **Access private repos** - Can only check public URLs

### What AI Does Well

✓ **Pattern matching** - Great at finding similar URLs
✓ **Context understanding** - Uses link text intelligently  
✓ **Error interpretation** - Knows what different HTTP codes mean
✓ **Web knowledge** - Understands Web Archive, redirects, etc.

---

## Future Enhancements

### Auto-Apply Mode
```bash
# Apply high-confidence suggestions automatically
gang fix --links --auto-apply --min-confidence high

# Dry run first
gang fix --links --dry-run
```

### Interactive Mode
```bash
gang validate --links --suggest-fixes --interactive

# Shows:
Fix broken link in pages/manifesto.md?
  Broken: /docs
  Suggested: /pages/about/ (high confidence)
  
[a] Apply  [s] Skip  [e] Edit  [q] Quit: 
```

### Learning Mode
```bash
# Learn from your corrections
gang fix --links --learn

# AI adapts to your preferences over time
```

---

## Comparison

| Mode | Speed | Cost | Accuracy |
|------|-------|------|----------|
| Manual | Slow | Free | 100% (you decide) |
| AI Suggestions | Fast | ~$0.002/link | ~80-90% |
| Future Auto-fix | Instant | ~$0.002/link | ~95% (high-conf only) |

---

## Example Session

```bash
$ gang validate --links --suggest-fixes

🔗 Validating links...
Found 3 broken links

🤖 Generating AI fix suggestions...

📝 INTERNAL LINK FIXES (1)
File: pages/manifesto.md
  Broken: /docs
  ✨ Suggested: /pages/about/ (high confidence)
  💡 The "Documentation" link likely refers to the About page

🌐 EXTERNAL LINK FIXES (1)  
File: pages/manifesto.md
  Broken: https://github.com/www-gang-tech/platform
  ✨ Action: MANUAL_CHECK
  💡 Check if repo was renamed or moved to different org

↪️  REDIRECT FIXES (1)
File: posts/old-post.md
  Current: https://old-site.com/page
  ✨ Update to: https://new-site.com/page
  💡 Avoid 301 redirect for better performance

💡 TIP: Review suggestions and apply manually
```

---

## Philosophy

AI suggestions embody GANG's core values:

✓ **AI-first** - Leverage AI for tedious tasks  
✓ **Human-in-loop** - AI suggests, you decide  
✓ **Quality-focused** - Helps maintain link integrity  
✓ **Transparent** - Shows reasoning and confidence  
✓ **Optional** - Works without AI key

**AI assists, humans decide. Quality is non-negotiable.**


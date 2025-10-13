# AI Link Suggestions - Live Demo

## Example Session (With API Key Set)

```bash
$ export ANTHROPIC_API_KEY=sk-ant-...
$ gang validate --links --suggest-fixes
```

### Output:

```
🔗 Validating links...
============================================================
🔗 Link Validation Report
============================================================

📊 SUMMARY
├─ Files scanned: 4
├─ Total links: 2
├─ Internal links: 1
└─ External links: 1

❌ BROKEN INTERNAL LINKS: 1
  pages/manifesto.md
  └─ [Documentation](/docs)

❌ BROKEN EXTERNAL LINKS: 1
  pages/manifesto.md
  └─ https://github.com/www-gang-tech/platform → HTTP 404

============================================================
Overall Status: FAILED ❌
Total broken links: 2
============================================================

🤖 Generating AI fix suggestions...

============================================================
🤖 AI-Powered Link Fix Suggestions
============================================================

📝 INTERNAL LINK FIXES (1)

File: pages/manifesto.md
  Broken: /docs
  ✨ Suggested: /pages/about/ (high confidence)
  💡 Based on the link text "Documentation" and analyzing your site
     structure, the About page (/pages/about/) is the most likely match.
     It contains information about GANG and appears to serve as the main
     documentation entry point. Alternatively, you could create a dedicated
     /docs page if you plan to have extensive documentation.

🌐 EXTERNAL LINK FIXES (1)

File: pages/manifesto.md
  Broken: https://github.com/www-gang-tech/platform
  Error: HTTP 404
  ✨ Action: MANUAL_CHECK
  Suggested URL: null
  💡 The GitHub repository returns a 404 error, which typically means:
     1. The repository was renamed or moved to a different organization
     2. The repository was made private or deleted
     3. There's a typo in the organization or repository name
     
     Recommended actions:
     - Search GitHub for "gang platform" to find the current location
     - Check if the organization name changed (www-gang-tech → ?)
     - If the repo is gone, consider using Web Archive:
       https://web.archive.org/web/*/github.com/www-gang-tech/platform
     - Or link to your project homepage instead

============================================================
💡 TIP: Review suggestions and apply manually
    Future: 'gang fix --links' to auto-apply
============================================================

❌ Validation failed with 2 broken links
```

---

## How AI Made These Suggestions

### Internal Link: `/docs` → `/pages/about/`

**AI analyzed:**
1. **Broken URL:** `/docs`
2. **Link text:** "Documentation"
3. **Available pages:** 
   - `/` (home)
   - `/posts/` (blog)
   - `/projects/` (portfolio)
   - `/pages/about/` (about page)
   - `/pages/manifesto/` (manifesto)

**AI reasoning:**
- Link text "Documentation" suggests informational content
- `/pages/about/` is the only page with documentation-like content
- High confidence because clear semantic match
- Bonus: Suggests creating dedicated `/docs` if needed

---

### External Link: GitHub 404

**AI analyzed:**
1. **Broken URL:** `https://github.com/www-gang-tech/platform`
2. **Error:** HTTP 404
3. **Domain:** GitHub (well-known platform)
4. **Pattern:** Repo not found

**AI reasoning:**
- 404 on GitHub = repo moved, deleted, or renamed
- Can't guess new location without more context
- Suggests manual actions:
  - Search GitHub
  - Check Web Archive
  - Update to alternative

**Action:** `MANUAL_CHECK` (needs human decision)

---

## Confidence Levels Explained

### High Confidence (>90%)

**Example:**
```
Broken: /dokumentation
Available: /documentation/, /docs/, /pages/about/

✨ Suggested: /documentation/ (high confidence)
💡 Clear typo in URL - missing 'c' in documentation
```

**When AI is highly confident:**
- URL typo is obvious
- Only one semantic match exists
- Link text strongly suggests specific page

### Medium Confidence (70-90%)

**Example:**
```
Broken: /guide
Available: /pages/about/, /posts/getting-started/, /pages/tutorial/

✨ Suggested: /pages/tutorial/ (medium confidence)
💡 "guide" could refer to multiple pages. Tutorial is most likely,
   but also review getting-started post.
```

**When AI is moderately confident:**
- Multiple plausible matches
- Link text is ambiguous
- Context doesn't strongly favor one option

### Low Confidence (<70%)

**Example:**
```
Broken: /old-page
Available: [many unrelated pages]

✨ Suggested: null (low confidence)
💡 No matching page found. Consider:
   1. Creating the page at /old-page
   2. Removing this broken link
   3. Updating link text to clarify intent
```

**When AI has low confidence:**
- No good matches found
- Broken URL is very different from available pages
- Suggests creating page or removing link

---

## Real-World Scenarios

### Scenario 1: Content Migration

**Problem:** Migrated from WordPress to GANG, old URLs broken

```bash
gang validate --links --suggest-fixes
```

**AI helps:**
```
Broken: /2024/03/my-old-post/
✨ Suggested: /posts/my-old-post/ (high confidence)
💡 WordPress URL structure → GANG URL structure
```

### Scenario 2: Site Restructure

**Problem:** Reorganized content, links outdated

```bash
gang validate --links --suggest-fixes
```

**AI helps:**
```
Broken: /blog/article-name/
Available: /posts/article-name/, /projects/article-name/
✨ Suggested: /posts/article-name/ (high confidence)
💡 "blog" folder was renamed to "posts"
```

### Scenario 3: External Link Rot

**Problem:** Third-party sites went offline

```bash
gang validate --links --suggest-fixes
```

**AI helps:**
```
Broken: https://dead-site.com/article
✨ Action: ARCHIVE
Suggested: https://web.archive.org/web/*/dead-site.com/article
💡 Site appears permanently offline. Web Archive has 47 snapshots.
```

---

## Without API Key

The feature **gracefully degrades** if no API key is set:

```bash
$ gang validate --links --suggest-fixes

🔗 Validating links...
[... validation results ...]

🤖 Generating AI fix suggestions...

⚠️  ANTHROPIC_API_KEY not set
Set ANTHROPIC_API_KEY to enable AI suggestions

# Still shows broken links, just no AI suggestions
# You can fix manually
```

---

## Cost Estimation

**Typical usage:**
- 10 broken links × $0.0015/suggestion = **$0.015 per run**
- 100 broken links (major migration) = **$0.15**
- Monthly site check (weekly) = **~$0.06/month**

**Very affordable** compared to manual link checking time!

---

## Future: Auto-Apply Mode

```bash
# Coming soon
gang fix --links --auto-apply --min-confidence high

Would apply 3 fixes:
  ✓ /docs → /pages/about/ (high confidence)
  ⚠️  Skipping: /old → /new (medium confidence)
  ⚠️  Skipping: external fix (manual review needed)

Apply? [y/N]: y
✓ Applied 1 fix
⚠️  Review 2 suggestions manually
```

---

## Why This Matters

### Before (Manual)
```
1. Find broken link      → 5 seconds
2. Understand context    → 30 seconds
3. Search for right page → 60 seconds
4. Update markdown       → 10 seconds
Total: ~2 minutes per link

10 broken links = 20 minutes
```

### After (AI-Assisted)
```
1. Find broken link      → 5 seconds
2. AI suggests fix       → 2 seconds
3. Review suggestion     → 5 seconds  
4. Update markdown       → 10 seconds
Total: ~20 seconds per link

10 broken links = 3-4 minutes

Time saved: 75-80%!
```

---

## Testing the Feature

### Test with Your Current Broken Links

```bash
# You have 2 broken links in manifesto.md
$ gang validate --links --suggest-fixes

# AI will suggest:
# - Internal: /docs → most likely /pages/about/
# - External: GitHub 404 → manual check needed
```

### See It In Action

```bash
# 1. Check current status
gang validate --links

# 2. Get AI suggestions (if API key set)
gang validate --links --suggest-fixes

# 3. Review and apply manually

# 4. Validate again
gang validate --links
# ✓ All links valid!
```

---

## Philosophy

This feature is peak "AI-first" platform:

✓ **AI assists** - Suggests fixes intelligently  
✓ **Human decides** - You review and apply  
✓ **Context-aware** - Uses link text and site structure  
✓ **Transparent** - Shows reasoning and confidence  
✓ **Optional** - Works perfectly without AI too  

**AI makes suggestions. Humans make decisions. Quality is guaranteed.**


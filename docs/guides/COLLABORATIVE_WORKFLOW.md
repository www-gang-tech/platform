# Collaborative Workflow - Safe AI-Assisted Link Fixing

**Designed for multi-editor teams where safety and review are critical.**

## 🎯 Design Philosophy

### The Problem with Auto-Fix

**Scenario:** Editor B is working on a document, tries to publish, AI auto-fixes a broken link to the wrong page.

**Result:** Wrong link goes live ❌

### The Solution: Suggest, Don't Change

**Default behavior:** AI suggests, humans decide.

---

## 👥 Multi-Editor Workflow

### Editor Workflow

```
┌─────────────────────────────────────┐
│ Editor writes content               │
│ Content includes: [Docs](/docs)     │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ Editor clicks "Publish"             │
│ Runs: gang build --validate-links   │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ ❌ BUILD BLOCKED                    │
│ "Found 1 broken link: /docs"        │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ Editor runs: gang fix --links       │
│ Gets AI suggestion (NO CHANGES!)    │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ 🤖 AI SUGGESTS:                     │
│ "/docs → /pages/about/"             │
│ Confidence: High                    │
│ Reasoning: Best match               │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ EDITOR DECIDES:                     │
│ ✓ Looks good? Apply it              │
│ ✗ Wrong? Fix manually               │
│ ? Unsure? Ask teammate              │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ Option A: gang fix --links --apply  │
│ Option B: gang fix --links --commit │
│ Option C: Edit manually             │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ ✅ Publishes successfully           │
└─────────────────────────────────────┘
```

---

## 🔒 Safety Modes

### Mode 1: Suggestion Only (Default - Safest)

```bash
gang fix --links
```

**Behavior:**
- ✅ Validates links
- ✅ Shows AI suggestions
- ❌ **Does NOT modify files**
- ❌ Exit code 1 (blocks publish)

**Best for:**
- Quick checks
- Uncertain fixes
- Multi-editor teams
- Review before applying

---

### Mode 2: Apply After Review

```bash
# Step 1: See suggestions
gang fix --links

# Step 2: Review and decide
# ... editor reviews the suggestions ...

# Step 3: Apply if approved
gang fix --links --apply
```

**Behavior:**
- ✅ Applies fixes to markdown
- ✅ Editor can review with `git diff`
- ✅ Still requires manual rebuild
- ✅ Editor stays in control

**Best for:**
- Solo editor confident in AI
- High-confidence suggestions
- Quick fixes

---

### Mode 3: Commit for Team Review

```bash
gang fix --links --commit
```

**Behavior:**
- ✅ Applies fixes
- ✅ Creates git commit
- ✅ Descriptive commit message
- ✅ Ready for PR/review

**Commit includes:**
```
Fix 2 broken link(s) [AI-suggested]

- pages/article.md: /pags/about → /pages/about/
- pages/article.md: /project → /projects/
```

**Review process:**
```bash
# Editor A creates fix commit
gang fix --links --commit

# Editor A pushes for review
git push origin feature/ai-link-fixes

# Editor B reviews PR
git show  # See changes
# Approve or request changes

# If approved, merge
git merge feature/ai-link-fixes
```

**Best for:**
- Team environments
- Important content
- When uncertain
- Audit trail needed

---

## Real-World Scenarios

### Scenario 1: Junior Editor Making Changes

**Problem:** New editor creates broken link, doesn't know site structure

```bash
# Editor clicks "Publish"
gang build --validate-links

# Output:
❌ Build blocked: broken link /dokumentation

# Editor gets help from AI
gang fix --links

# AI suggests:
✨ Suggested: /pages/documentation/ (high confidence)
💡 Typo: 'dokumentation' → 'documentation'

# Editor sees it's a typo, applies
gang fix --links --apply
gang build
# ✅ Published!
```

**Result:** Editor learns correct URLs, AI catches mistakes safely.

---

### Scenario 2: Unsure About Correct Link

**Problem:** Editor not sure which page is correct

```bash
# Get AI suggestion
gang fix --links

# AI suggests:
✨ Suggested: /pages/tutorial/ (medium confidence)
💡 Could also be /pages/guide/ or /pages/docs/

# Editor uncertain, asks teammate
# Creates commit for review
gang fix --links --commit

# Senior editor reviews
git show
# Approves or suggests different link

# If wrong, easy to undo
git reset 'HEAD^'  # Undo commit
# Edit manually instead
```

**Result:** Team review ensures correct link, AI speeds up process.

---

### Scenario 3: Content Migration

**Problem:** Migrated 50 articles from WordPress, many broken links

```bash
# Validate all links
gang validate --links

# Found 47 broken links!

# Get AI suggestions for all
gang fix --links

# Review suggestions
# High confidence: 35 (likely URL pattern changes)
# Medium confidence: 10 (need manual review)
# Low confidence: 2 (no good match)

# Apply high-confidence only
gang fix --links --apply --min-confidence high
# ✅ 35 fixed automatically

# Review medium-confidence manually
# Fix the 12 remaining by hand
```

**Result:** AI handles obvious patterns, human handles edge cases.

---

## 🛡️ Safety Guarantees

### 1. **No Surprises**

Default: `gang fix --links`
- Shows suggestions
- Changes nothing
- Clear next steps

### 2. **Explicit Intent**

Must use `--apply` or `--commit` to modify files.

### 3. **Confidence Filtering**

```bash
# Conservative (recommended)
gang fix --links --apply  # Default: high confidence only

# Moderate
gang fix --links --apply --min-confidence medium

# Aggressive (review carefully!)
gang fix --links --apply --min-confidence low
```

### 4. **Git Integration**

```bash
# Create reviewable commit
gang fix --links --commit

# Review
git show

# Undo if wrong
git reset 'HEAD^'

# Or amend
git commit --amend
```

### 5. **Clear Communication**

Every suggestion includes:
- ✅ Which file
- ✅ What's broken
- ✅ What AI suggests
- ✅ Confidence level
- ✅ Reasoning why

---

## Integration with Studio CMS

### Future: Studio UI Integration

When editor clicks "Publish" in Studio:

```
┌──────────────────────────────────────────┐
│  ⚠️  Cannot Publish                      │
│                                          │
│  Found 1 broken link in your content:   │
│                                          │
│  [Documentation](/docs)                  │
│                                          │
│  🤖 AI Suggestion:                       │
│  Change to: /pages/about/               │
│  Confidence: High                        │
│  Reason: Best semantic match             │
│                                          │
│  [ Review Suggestion ]  [ Fix Manually ] │
└──────────────────────────────────────────┘
```

**Editor clicks "Review Suggestion":**
```
┌──────────────────────────────────────────┐
│  AI-Suggested Fix                        │
│                                          │
│  File: pages/article.md                  │
│  Line 45                                 │
│                                          │
│  Before: [Documentation](/docs)          │
│  After:  [Documentation](/pages/about/)  │
│                                          │
│  Confidence: High (95%)                  │
│  Reason: Link text "Documentation"       │
│  matches About page content              │
│                                          │
│  [ Apply Fix ]  [ Ignore ]  [ Edit ]     │
└──────────────────────────────────────────┘
```

---

## Commands Summary

### Default: Show Suggestions (No Changes)

```bash
gang fix --links
```
- Safe for anyone to run
- No file modifications
- Blocks publish workflow
- Shows clear next steps

### Apply Fixes (After Review)

```bash
gang fix --links --apply
```
- Requires explicit flag
- Applies AI suggestions
- Can review with `git diff`
- Can undo before commit

### Create Commit (Team Review)

```bash
gang fix --links --commit
```
- Applies fixes
- Creates git commit
- Descriptive message
- Ready for PR
- Easy to review/undo

### Complete Workflow

```bash
gang fix --links --commit --rebuild
```
- Applies fixes
- Creates commit
- Rebuilds site
- All in one (for confident fixes)

---

## Best Practices

### For Solo Editors

```bash
# 1. See suggestions
gang fix --links

# 2. If looks good, apply
gang fix --links --apply

# 3. Review changes
git diff

# 4. Commit manually
git commit -am "Fix broken links"

# 5. Rebuild
gang build
```

### For Team Editors

```bash
# 1. See suggestions
gang fix --links

# 2. Create commit for review
gang fix --links --commit

# 3. Push for PR
git push origin fix/broken-links

# 4. Team reviews PR
# Approves or requests changes

# 5. Merge and rebuild
git merge && gang build
```

### For CI/CD

```bash
# Block builds, show suggestions in CI logs
gang build --validate-links

# Don't auto-fix in CI (too risky)
# Let humans review and apply
```

---

## Why This is Better

### Before (Auto-Fix)
```
❌ AI might fix to wrong page
❌ No human review
❌ Could publish incorrect links
❌ Scary for teams
```

### After (Suggest-First)
```
✅ AI suggests, humans decide
✅ Review before applying
✅ Safe for collaborative editing
✅ Quality guaranteed
```

---

## Your Workflow is Now

1. **Editor writes content**
2. **Tries to publish** → `gang build --validate-links`
3. **Build blocks if broken links** ❌
4. **Editor gets AI suggestions** → `gang fix --links`
5. **Editor reviews suggestions** 👀
6. **Editor decides:**
   - Apply: `gang fix --links --apply`
   - Commit for review: `gang fix --links --commit`
   - Fix manually: `vim content/...`
7. **Publish successfully** ✅

**Safe. Collaborative. AI-assisted. Human-decided.**


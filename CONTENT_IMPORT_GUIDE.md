# Content Import Guide

**Two powerful ways to add content with automatic image handling and AI assistance.**

## Use Case #1: CMS Editor Adding New Documents

**Scenario:** Editor is in the Studio CMS, wants to create new content with images.

### Workflow

```
┌─────────────────────────────────────┐
│  Studio CMS                         │
│  [New Post] [New Page] [New Project]│
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Editor writes in markdown          │
│  Adds images via markdown syntax    │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Clicks "Upload Image"              │
│  → Uploads to R2 automatically      │
│  → AI generates alt text            │
│  → Inserts markdown snippet         │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Clicks "Publish"                   │
│  → Checks slug uniqueness ✓         │
│  → Validates quality ✓              │
│  → Validates links ✓                │
│  → Builds site ✓                    │
└─────────────────────────────────────┘
```

### Commands

```bash
# Upload image from CMS
gang media upload hero.jpg

# Output:
✅ Uploaded successfully (145KB)
📍 Public URL: https://media.yourdomain.com/images/hero.jpg

💡 Use in markdown:
   ![Alt text](https://media.yourdomain.com/images/hero.jpg)

# CMS automatically:
# 1. Uploads to R2
# 2. Compresses image
# 3. Generates alt text with AI
# 4. Inserts into editor
```

---

## Use Case #2: Paste from Google Docs / Notes

**Scenario:** Editor has existing content in Google Docs, Notes, or TextEdit with images embedded.

### Workflow

```
┌─────────────────────────────────────┐
│  Google Docs / Notes / TextEdit     │
│  (Content with embedded images)     │
└─────────────────────────────────────┘
              ↓
         Copy All (⌘+A, ⌘+C)
              ↓
┌─────────────────────────────────────┐
│  Terminal or CMS                    │
│  gang import-content                │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  🤖 AI Analysis                     │
│  ├─ Extracts title                  │
│  ├─ Suggests category (post/page)   │
│  ├─ Generates slug                  │
│  ├─ Checks uniqueness ✓             │
│  ├─ Extracts images                 │
│  ├─ Compresses images               │
│  ├─ Uploads to R2                   │
│  └─ Generates alt text              │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  ✅ Markdown file created           │
│  ✅ Images on CDN                   │
│  ✅ Alt text added                  │
│  ✅ Slug validated                  │
└─────────────────────────────────────┘
```

### Commands

#### Import from File

```bash
gang import-content article.txt

# Or specify category
gang import-content article.txt --category posts

# With git commit
gang import-content article.txt --commit
```

#### Import from Clipboard

```bash
# 1. Copy content from Google Docs (⌘+A, ⌘+C)
# 2. Run import
gang import-content

# Reads clipboard automatically!
```

### Example Output

```
📋 Importing from clipboard...
🔍 Analyzing content...

📊 Import Analysis:
├─ Title: My New Article About AI Publishing
├─ Suggested slug: my-new-article-about-ai-publishing
├─ AI category: posts (high confidence)
│  └─ Time-sensitive content about technology trends, best suited for blog
└─ Images found: 2

🖼️  Processing 2 image(s)...
  ✓ Uploaded & compressed: 145KB (saved 42%)
    Alt text (AI): Modern AI publishing dashboard showing analytics
  ✓ Uploaded & compressed: 89KB (saved 38%)
    Alt text (AI): Screenshot of automated quality gate system

📝 Will create: content/posts/my-new-article-about-ai-publishing.md

Preview (first 10 lines):
────────────────────────────────────────────────────────────
---
type: post
title: My New Article About AI Publishing
date: 2025-10-11
status: draft
---

# My New Article About AI Publishing

This is an article about AI-powered publishing...
...
────────────────────────────────────────────────────────────

Create this file? [y/N]: y

✅ Content imported successfully!
📁 File: content/posts/my-new-article-about-ai-publishing.md
✅ Git commit created
   Review: git show

💡 Next steps:
   1. Review and edit: vim content/posts/my-new-article-about-ai-publishing.md
   2. Analyze quality: gang analyze content/posts/my-new-article-about-ai-publishing.md
   3. Change status to 'published' when ready
   4. Build: gang build
```

---

## What Happens Automatically

### Image Processing

1. **Extraction**
   - Finds embedded images (base64 data URLs)
   - Finds HTML `<img>` tags
   - Finds external URLs

2. **Compression**
   - Resizes if >1600px wide
   - Optimizes quality (85%)
   - Reduces file size 30-50%

3. **Upload to R2**
   - Organized by slug: `images/my-article/image-1.jpg`
   - Gets public CDN URL
   - Returns markdown-ready snippet

4. **AI Alt Text**
   - Reads article context
   - Generates descriptive alt text
   - 10-15 words, contextual
   - WCAG AA compliant

### Content Processing

1. **Title Extraction**
   - Finds first `# Heading`
   - Or first `<h1>` tag
   - Or uses first line

2. **Slug Generation**
   - Converts title to URL-safe format
   - Removes special characters
   - Checks for conflicts
   - Suggests unique alternative if needed

3. **Category Suggestion (AI)**
   - Analyzes content type
   - Suggests: posts / pages / projects
   - Provides reasoning
   - High/medium/low confidence

4. **Slug Uniqueness**
   - Checks against ALL existing content
   - Prevents URL conflicts
   - Suggests alternatives (-2, -3, etc.)
   - Blocks if duplicate

### Frontmatter Creation

```yaml
---
type: post
title: My Article
date: 2025-10-11
status: draft  # ← Always starts as draft
---
```

**Always draft** so editor can review before publishing!

---

## Slug Checking (Automatic)

### Built Into Every Build

```bash
gang build

# Output:
🔨 Building site...
✓ All 4 slugs are unique

📦 Copying public assets...
...
```

**If duplicate found:**
```bash
gang build

# Output:
❌ Duplicate slugs detected!

  Slug 'about' used in:
    - pages/about.md
    - posts/about.md

🚫 Cannot build: 1 duplicate slug(s) found
   Run 'gang slugs' for details
   Fix by renaming files to have unique slugs

Exit code: 1 (build blocked)
```

### Manual Check

```bash
# Check slugs anytime
gang slugs

# Output:
✅ All slugs are unique!
```

---

## Complete Import Example

### Scenario: Paste from Google Docs

**Google Docs content:**
```
Title: Product Launch Announcement

We're excited to announce our new product!

[Image: Screenshot of product dashboard]

Key features:
- Fast performance
- Beautiful design
- AI-powered

[Image: Product photo]
```

**Steps:**
```bash
# 1. Select all in Google Docs (⌘+A)
# 2. Copy (⌘+C)  
# 3. Run import
gang import-content --commit

# AI Processing:
📋 Importing from clipboard...
🔍 Analyzing content...

📊 Import Analysis:
├─ Title: Product Launch Announcement
├─ Suggested slug: product-launch-announcement
├─ AI category: posts (high confidence)
│  └─ Announcement with time-sensitive nature, best as blog post
└─ Images found: 2

🖼️  Processing 2 image(s)...
🤖 Compressing image 1... (2.1MB → 450KB, saved 79%)
🤖 Uploading to R2...
   Alt text (AI): Screenshot showing product dashboard with analytics...
   
🤖 Compressing image 2... (1.5MB → 380KB, saved 75%)
🤖 Uploading to R2...
   Alt text (AI): Professional product photo on white background...

📝 Creating: content/posts/product-launch-announcement.md

Create this file? [y/N]: y

✅ Content imported!
✅ Git commit created
✅ 2 images uploaded to R2 (830KB total)
✅ Alt text generated by AI
```

**Result: `content/posts/product-launch-announcement.md`**
```markdown
---
type: post
title: Product Launch Announcement
date: 2025-10-11
status: draft
---

# Product Launch Announcement

We're excited to announce our new product!

![Screenshot showing product dashboard with analytics](https://media.yourdomain.com/images/product-launch-announcement/image-1.jpg)

Key features:
- Fast performance
- Beautiful design  
- AI-powered

![Professional product photo on white background](https://media.yourdomain.com/images/product-launch-announcement/image-2.jpg)
```

---

## Image Compression Stats

### Before Upload

| Image | Original | Compressed | Savings |
|-------|----------|------------|---------|
| Hero photo | 2.1MB | 450KB | 79% |
| Product shot | 1.5MB | 380KB | 75% |
| Screenshot | 890KB | 215KB | 76% |

**Total:** 4.5MB → 1.0MB (78% reduction!)

### Settings

```yaml
# gang.config.yml
images:
  max_width: 1600      # Resize if larger
  quality: 85          # JPEG/WebP quality
  formats: [avif, webp] # Generate variants
```

---

## AI Features

### 1. Category Suggestion

**AI analyzes:**
- Title keywords
- Content structure
- Writing style
- Time sensitivity

**AI suggests:**
```
Category: posts (high confidence)
Reasoning: News/announcement with time-sensitive nature
```

### 2. Alt Text Generation

**AI considers:**
- Article context
- Image purpose
- Accessibility guidelines
- Descriptive clarity

**AI generates:**
```
"Screenshot showing product dashboard with real-time analytics and performance metrics"
```

Not generic:
```
❌ "Image"
❌ "Screenshot"
✅ "Screenshot showing product dashboard with real-time analytics"
```

### 3. Slug Uniqueness

**AI checks:**
- All existing posts
- All existing pages
- All existing projects

**If conflict:**
```
Slug 'announcement' conflicts with:
  - posts/announcement.md

Suggested: announcement-2
```

---

## Commands Reference

### Import Content

```bash
# From file
gang import-content article.txt

# From clipboard (Google Docs paste)
gang import-content

# With specific category
gang import-content article.txt --category posts

# With git commit
gang import-content --commit

# Custom title
gang import-content article.txt --title "My Custom Title"
```

### Check Slugs

```bash
# Check all slugs
gang slugs

# Show fix suggestions
gang slugs --fix
```

### Build with Slug Check

```bash
# Slug check is automatic (default: enabled)
gang build

# Disable if needed
gang build --no-check-slugs

# Full quality gates
gang build --check-quality --validate-links
# (slug check runs automatically)
```

---

## Integration with Build Process

### Default Build

```bash
gang build
```

**Automatically runs:**
1. ✅ Slug uniqueness check
2. Build process
3. Output generation

### With All Gates

```bash
gang build --check-quality --validate-links
```

**Runs in order:**
1. ✅ Slug uniqueness (blocks duplicates)
2. ✅ Content quality (score ≥85)
3. ✅ Link validation (no broken links)
4. Build process
5. Output generation

**Any gate fails → Build blocked!**

---

## Handling Duplicates

### If Duplicate Slug Found

```bash
gang build

# Output:
❌ Duplicate slugs detected!

  Slug 'product-launch' used in:
    - posts/product-launch.md
    - pages/product-launch.md

🚫 Cannot build: 1 duplicate slug(s) found
```

### How to Fix

**Option 1: Rename File**
```bash
# Rename one of the files
mv content/pages/product-launch.md content/pages/product-launch-page.md

# Build again
gang build
# ✅ All slugs unique!
```

**Option 2: Change Slug in Frontmatter** (Future)
```yaml
---
title: Product Launch
slug: product-launch-announcement  # Custom slug
---
```

---

## Requirements

### For Basic Import

- ✅ Gang CLI installed
- ✅ Content to import (file or clipboard)

### For Image Upload

- ✅ R2 configured (see MEDIA_QUICK_START.md)
- ✅ CLOUDFLARE credentials in .env

### For AI Features

- ✅ ANTHROPIC_API_KEY in .env

### If Missing AI

**Without AI key:**
- ❌ No category suggestions
- ❌ No alt text generation
- ✅ Still imports content
- ✅ Still uploads images
- ✅ Still checks slugs

---

## Best Practices

### 1. Always Review Imports

```bash
# Content starts as "draft"
status: draft

# Review before publishing:
vim content/posts/my-new-post.md

# Check quality
gang analyze content/posts/my-new-post.md

# When ready
# Change: status: draft
# To:     status: published

# Build
gang build
```

### 2. Use Git Commits

```bash
gang import-content --commit

# Creates reviewable commit
git show

# Easy to undo if wrong
git reset 'HEAD^'
```

### 3. Compress Images

```bash
# Always enabled by default
gang import-content article.txt

# Disable if needed (not recommended)
gang import-content article.txt --no-compress-images
```

### 4. Check Slugs Before Import

```bash
# See existing slugs
gang slugs

# Import with unique title
gang import-content --title "My Unique Title"
```

---

## Error Handling

### Duplicate Slug

```
⚠️  Slug conflict! 'my-article' already exists:
  - posts/my-article.md

💡 Suggested unique slug: my-article-2

Use 'my-article-2' instead? [y/N]: y
```

### R2 Not Configured

```
⚠️  R2 not configured
   Images will not be uploaded
   
   Continue with import? [y/N]:
```

### No AI Key

```
⚠️  ANTHROPIC_API_KEY not set
   - No category suggestions
   - No alt text generation
   - Manual review required
   
   Continue? [y/N]:
```

---

## Examples

### Example 1: Blog Post from Notes

```bash
# Copy from Notes app
gang import-content --category posts --commit

# AI processes:
✓ Title extracted
✓ Category: posts (AI confirmed)
✓ Slug: my-notes-article
✓ 3 images extracted & uploaded
✓ Alt text generated
✓ File created
✓ Git commit created
```

### Example 2: Documentation from Google Docs

```bash
# Paste from Google Docs
gang import-content --category pages

# AI processes:
✓ Title: API Documentation
✓ Category: pages (AI suggested)
✓ Slug: api-documentation
✓ No slug conflicts
✓ 5 screenshots uploaded
✓ Alt text generated
✓ File created
```

### Example 3: Project Case Study

```bash
gang import-content case-study.html --category projects --commit

# AI processes:
✓ Title: E-Commerce Redesign
✓ Category: projects (confirmed)
✓ Slug: e-commerce-redesign
✓ 8 images (before/after shots)
✓ All compressed & uploaded
✓ Alt text generated
✓ Git commit created
```

---

## What Gets Checked Every Build

```bash
gang build
```

**Automatic checks:**
1. ✅ **Slug uniqueness** (blocks if duplicates)
2. Content processing
3. Output generation

```bash
gang build --check-quality --validate-links
```

**Full quality gates:**
1. ✅ **Slug uniqueness** (blocks duplicates)
2. ✅ Content quality (score ≥85)
3. ✅ Link validation (no broken links)
4. Content processing
5. Output generation

**All must pass or build fails!**

---

## Slug Checking Details

### What Is a Slug?

**Slug:** URL-safe identifier for content

```
Title: "My Awesome Article!"
Slug:  my-awesome-article

URL:   https://yourdomain.com/posts/my-awesome-article/
```

### How Slugs Are Generated

```
Title:    "Product Launch: Q2 2025!"
          ↓ (lowercase)
          "product launch: q2 2025!"
          ↓ (remove special chars)
          "product launch q2 2025"
          ↓ (replace spaces with hyphens)
          "product-launch-q2-2025"
          ↓ (limit length)
Slug:     "product-launch-q2-2025"
```

### Uniqueness Rules

**Across ALL content types:**
```
❌ BAD:
  posts/about.md      → /posts/about/
  pages/about.md      → /pages/about/
  
  Both have slug "about" - CONFLICT!

✅ GOOD:
  posts/about-us.md   → /posts/about-us/
  pages/about.md      → /pages/about/
  
  Different slugs - OK!
```

### Auto-Resolution

If duplicate found:
```
Original: my-article
Conflict detected!

Suggestions:
  1. my-article-2
  2. my-article-3
  ...
  
First available: my-article-2
```

---

## Supported Input Formats

### Plain Text
```
# My Article

Content here...
```

### Markdown
```markdown
# My Article

**Bold text** and *italic*

![Image](image.jpg)
```

### HTML (Google Docs)
```html
<h1>My Article</h1>
<p>Content here...</p>
<img src="data:image/png;base64,..." />
```

### Rich Text (Notes)
```
Pasted with formatting, images embedded as data URLs
```

---

## Current Status

✅ **Slug checking:** Integrated into build (enabled by default)  
✅ **Import system:** Ready to use  
✅ **Image processing:** Compression + R2 upload  
✅ **AI assistance:** Category suggestions + alt text  
✅ **Git integration:** Optional commits for review  

---

## Try It Now

### Test Slug Checker

```bash
gang slugs
```

### Test Import (When R2 Configured)

```bash
# Create test file
echo "# Test Article

This is a test.
" > /tmp/test.txt

# Import
gang import-content /tmp/test.txt
```

---

**Your content import system is production-ready!** 🚀

See also:
- **MEDIA_QUICK_START.md** - R2 setup (5 min)
- **R2_SETUP.md** - Complete R2 guide


# Slug Rename & 301 Redirect Guide

## Overview

When you rename a content slug, you **must** create a 301 redirect to preserve SEO and prevent broken links. The GANG platform makes this automatic and safe.

## Why This Matters

Changing a URL breaks:
- **Search engine rankings** - Google sees it as a new page
- **External links** - Other sites linking to you get 404s
- **Bookmarks** - User bookmarks stop working
- **Social shares** - Shared links break

**301 redirects tell search engines**: "This page permanently moved to a new location."

---

## Quick Start

### Rename with 301 redirect (default)
```bash
gang rename-slug old-slug new-slug --category posts
```

### Rename without redirect (⚠️ breaks SEO)
```bash
gang rename-slug old-slug new-slug --category posts --no-redirect
```

---

## Complete Workflow

### Step 1: Rename the slug
```bash
gang rename-slug my-old-post my-new-post --category posts
```

**Output:**
```
📝 Rename slug in posts:
   From: my-old-post
   To:   my-new-post

🔀 Will create 301 redirect:
   /posts/my-old-post/ → /posts/my-new-post/

Proceed with rename? [y/N]: y
✅ File renamed: my-old-post.md → my-new-post.md
✅ 301 redirect created
📄 Redirects file: .redirects.json

Create git commit? [y/N]: y
✅ Git commit created
```

### Step 2: Review the redirect
```bash
gang redirects list
```

**Output:**
```
📋 1 redirect(s):

  /posts/my-old-post/ → /posts/my-new-post/ (301)
    Reason: slug_rename
    Created: 2025-10-12T00:00:00
```

### Step 3: Build and deploy
```bash
gang build
```

This automatically generates `dist/_redirects` for Cloudflare Pages:
```
# GANG Platform Redirects
# Generated automatically - do not edit manually
# Last updated: 2025-10-12T00:00:00

/posts/my-old-post/ /posts/my-new-post/ 301
```

### Step 4: Deploy
```bash
# Your redirects go live automatically
# Cloudflare Pages reads dist/_redirects
```

---

## Managing Redirects

### List all redirects
```bash
gang redirects list                    # Human-readable
gang redirects list --format json      # JSON
gang redirects list --format cloudflare # _redirects format
gang redirects list --format nginx     # nginx config
gang redirects list --format netlify   # Netlify format
```

### Add a manual redirect
```bash
# Permanent (301)
gang redirects add /old-path/ /new-path/

# Temporary (302)
gang redirects add /old-path/ /new-path/ --temporary
```

### Remove a redirect
```bash
gang redirects remove /old-path/
```

### Validate redirects
```bash
gang redirects validate
```

Checks for:
- **Redirect chains**: A → B → C (SEO penalty)
- **Redirect loops**: A → B → A (breaks site)

**Example of a problem:**
```
⚠️  Found 1 issue(s):
  • Redirect chain (2 hops): /posts/old/ → /posts/new/ → /posts/newest/
```

**Fix:** Update the redirect to point directly:
```bash
gang redirects remove /posts/old/
gang redirects add /posts/old/ /posts/newest/
```

---

## Redirect Storage

### `.redirects.json` (source of truth)
```json
{
  "redirects": [
    {
      "from": "/posts/old-slug/",
      "to": "/posts/new-slug/",
      "status": 301,
      "reason": "slug_rename",
      "created": "2025-10-12T00:00:00"
    }
  ],
  "version": "1.0"
}
```

- **Track in git** - Version control for redirects
- **Portable** - Works with any hosting platform
- **Auditable** - Know when and why each redirect was created

### `dist/_redirects` (generated)
```
/posts/old-slug/ /posts/new-slug/ 301
```

- Auto-generated during `gang build`
- Format depends on hosting (Cloudflare by default)
- **Never edit manually** - Changes will be overwritten

---

## Platform-Specific Formats

### Cloudflare Pages (default)
```bash
gang redirects list --format cloudflare > dist/_redirects
```

Format:
```
/old-path /new-path 301
```

Automatically deployed with your site.

### Netlify
```bash
gang redirects list --format netlify > dist/_redirects
```

Same format as Cloudflare.

### nginx
```bash
gang redirects list --format nginx > /etc/nginx/conf.d/redirects.conf
```

Format:
```nginx
rewrite ^/old-path$ /new-path permanent;
```

Add to your nginx config and reload:
```bash
sudo nginx -t && sudo nginx -s reload
```

---

## Best Practices

### ✅ DO

1. **Always create redirects for renamed content**
   ```bash
   gang rename-slug old new --category posts
   # ✅ Creates redirect automatically
   ```

2. **Validate before deploying**
   ```bash
   gang redirects validate
   gang build
   ```

3. **Track redirects in git**
   ```bash
   git add .redirects.json
   git commit -m "Add redirect: /old/ → /new/"
   ```

4. **Keep redirects forever (or at least 1 year)**
   - Search engines need time to update
   - External links may never update
   - Bookmarks don't expire

### ❌ DON'T

1. **Don't skip redirects**
   ```bash
   # ❌ Breaks SEO
   gang rename-slug old new --category posts --no-redirect
   ```

2. **Don't create redirect chains**
   ```bash
   # ❌ Bad (2 redirects)
   /posts/v1/ → /posts/v2/
   /posts/v2/ → /posts/v3/
   
   # ✅ Good (1 redirect)
   /posts/v1/ → /posts/v3/
   /posts/v2/ → /posts/v3/
   ```

3. **Don't manually edit `dist/_redirects`**
   - It's regenerated on every build
   - Edit `.redirects.json` or use CLI commands

4. **Don't delete redirects too soon**
   - Wait at least 6-12 months
   - Check analytics first (is old URL still getting traffic?)

---

## Common Scenarios

### Scenario 1: Simple rename
```bash
# Rename post
gang rename-slug my-post my-better-post --category posts

# Build and deploy
gang build
# Deploy to hosting
```

✅ Old URL redirects to new URL automatically.

### Scenario 2: Reorganize content structure
```bash
# Moving from /posts/ to /articles/
# Manual redirect (file needs to be moved manually)
mv content/posts/my-post.md content/articles/my-post.md

gang redirects add /posts/my-post/ /articles/my-post/
gang build
```

### Scenario 3: Merge two posts
```bash
# Keep post-a.md, delete post-b.md
gang redirects add /posts/post-b/ /posts/post-a/

# Manually delete post-b.md or mark as draft
rm content/posts/post-b.md

gang build
```

### Scenario 4: Remove old content
```bash
# Redirect to category page or homepage
gang redirects add /posts/outdated-post/ /posts/

# Delete the content
rm content/posts/outdated-post.md

gang build
```

---

## Integration with Build Process

Redirects are **automatically integrated** into every build:

```bash
gang build
```

**Output:**
```
🔨 Building site...
✓ All 10 slugs are unique
📦 Copying public assets...
📝 Processing content...
🏠 Creating index page...
📄 Creating list pages...
🗺️  Generating sitemap, robots.txt, and feeds...
🔀 Generated 5 redirect(s) → dist/_redirects    ← Automatic!
✅ Build complete! Output in dist
```

If no redirects exist, the build silently skips this step.

---

## Quality Gates

### Check for redirect issues before deploying
```bash
# Build with all quality gates
gang build \
  --check-quality \
  --validate-links \
  --check-slugs

# Then validate redirects
gang redirects validate
```

### Block builds with redirect chains
Create a pre-deploy script:
```bash
#!/bin/bash
gang redirects validate || exit 1
gang build --validate-links
```

---

## Troubleshooting

### Problem: Redirect not working
**Check 1:** Is it in `.redirects.json`?
```bash
gang redirects list
```

**Check 2:** Did you rebuild?
```bash
gang build
ls -la dist/_redirects
```

**Check 3:** Did you deploy?
```bash
# Check your hosting platform
# Cloudflare Pages: Check deployment logs
```

### Problem: Too many redirects error
**Cause:** Redirect loop (A → B → A)

**Fix:**
```bash
gang redirects validate
# Identifies the loop

gang redirects remove /path-causing-loop/
```

### Problem: Old URL still returns 404
**Check 1:** Wait for CDN cache to clear (5-10 minutes)

**Check 2:** Verify redirect format matches hosting platform
```bash
# Cloudflare/Netlify
gang redirects list --format cloudflare

# nginx
gang redirects list --format nginx
```

---

## SEO Impact

### What Google Sees

**Without 301:**
```
Old URL: 404 Not Found
→ Google: "Page deleted, remove from index"
→ You: Lost all rankings
```

**With 301:**
```
Old URL: 301 Moved Permanently → New URL
→ Google: "Page moved, transfer rankings to new URL"
→ You: Keep ~90-99% of rankings
```

### Timeline
- **Day 1-7:** Google starts noticing redirects
- **Week 2-4:** Rankings begin transferring
- **Month 1-3:** Full ranking transfer (usually)
- **Month 6+:** Safe to remove redirect (check analytics first)

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `gang rename-slug OLD NEW --category TYPE` | Rename slug with 301 |
| `gang rename-slug OLD NEW --category TYPE --no-redirect` | Rename without redirect |
| `gang redirects list` | Show all redirects |
| `gang redirects list --format cloudflare` | Export for Cloudflare |
| `gang redirects list --format nginx` | Export for nginx |
| `gang redirects add FROM TO` | Add manual redirect (301) |
| `gang redirects add FROM TO --temporary` | Add temporary redirect (302) |
| `gang redirects remove PATH` | Remove redirect |
| `gang redirects validate` | Check for chains/loops |

---

## Related Documentation

- `CONTENT_IMPORT_GUIDE.md` - Importing content
- `QUALITY_GATES.md` - Build quality checks
- `LINK_VALIDATOR.md` - Finding broken links
- `CLOUDFLARE_SETUP.md` - Deploying to Cloudflare Pages

---

## Summary

1. **Always create redirects** when renaming content
2. Use `gang rename-slug` for safe, automatic redirects
3. Validate with `gang redirects validate`
4. Redirects are **automatically included** in every build
5. Keep redirects for at least 6-12 months
6. Check for chains and loops before deploying

**Bottom line:** Changing slugs is safe and SEO-friendly when you use 301 redirects. The GANG platform makes it automatic.


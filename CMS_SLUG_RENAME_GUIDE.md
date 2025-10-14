# CMS Slug Rename Feature

## Overview

The GANG Studio CMS now includes a built-in slug rename feature with automatic 301 redirect creation. Editors can safely rename content URLs directly from the CMS without breaking SEO or external links.

---

## Features

✅ **Visual slug renaming** - Rename directly in the CMS  
✅ **Automatic 301 redirects** - Preserve SEO automatically  
✅ **Redirect management** - View and manage all redirects  
✅ **Slug validation** - Prevents duplicate or invalid slugs  
✅ **Real-time feedback** - See redirect preview before applying  
✅ **Zero downtime** - File renamed and redirect created atomically  

---

## How to Use

### Step 1: Start the CMS

```bash
gang studio
```

Open `http://localhost:3000` in your browser.

### Step 2: Open a content file

Click on any content file in the sidebar to load it in the editor.

### Step 3: Rename the slug

1. Click the **🔄 Rename Slug** button in the toolbar
2. Enter the new slug in the dialog
3. Keep "Create 301 redirect" checked (recommended)
4. Click **Rename**

**That's it!** The file is renamed and the redirect is created automatically.

---

## UI Walkthrough

### Toolbar Buttons

| Button | Function |
|--------|----------|
| 💾 Save | Save current file |
| 🔄 Rename Slug | Rename slug + create redirect |
| 🔀 Redirects | View/manage all redirects |
| 🔨 Build | Build site (runs `gang build`) |
| 🤖 Optimize | AI optimize (runs `gang optimize`) |

### Rename Slug Dialog

```
┌─────────────────────────────────────┐
│ Rename Slug                         │
├─────────────────────────────────────┤
│ ⚠️  Important:                      │
│ Renaming a slug changes the URL.    │
│ Always create a 301 redirect to     │
│ preserve SEO and prevent broken     │
│ links.                              │
│                                     │
│ Current slug: [my-old-post]         │
│ New slug:     [my-new-post____]     │
│                                     │
│ ☑ Create 301 redirect (recommended)│
│                                     │
│ ℹ️  Redirect will be created:       │
│   /posts/my-old-post/               │
│   → /posts/my-new-post/             │
│                                     │
│         [Cancel]  [Rename]          │
└─────────────────────────────────────┘
```

### Redirects Panel

Click **🔀 Redirects** to view all active redirects:

```
┌─────────────────────────────────────┐
│ Redirects                           │
├─────────────────────────────────────┤
│ /posts/old-slug/                    │
│ → /posts/new-slug/         [Delete] │
├─────────────────────────────────────┤
│ /pages/archived/                    │
│ → /pages/about/            [Delete] │
└─────────────────────────────────────┘
```

---

## API Endpoints

The CMS communicates with these API endpoints (automatically handled):

### `POST /api/rename-slug`

Rename a slug and optionally create a redirect.

**Request:**
```json
{
  "old_slug": "my-old-post",
  "new_slug": "my-new-post",
  "category": "posts",
  "create_redirect": true
}
```

**Response:**
```json
{
  "success": true,
  "old_path": "posts/my-old-post.md",
  "new_path": "posts/my-new-post.md",
  "redirect": {
    "from": "/posts/my-old-post/",
    "to": "/posts/my-new-post/",
    "status": 301,
    "reason": "slug_rename_cms",
    "created": "2025-10-12T00:00:00"
  }
}
```

### `POST /api/redirects`

List all redirects.

**Response:**
```json
[
  {
    "from": "/posts/old/",
    "to": "/posts/new/",
    "status": 301,
    "reason": "slug_rename_cms",
    "created": "2025-10-12T00:00:00"
  }
]
```

### `DELETE /api/redirects/{path}`

Delete a redirect.

**Example:**
```
DELETE /api/redirects/posts/old-slug/
```

### `PUT /api/content/{path}`

Save a content file.

**Example:**
```
PUT /api/content/posts/my-post.md
Content-Type: text/plain

---
title: My Post
---

Content here...
```

---

## Safety Features

### 1. Slug Validation

The CMS validates new slugs before applying:

✅ Only lowercase letters, numbers, and hyphens  
✅ Cannot be empty  
✅ Must be unique (checks for existing files)  
✅ Real-time validation with error messages  

**Valid slugs:**
- `my-post`
- `hello-world-2024`
- `design-system-v2`

**Invalid slugs:**
- `My Post` (uppercase, spaces)
- `my_post` (underscores)
- `my post!` (special characters)

### 2. Duplicate Detection

If the new slug already exists, the CMS shows an error:

```
❌ Error: Slug already exists
A file with slug "my-new-slug" already exists
```

### 3. Automatic Redirect Creation

Redirects are created by default to prevent:
- Broken links from other sites
- Lost search engine rankings
- 404 errors for bookmarks
- Broken internal links

### 4. Redirect Preview

Before applying the rename, you see exactly what redirect will be created:

```
ℹ️  Redirect will be created:
  /posts/my-old-post/ → /posts/my-new-post/
```

### 5. Atomic Operations

The rename + redirect creation happens in a single transaction:
- File is renamed
- Redirect is added to `.redirects.json`
- If either fails, both are rolled back

---

## Workflow Examples

### Example 1: Simple rename with redirect

1. Open `posts/launch.md` in CMS
2. Click **🔄 Rename Slug**
3. Change `launch` to `product-launch`
4. Keep redirect checkbox checked
5. Click **Rename**

**Result:**
- File: `posts/product-launch.md`
- Redirect: `/posts/launch/` → `/posts/product-launch/` (301)
- SEO preserved ✅

### Example 2: Rename without redirect (not recommended)

1. Open `posts/draft.md` in CMS
2. Click **🔄 Rename Slug**
3. Change `draft` to `final`
4. **Uncheck** redirect checkbox
5. Click **Rename**

**Result:**
- File: `posts/final.md`
- No redirect created
- Old URL returns 404 ⚠️

**Use case:** Content was never published, no external links exist.

### Example 3: Managing redirects

After renaming several slugs:

1. Click **🔀 Redirects** to open the panel
2. Review all active redirects
3. Delete outdated redirects (optional)
4. Panel shows real-time redirect list

---

## Integration with CLI

### The CMS and CLI work together seamlessly:

**CMS creates redirects:**
```
# In CMS: Rename "old-post" → "new-post"
# Creates redirect in .redirects.json
```

**CLI uses redirects:**
```bash
# Build site
gang build

# Output includes:
🔀 Generated 1 redirect(s) → dist/_redirects
```

**Deploy:**
```bash
# Redirects are automatically included
# Works with Cloudflare Pages, Netlify, etc.
```

### You can also manage redirects via CLI:

```bash
# List redirects
gang redirects list

# Rename slug via CLI
gang rename-slug old-post new-post --category posts

# Validate redirects (check for chains/loops)
gang redirects validate
```

---

## Best Practices

### ✅ DO

1. **Always create redirects for published content**
   - If the page has been live, create a redirect
   - If it has any external links, create a redirect
   - If it's indexed by search engines, create a redirect

2. **Use descriptive slugs**
   - `design-system-v2` better than `ds2`
   - `getting-started-guide` better than `guide`

3. **Keep slugs consistent**
   - `my-post` not `my_post` or `mypost`
   - Use hyphens, not underscores

4. **Review redirects periodically**
   - Check the redirects panel
   - Remove redirects for deleted content after 6+ months

### ❌ DON'T

1. **Don't skip redirects for live content**
   - Always check the redirect box
   - Exception: Content was never published

2. **Don't create redirect chains**
   - Bad: A → B, B → C (2 hops)
   - Good: A → C, B → C (direct)
   - Use `gang redirects validate` to check

3. **Don't use invalid characters**
   - No spaces, uppercase, or special characters
   - Stick to lowercase letters, numbers, hyphens

4. **Don't rename slugs frequently**
   - Pick a good slug initially
   - Only rename when necessary
   - Each rename requires a redirect

---

## Troubleshooting

### Problem: Rename button is disabled

**Cause:** No file is loaded.

**Fix:** Click on a file in the sidebar to load it.

---

### Problem: "Slug already exists" error

**Cause:** Another file already uses that slug.

**Fix:** Choose a different, unique slug.

---

### Problem: Redirect not showing in panel

**Cause:** 
- Redirect was not created (checkbox unchecked)
- Panel needs refresh

**Fix:** 
- Click **🔀 Redirects** to reload the panel
- Check `.redirects.json` file

---

### Problem: Changes not visible on site

**Cause:** Site needs to be rebuilt.

**Fix:**
```bash
gang build
gang serve  # or deploy
```

---

### Problem: Invalid slug format error

**Cause:** Slug contains invalid characters.

**Fix:** Use only lowercase letters, numbers, and hyphens.

**Examples:**
- ✅ `my-new-post`
- ❌ `My New Post`
- ❌ `my_new_post`
- ❌ `my new post!`

---

## CLI + CMS Comparison

| Action | CLI Command | CMS Action |
|--------|-------------|------------|
| Rename slug | `gang rename-slug old new --category posts` | Click **🔄 Rename Slug** |
| List redirects | `gang redirects list` | Click **🔀 Redirects** |
| Delete redirect | `gang redirects remove /path/` | Click **Delete** in panel |
| Check duplicates | `gang slugs` | Automatic validation |
| Build site | `gang build` | Click **🔨 Build** |

**Both approaches:**
- Use the same `.redirects.json` file
- Create the same `dist/_redirects` output
- Support all hosting platforms
- Preserve SEO with 301 redirects

---

## File Structure

### `.redirects.json` (created automatically)

```json
{
  "redirects": [
    {
      "from": "/posts/old-slug/",
      "to": "/posts/new-slug/",
      "status": 301,
      "reason": "slug_rename_cms",
      "created": "2025-10-12T00:00:00"
    }
  ],
  "version": "1.0"
}
```

**Location:** Project root  
**Tracked in git:** Yes  
**Auto-generated:** No (but auto-updated)  

### `dist/_redirects` (generated during build)

```
# GANG Platform Redirects
# Generated automatically - do not edit manually
# Last updated: 2025-10-12T00:00:00

/posts/old-slug/ /posts/new-slug/ 301
```

**Location:** `dist/` directory  
**Tracked in git:** No  
**Auto-generated:** Yes (every build)  
**Format:** Cloudflare Pages / Netlify  

---

## Summary

The CMS slug rename feature makes it **safe and easy** to rename content URLs:

1. ✅ Click **🔄 Rename Slug** in the CMS
2. ✅ Enter new slug
3. ✅ Keep redirect checkbox checked
4. ✅ Click **Rename**
5. ✅ Build and deploy

**Result:**
- File renamed
- 301 redirect created
- SEO preserved
- No broken links
- Zero downtime

---

## Related Documentation

- `SLUG_RENAME_GUIDE.md` - CLI slug rename guide
- `QUALITY_GATES.md` - Build quality checks
- `COLLABORATIVE_WORKFLOW.md` - Team workflows

---

## Quick Reference

```bash
# Start CMS
gang studio

# CLI equivalents
gang rename-slug old new --category posts
gang redirects list
gang redirects validate

# Build with redirects
gang build  # Auto-includes redirects
```

**Bottom line:** Rename slugs safely in the CMS. Redirects are automatic, SEO is preserved, and your team can work confidently without breaking links.


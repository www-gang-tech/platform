# In-Place Editor Demo Guide

## 🎯 Quick Demo (5 minutes)

This guide shows how to test the new in-place editor feature.

## Prerequisites

- Python 3.8+ with Flask
- Node.js (for testing)
- Git configured

## Step 1: Start the Backend API

Open a terminal and start the Flask backend:

```bash
cd apps/studio/backend

# Install dependencies (first time only)
pip install -r requirements.txt

# Start the server
python app.py
```

You should see:
```
🚀 GANG Studio Backend starting...
📁 Content directory: /path/to/content
...
 * Running on http://0.0.0.0:5000
```

**Keep this terminal open!**

## Step 2: Build Site with Editor Enabled

Open a **new terminal** and build the site with editor mode:

```bash
export EDITOR_MODE=true
gang build
```

This builds the site with the edit button and editor scripts included.

## Step 3: Serve the Site

In the same terminal, serve the built site:

```bash
python -m http.server 8000 --directory dist
```

Or use any static file server.

## Step 4: Open in Browser

Visit any content page, for example:
- http://localhost:8000/pages/manifesto/
- http://localhost:8000/pages/about/
- http://localhost:8000/posts/qi2-launch/

You should see a **floating "✏️ Edit" button** in the bottom-right corner!

## Step 5: Test the Editor

1. **Click the "✏️ Edit" button**
   - Page content will be replaced with ToastUI Editor
   - Floating toolbar appears at the top
   - Original markdown loads into editor

2. **Make changes**
   - Edit the content in WYSIWYG or Markdown mode
   - Click "🔄 Toggle Mode" to switch between modes

3. **Validate headings**
   - Click "✓ Check Headings"
   - See validation results
   - Fix any WCAG issues

4. **Save draft (optional)**
   - Click "💾 Save Draft" to save locally
   - Or press **Cmd/Ctrl + S**
   - Drafts persist in localStorage

5. **Publish**
   - Click "📤 Publish"
   - Content is validated
   - Saved to disk
   - Git commit created (if AUTO_PUSH=true, also pushes)
   - Page reloads with new content

6. **Cancel**
   - Click "❌ Cancel" to discard changes
   - Or press **Esc**
   - Original content restored

## Features to Test

### ✅ Core Features
- [ ] Edit button appears on authenticated pages
- [ ] Editor loads with current content
- [ ] WYSIWYG and Markdown modes work
- [ ] Toolbar buttons function correctly
- [ ] Keyboard shortcuts (Cmd+S, Esc)

### ✅ Validation
- [ ] Heading validation catches errors
- [ ] Error modal shows suggestions
- [ ] Can publish anyway or fix issues

### ✅ Persistence
- [ ] Drafts save to localStorage
- [ ] Draft recovery on next edit
- [ ] Published changes persist

### ✅ Mobile/Responsive
- [ ] Works on mobile viewport
- [ ] Toolbar wraps properly
- [ ] Touch events work

## Troubleshooting

### Edit button doesn't appear
**Check:**
- Is EDITOR_MODE=true when building?
- Did you rebuild after setting env var?
- Check browser console for errors

**Fix:**
```bash
export EDITOR_MODE=true
gang build
```

### Editor fails to load
**Check:**
- Is backend running on port 5000?
- Any CORS errors in console?
- ToastUI CDN accessible?

**Fix:**
```bash
# In apps/studio/backend:
python app.py
```

### "Failed to load content" error
**Check:**
- Is the file in content/pages or content/posts?
- Correct category and slug in URL?

**Fix:** Check `body` data attributes:
```html
<body data-category="pages" data-slug="manifesto">
```

### Publish doesn't work
**Check:**
- Git is configured?
- Content directory has changes?
- AUTO_PUSH environment variable?

**Fix:**
```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"

# Enable auto-push:
AUTO_PUSH=true python app.py
```

## Advanced Testing

### Test Multiple Content Types

```bash
# Test pages
http://localhost:8000/pages/manifesto/

# Test posts  
http://localhost:8000/posts/qi2-launch/

# Test projects
http://localhost:8000/projects/design-system-rebuild/
```

### Test API Directly

```bash
# Run test script
./apps/studio/backend/test_api.sh

# Or manually:
curl http://localhost:5001/api/health
curl http://localhost:5001/api/content/pages/manifesto
```

### Test Validation

Create content with bad heading structure:
```markdown
---
title: Test
---

## Wrong Start (should be H1)

# Main Title (H1 after H2)

#### Too Deep Skip (H2 -> H4)
```

Click "✓ Check Headings" to see errors.

## Production Deployment

### Option 1: Cloudflare Access (Recommended)

1. Set up Cloudflare Zero Trust
2. Protect `/api/*` routes
3. Allow only your email
4. Remove EDITOR_MODE env var
5. Backend checks `CF-Access-Authenticated-User-Email` header

### Option 2: GitHub OAuth

1. Create GitHub OAuth App
2. Add authentication middleware
3. Verify GitHub token on each request
4. Store session in secure cookie

### Option 3: Simple Token

1. Generate secure API token
2. Add to environment variable
3. Check token on each API request
4. Rotate regularly

## Next Steps

After testing Phase 1 MVP:

1. **Port Additional Features**
   - Slug rename modal
   - Redirect management
   - Product sync
   - Image upload to R2

2. **Enhance UX**
   - Real-time preview
   - Collaborative indicators
   - AI writing assistant
   - Auto-save improvements

3. **Optimize Performance**
   - Lazy load ToastUI only when needed
   - Optimize bundle size
   - Add service worker caching

4. **Security Hardening**
   - Implement proper authentication
   - Add CSRF protection
   - Rate limiting
   - Input sanitization

## Success Metrics

✅ Phase 1 MVP is complete when:
- Edit button appears on authenticated pages
- Editor loads in <500ms
- Can edit, validate, and publish content
- Changes persist and trigger deployment
- No WCAG violations in editor UI
- Works on mobile devices

---

**Questions or issues?** Check:
- Backend logs in terminal 1
- Browser console in DevTools
- Network tab for API calls
- `apps/studio/backend/README.md`



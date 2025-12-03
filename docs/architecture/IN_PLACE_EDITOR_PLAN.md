# In-Place Editor Integration Plan

## Vision
Transform the studio from a separate interface (`/studio`) into contextual, in-place editing that activates directly on published pages. Users can click "Edit" on any page (e.g., `/pages/manifesto`) and the content enters edit mode with floating toolbars—no layout change, no context switch.

## Current Architecture

### Studio (Separate Interface)
- **Location**: `studio.html` - standalone single-page app
- **Editor**: ToastUI Editor (WYSIWYG + Markdown modes)
- **Backend APIs**:
  - `/api/content` - list all editable files
  - `/api/content/{path}` - get/save content
  - `/api/validate-headings` - WCAG heading validation
  - `/api/rename-slug` - rename with redirect creation
  - `/api/redirects` - manage 301 redirects
  - `/api/products/sync` - Shopify integration
- **Features**:
  - Sidebar file browser
  - Toolbar with Publish/Save/Validate
  - Heading validation (WCAG compliance)
  - Slug renaming with SEO redirects
  - Live WYSIWYG/Markdown toggle

### Build System
- **CLI**: `gang build` (Python)
- **Process**: Markdown → HTML via Jinja2 templates
- **Deploy**: GitHub Actions → Cloudflare Pages
- **Validation**: Contract checks, Lighthouse, Axe a11y
- **Constraints**: No JS on read pages (project rule)

## Target Architecture

### 1. In-Place Editor Activation

#### Edit Mode Toggle
```html
<!-- On every published page -->
<body data-page-type="page" data-slug="manifesto" data-category="pages">
  
  <!-- Edit trigger (only visible to authenticated users) -->
  <button class="edit-trigger" aria-label="Edit this page">
    ✏️ Edit
  </button>

  <!-- Content becomes editable when activated -->
  <main role="main" id="editable-content">
    <!-- Current page content -->
  </main>

  <!-- Floating editor UI (hidden by default) -->
  <div class="editor-ui" hidden>
    <div class="editor-toolbar">
      <button>📤 Publish</button>
      <button>💾 Save Draft</button>
      <button>✓ Check Headings</button>
      <button>🔄 Rename Slug</button>
      <button>❌ Cancel</button>
    </div>
  </div>

  <!-- Editor scripts (loaded only when needed) -->
  <script src="/assets/editor-bundle.js" defer></script>
</body>
```

#### Edit Mode Behavior
1. **Click "Edit"** → Fetch raw markdown from `/api/content/{category}/{slug}`
2. **Transform page** → Replace `<main>` with ToastUI Editor instance
3. **Show floating toolbar** → Position at top/bottom of viewport
4. **Preserve context** → Same URL, same layout, same navigation
5. **Exit edit mode** → Restore original HTML or reload page

### 2. Progressive Enhancement Pattern

Since project rules prohibit JS on read-only pages, we use conditional loading:

```html
<!-- base.html template -->
{% if user_is_authenticated %}
  <!-- Preload editor resources -->
  <link rel="preload" href="/assets/editor-bundle.js" as="script">
  <link rel="preload" href="/assets/toastui-editor.css" as="style">
  
  <!-- Show edit trigger -->
  <button class="edit-trigger" onclick="activateEditor()">✏️ Edit</button>
{% endif %}
```

**Constraints Met**:
- ✅ No JS on public/unauthenticated pages
- ✅ JS only loads for authenticated editors
- ✅ Core content accessible without JS
- ✅ Editor enhancement is progressive

### 3. Authentication Layer

#### Simple Auth Options

**Option A: HTTP Basic Auth** (Simplest)
```yaml
# Cloudflare _headers
/api/*
  CF-Access-Require-Auth: true
  WWW-Authenticate: Basic realm="GANG Editor"
```

**Option B: Cloudflare Access** (Recommended)
```yaml
# Zero Trust auth via Cloudflare
/api/*
  CF-Access-Require: email:[YOUR_EMAIL]
```

**Option C: GitHub OAuth** (Most flexible)
```python
# Studio backend authenticates via GitHub
@app.before_request
def check_auth():
    if request.path.startswith('/api'):
        token = request.headers.get('Authorization')
        # Verify GitHub token
        if not verify_github_user(token):
            return jsonify({'error': 'Unauthorized'}), 401
```

#### Session Detection
```javascript
// editor-client.js
async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/status');
    if (res.ok) {
      const { authenticated, user } = await res.json();
      if (authenticated) {
        showEditTrigger(user);
      }
    }
  } catch (e) {
    // Not authenticated - hide editor UI
  }
}
```

### 4. Editor Bundle Architecture

#### File Structure
```
public/
├── editor-bundle.js         # Lazy-loaded editor code
├── editor-bundle.css        # Editor-specific styles
└── toastui-editor.min.js    # Toast UI library (CDN or local)
```

#### Bundle Contents (`editor-bundle.js`)
```javascript
// 1. ToastUI Editor initialization
import Editor from '@toast-ui/editor';

// 2. Edit mode controller
class InPlaceEditor {
  constructor() {
    this.editor = null;
    this.originalContent = null;
    this.currentFile = null;
  }

  async activate() {
    // Store original HTML
    this.originalContent = document.querySelector('main').innerHTML;
    
    // Fetch markdown source
    const { category, slug } = document.body.dataset;
    const res = await fetch(`/api/content/${category}/${slug}`);
    const markdown = await res.text();
    
    // Replace main with editor
    this.renderEditor(markdown);
    this.showToolbar();
  }

  renderEditor(markdown) {
    const main = document.querySelector('main');
    main.innerHTML = '<div id="editor-mount"></div>';
    
    this.editor = new Editor({
      el: document.querySelector('#editor-mount'),
      initialValue: markdown,
      height: '100vh',
      initialEditType: 'wysiwyg',
      usageStatistics: false,
      toolbarItems: [
        ['heading', 'bold', 'italic'],
        ['ul', 'ol', 'task'],
        ['table', 'link', 'image'],
        ['code', 'codeblock']
      ]
    });
  }

  async publish() {
    // Validate headings (WCAG)
    const valid = await this.validateHeadings();
    if (!valid && !confirm('Publish with heading errors?')) {
      return;
    }

    // Save content
    const markdown = this.editor.getMarkdown();
    const { category, slug } = document.body.dataset;
    
    await fetch(`/api/content/${category}/${slug}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'text/plain' },
      body: markdown
    });

    // Trigger rebuild & deploy
    await fetch('/api/build', { method: 'POST' });
    
    // Show success message
    this.showNotification('✅ Published! Deploying...', 'success');
    
    // Reload page after deploy completes
    setTimeout(() => location.reload(), 3000);
  }

  async validateHeadings() {
    const markdown = this.editor.getMarkdown();
    const res = await fetch('/api/validate-headings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: markdown })
    });
    const result = await res.json();
    
    if (!result.valid) {
      this.showValidationErrors(result.errors, result.suggestions);
    }
    
    return result.valid;
  }

  cancel() {
    if (confirm('Discard changes?')) {
      // Restore original content
      document.querySelector('main').innerHTML = this.originalContent;
      this.hideToolbar();
      this.editor?.destroy();
      this.editor = null;
    }
  }
}

// Global instance
window.gangEditor = new InPlaceEditor();

// Export activation function
window.activateEditor = () => window.gangEditor.activate();
```

### 5. Backend API Updates

The existing studio APIs remain mostly unchanged, but we add:

#### New Endpoint: Trigger Build
```python
# apps/studio/backend/routes/build.py
@app.route('/api/build', methods=['POST'])
@require_auth
def trigger_build():
    """Trigger GitHub Actions build after content save"""
    import subprocess
    
    # Option 1: Commit & push (triggers GitHub Actions)
    subprocess.run(['git', 'add', 'content/'])
    subprocess.run(['git', 'commit', '-m', 'Content update via in-place editor'])
    subprocess.run(['git', 'push', 'origin', 'main'])
    
    # Option 2: Direct API call to GitHub Actions
    # trigger_github_workflow('build-deploy')
    
    return jsonify({'status': 'building'})
```

#### Enhanced Auth Endpoint
```python
@app.route('/api/auth/status')
def auth_status():
    """Check if user is authenticated"""
    token = request.headers.get('Authorization')
    
    if verify_auth(token):
        return jsonify({
            'authenticated': True,
            'user': get_user_info(token)
        })
    
    return jsonify({'authenticated': False}), 401
```

### 6. Floating Toolbar UI

#### Positioning Strategy
```css
/* editor-bundle.css */
.editor-toolbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* Sticky toolbar variant */
@supports (position: sticky) {
  .editor-toolbar {
    position: sticky;
    top: 0;
  }
}

/* Mobile optimization */
@media (max-width: 768px) {
  .editor-toolbar {
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  
  .editor-toolbar button {
    flex: 1 1 auto;
    font-size: 0.875rem;
  }
}
```

#### Accessible Toolbar
```html
<div class="editor-toolbar" role="toolbar" aria-label="Editor controls">
  <button type="button" onclick="gangEditor.publish()" 
          aria-label="Publish changes">
    📤 Publish
  </button>
  
  <button type="button" onclick="gangEditor.saveDraft()"
          aria-label="Save draft">
    💾 Save Draft
  </button>
  
  <button type="button" onclick="gangEditor.validateHeadings()"
          aria-label="Check heading structure">
    ✓ Check Headings
  </button>
  
  <button type="button" onclick="gangEditor.showRenameSlug()"
          aria-label="Rename page slug">
    🔄 Rename Slug
  </button>
  
  <button type="button" onclick="gangEditor.cancel()"
          aria-label="Cancel editing" class="btn-cancel">
    ❌ Cancel
  </button>
</div>
```

### 7. Build & Deploy Flow

#### Current Flow
```
1. Edit in /studio
2. Click "Publish" → Save to disk
3. Manual: Run `gang build` in terminal
4. Manual: Commit & push
5. GitHub Actions → Build → Deploy
```

#### New In-Place Flow
```
1. Visit /pages/manifesto
2. Click "Edit" → In-place editor activates
3. Edit content → Click "Publish"
4. Backend:
   a. Save markdown to disk
   b. Validate (headings, contracts)
   c. Git commit & push
   d. Trigger GitHub Actions
5. GitHub Actions → Build → Deploy
6. Page reloads with new content
```

#### Auto-Deploy Implementation
```python
# apps/studio/backend/routes/content.py
@app.route('/api/content/<path:file_path>', methods=['PUT'])
@require_auth
def save_content(file_path):
    # Save markdown
    content = request.get_data(as_text=True)
    full_path = Path('content') / file_path
    full_path.write_text(content)
    
    # Auto-commit (if enabled in config)
    if config.get('auto_deploy', False):
        subprocess.run(['git', 'add', str(full_path)])
        subprocess.run(['git', 'commit', '-m', f'Update {file_path}'])
        subprocess.run(['git', 'push', 'origin', 'main'])
        
        return jsonify({
            'status': 'saved',
            'deploying': True,
            'message': 'Content saved and deployment triggered'
        })
    
    return jsonify({
        'status': 'saved',
        'deploying': False,
        'message': 'Content saved. Manual deploy required.'
    })
```

### 8. Template Integration

#### Updated `base.html`
```html
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
  <!-- ... existing head ... -->
  
  {% if user_authenticated %}
  <!-- Editor resources (only for authenticated users) -->
  <link rel="preload" href="/assets/editor-bundle.js" as="script">
  <link rel="stylesheet" href="/assets/editor-bundle.css">
  {% endif %}
</head>
<body data-page-type="{{ page_type }}" 
      data-category="{{ category }}" 
      data-slug="{{ slug }}">
  
  {% if user_authenticated %}
  <!-- Edit trigger button -->
  <button class="edit-trigger" 
          onclick="activateEditor()" 
          aria-label="Edit this page"
          style="position: fixed; bottom: 2rem; right: 2rem; z-index: 999;">
    ✏️ Edit
  </button>
  {% endif %}

  <!-- ... existing header/nav ... -->
  
  <main role="main" id="editable-content">
    {% block content %}{% endblock %}
  </main>

  <!-- ... existing footer ... -->

  {% if user_authenticated %}
  <!-- Editor script (lazy loaded) -->
  <script src="/assets/editor-bundle.js" defer></script>
  {% endif %}
</body>
</html>
```

### 9. Migration Path

#### Phase 1: Parallel Operation (Week 1-2)
- ✅ Keep existing `/studio` functional
- ✅ Build in-place editor as opt-in feature
- ✅ Test with single content type (e.g., pages)
- ✅ Verify auth, validation, deploy flow

#### Phase 2: Feature Parity (Week 3-4)
- ✅ Port all studio features to in-place editor:
  - Heading validation
  - Slug renaming
  - Redirect management
  - Product sync
- ✅ Add keyboard shortcuts (Cmd+S to save, etc.)
- ✅ Mobile-optimized toolbar

#### Phase 3: Full Migration (Week 5-6)
- ✅ Make in-place editor default
- ✅ Add "Edit" buttons to all content pages
- ✅ Deprecate `/studio` route
- ✅ Update documentation

#### Phase 4: Enhancement (Week 7+)
- ✅ Auto-save drafts to localStorage
- ✅ Real-time preview without leaving page
- ✅ Collaborative editing indicators
- ✅ Undo/redo history
- ✅ AI writing assistance inline

### 10. Technical Decisions

#### Editor Library
**Choice**: Stick with ToastUI Editor
- ✅ Already integrated
- ✅ WYSIWYG + Markdown modes
- ✅ Lightweight (~200KB gzipped)
- ✅ Accessible toolbar
- ❌ Alternative: TipTap (more modern, but requires rebuild)

#### Auth Strategy
**Choice**: Cloudflare Access (Zero Trust)
- ✅ No backend auth code needed
- ✅ Email/GitHub/Google providers
- ✅ Works with static site
- ✅ Free tier available
- ❌ Alternative: Custom JWT (more complex)

#### Deploy Trigger
**Choice**: Git commit + push (triggers GitHub Actions)
- ✅ Uses existing CI/CD pipeline
- ✅ Full validation (Lighthouse, axe, contracts)
- ✅ Git history preserved
- ❌ Alternative: Direct build API (faster, but bypasses checks)

#### State Management
**Choice**: No framework, vanilla JS
- ✅ Lightweight
- ✅ No build step
- ✅ Direct DOM manipulation
- ❌ Alternative: Vue/React (overkill for simple editor)

### 11. User Experience

#### Edit Mode Entry
1. **Authenticated user visits `/pages/manifesto`**
2. **Sees floating "✏️ Edit" button** (bottom-right corner)
3. **Clicks "Edit"**:
   - Page dims slightly
   - Loading spinner appears
   - Markdown fetched from API
   - Editor replaces main content
   - Toolbar slides in from top
4. **Editor ready** - user can now edit

#### Editing Experience
- **WYSIWYG mode by default** (formatted text)
- **Toggle to Markdown** (raw syntax) via toolbar
- **Auto-save indicator** (debounced, saves to localStorage)
- **Validation on demand** (click "Check Headings")
- **Preview changes** (without leaving editor)

#### Publishing Flow
1. **Click "📤 Publish"**
2. **Validation runs**:
   - ✅ Heading structure (WCAG)
   - ✅ Contract compliance
   - ✅ Link integrity
3. **If valid**:
   - Content saved to git
   - Commit created
   - Push to GitHub
   - Deploy triggered
   - Success message: "✅ Published! Deploying..."
4. **If invalid**:
   - Error modal shows issues
   - Option to "Publish Anyway" or "Fix Issues"

#### Exit Edit Mode
- **Click "❌ Cancel"** → Confirms discard → Restores original HTML
- **Click "💾 Save Draft"** → Saves locally → Can resume later
- **Publish success** → Auto-reload page with new content

### 12. Accessibility Considerations

✅ **Keyboard Navigation**
- Edit trigger: `Tab` to focus, `Enter` to activate
- Toolbar: Arrow keys to navigate buttons
- Editor: Standard text editing shortcuts
- Exit: `Esc` to cancel (with confirmation)

✅ **Screen Reader Support**
- Edit trigger announced: "Edit this page, button"
- Editor mode announced: "Editing mode active, WYSIWYG editor"
- Toolbar buttons have `aria-label`
- Validation errors read aloud

✅ **Focus Management**
- On edit mode entry: Focus moves to editor
- On validation error: Focus moves to error list
- On cancel: Focus returns to edit trigger

✅ **Color Contrast**
- Toolbar meets WCAG AA (4.5:1)
- Error messages use semantic colors + icons
- Success states visible without color alone

### 13. Performance Budget

**Editor Bundle Size**:
- ToastUI Editor: ~200KB (gzipped)
- Custom editor code: ~15KB
- Total: ~215KB (acceptable for opt-in feature)

**Load Strategy**:
- ❌ Don't bundle with main site JS
- ✅ Load only when user is authenticated
- ✅ Use `defer` to avoid blocking render
- ✅ Preload on authenticated pages

**Runtime Performance**:
- Editor init: <500ms
- Markdown fetch: <200ms (local API)
- Save operation: <100ms
- Full publish cycle: 30-60s (GitHub Actions)

### 14. Security Considerations

🔒 **Authentication**
- All `/api/*` routes require auth token
- Token verified on every request
- Session expires after 24 hours

🔒 **Authorization**
- Only allow editing of content in `content/` directory
- Block access to config files, templates, scripts
- Validate file paths (prevent `../` traversal)

🔒 **Content Validation**
- Sanitize user input (prevent XSS in markdown)
- Validate frontmatter schema
- Check file size limits (max 1MB per file)

🔒 **Git Operations**
- Sign commits with GPG key
- Verify remote before push
- Handle merge conflicts gracefully

### 15. Implementation Checklist

#### Backend Setup
- [ ] Add authentication middleware
- [ ] Create `/api/auth/status` endpoint
- [ ] Add `/api/build` trigger endpoint
- [ ] Implement auto-commit on save (optional)
- [ ] Add git signing for commits

#### Frontend Bundle
- [ ] Create `editor-bundle.js` with InPlaceEditor class
- [ ] Add `editor-bundle.css` with toolbar styles
- [ ] Bundle ToastUI Editor (or use CDN)
- [ ] Implement validation UI (modal/inline)
- [ ] Add keyboard shortcuts

#### Template Updates
- [ ] Update `base.html` with edit trigger
- [ ] Add auth check in template context
- [ ] Pass `category` and `slug` to template
- [ ] Conditionally load editor resources

#### Testing
- [ ] Test edit mode activation
- [ ] Test WYSIWYG ↔ Markdown toggle
- [ ] Test heading validation flow
- [ ] Test publish → deploy cycle
- [ ] Test on mobile devices
- [ ] Test with screen reader

#### Documentation
- [ ] Update README with in-place editor docs
- [ ] Create video demo
- [ ] Document auth setup
- [ ] Update deployment guide

## Next Steps

1. **Prototype** - Build minimal viable in-place editor (1-2 days)
2. **Auth Setup** - Configure Cloudflare Access or GitHub OAuth (1 day)
3. **Feature Port** - Migrate studio features to in-place UI (3-5 days)
4. **Testing** - Comprehensive testing across devices/browsers (2 days)
5. **Deploy** - Roll out to production with feature flag (1 day)
6. **Iterate** - Gather feedback and refine UX (ongoing)

## Success Metrics

- ✅ **Edit mode activates in <500ms** (perceived instant)
- ✅ **Publish cycle completes in <60s** (includes deploy)
- ✅ **Zero WCAG violations** in editor UI
- ✅ **Mobile editing works smoothly** (responsive toolbar)
- ✅ **100% feature parity** with studio
- ✅ **Positive user feedback** ("way better than /studio!")

---

**Implementation Target**: 2-3 weeks for full migration  
**Effort Level**: Medium (reuses existing APIs, adds thin UI layer)  
**Risk Level**: Low (can run parallel to existing studio)



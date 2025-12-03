# In-Place Editor Quick Start Guide

## Overview
This guide shows how to implement the in-place editor with minimal changes to the existing codebase.

## Architecture at a Glance

```
User visits /pages/manifesto
         ↓
Page loads with "Edit" button (if authenticated)
         ↓
User clicks "Edit"
         ↓
JavaScript loads editor bundle
         ↓
Fetches markdown from /api/content/pages/manifesto
         ↓
Replaces <main> with ToastUI Editor
         ↓
User edits → Clicks "Publish"
         ↓
Validates → Saves → Commits → Pushes → Deploys
         ↓
Page reloads with new content
```

## Step 1: Add Edit Trigger to Templates

### `templates/base.html`
```html
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
    <!-- ... existing head ... -->
    
    {% if user_authenticated %}
    <link rel="preload" href="/assets/editor.css" as="style">
    <link rel="stylesheet" href="/assets/editor.css">
    {% endif %}
</head>
<body data-page-type="{{ page_type }}" 
      data-category="{{ category }}" 
      data-slug="{{ slug }}">
    
    {% if user_authenticated %}
    <!-- Floating edit button -->
    <button id="edit-trigger" class="edit-btn" onclick="activateEditor()">
        ✏️ Edit
    </button>
    {% endif %}

    <header role="banner">
        <!-- ... existing header ... -->
    </header>
    
    <main role="main" id="content">
        {% block content %}{% endblock %}
    </main>

    <footer>
        <!-- ... existing footer ... -->
    </footer>

    {% if user_authenticated %}
    <script src="/assets/editor-bundle.js" defer></script>
    {% endif %}
</body>
</html>
```

### Pass context variables in build script

**`cli/gang/cli.py`** (update template context):
```python
# Around line 2350 where templates are rendered
context = {
    'title': frontmatter.get('title', 'Untitled'),
    'description': frontmatter.get('description', ''),
    'content': content_html,
    'site_title': config['site']['title'],
    'lang': frontmatter.get('lang', 'en'),
    'year': datetime.now().year,
    
    # NEW: Add these for in-place editor
    'page_type': content_type,  # 'page', 'post', 'project'
    'category': content_type + 's',  # 'pages', 'posts', 'projects'
    'slug': slug,
    'user_authenticated': os.environ.get('EDITOR_MODE') == 'true',  # Set via env var
    
    # ... rest of context
}
```

## Step 2: Create Editor Bundle

### `public/editor-bundle.js`
```javascript
/**
 * In-Place Editor for GANG Platform
 * Replaces page content with ToastUI Editor
 */

class InPlaceEditor {
    constructor() {
        this.editor = null;
        this.originalContent = null;
        this.isEditing = false;
    }

    async activate() {
        if (this.isEditing) return;
        
        // Get page metadata from body attributes
        const { category, slug } = document.body.dataset;
        
        // Store original HTML for restore
        this.originalContent = document.querySelector('#content').innerHTML;
        
        // Show loading state
        this.showLoading();
        
        try {
            // Fetch markdown source from API
            const response = await fetch(`/api/content/${category}/${slug}`);
            if (!response.ok) throw new Error('Failed to load content');
            
            const markdown = await response.text();
            
            // Initialize editor
            this.initEditor(markdown);
            
            // Show toolbar
            this.showToolbar();
            
            this.isEditing = true;
            
            // Hide edit trigger
            document.getElementById('edit-trigger').style.display = 'none';
            
        } catch (error) {
            console.error('Editor activation failed:', error);
            alert('Failed to activate editor. Please try again.');
            this.restore();
        }
    }

    initEditor(markdown) {
        // Clear main content area
        const main = document.querySelector('#content');
        main.innerHTML = '<div id="editor-root"></div>';
        
        // Initialize ToastUI Editor
        const { Editor } = toastui;
        
        this.editor = new Editor({
            el: document.querySelector('#editor-root'),
            height: '80vh',
            initialEditType: 'wysiwyg',
            initialValue: markdown,
            previewStyle: 'vertical',
            usageStatistics: false,
            toolbarItems: [
                ['heading', 'bold', 'italic', 'strike'],
                ['hr', 'quote'],
                ['ul', 'ol', 'task', 'indent', 'outdent'],
                ['table', 'link', 'image'],
                ['code', 'codeblock'],
            ],
        });
    }

    showToolbar() {
        // Create floating toolbar if it doesn't exist
        if (!document.getElementById('editor-toolbar')) {
            const toolbar = document.createElement('div');
            toolbar.id = 'editor-toolbar';
            toolbar.className = 'editor-toolbar';
            toolbar.setAttribute('role', 'toolbar');
            toolbar.setAttribute('aria-label', 'Editor controls');
            toolbar.innerHTML = `
                <button onclick="gangEditor.publish()" class="btn-primary">
                    📤 Publish
                </button>
                <button onclick="gangEditor.saveDraft()" class="btn-secondary">
                    💾 Save Draft
                </button>
                <button onclick="gangEditor.validateHeadings()" class="btn-secondary">
                    ✓ Check Headings
                </button>
                <button onclick="gangEditor.cancel()" class="btn-cancel">
                    ❌ Cancel
                </button>
            `;
            document.body.appendChild(toolbar);
        }
        
        document.getElementById('editor-toolbar').style.display = 'flex';
    }

    hideToolbar() {
        const toolbar = document.getElementById('editor-toolbar');
        if (toolbar) {
            toolbar.style.display = 'none';
        }
    }

    async validateHeadings() {
        const markdown = this.editor.getMarkdown();
        
        try {
            const response = await fetch('/api/validate-headings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: markdown })
            });
            
            const result = await response.json();
            
            if (result.valid) {
                this.showNotification('✅ Heading structure is valid!', 'success');
            } else {
                this.showValidationModal(result);
            }
            
            return result.valid;
        } catch (error) {
            console.error('Validation failed:', error);
            alert('Validation failed. Please try again.');
            return false;
        }
    }

    showValidationModal(result) {
        const modal = document.createElement('div');
        modal.className = 'validation-modal';
        modal.innerHTML = `
            <div class="modal-overlay" onclick="this.parentElement.remove()"></div>
            <div class="modal-content">
                <h2>❌ Heading Validation Failed</h2>
                <div class="errors">
                    <strong>Errors:</strong>
                    <ul>
                        ${result.errors.map(e => `<li>${e}</li>`).join('')}
                    </ul>
                </div>
                ${result.suggestions ? `
                    <div class="suggestions">
                        <strong>How to fix:</strong>
                        <ul>
                            ${result.suggestions.map(s => `<li>${s}</li>`).join('')}
                        </ul>
                    </div>
                ` : ''}
                <div class="modal-actions">
                    <button onclick="this.closest('.validation-modal').remove()" class="btn-secondary">
                        Fix Issues
                    </button>
                    <button onclick="gangEditor.forcePublish()" class="btn-warning">
                        Publish Anyway
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    async publish() {
        // Validate first
        const valid = await this.validateHeadings();
        if (!valid) {
            return; // Modal will show with publish anyway option
        }
        
        await this.saveAndDeploy();
    }

    async forcePublish() {
        if (confirm('Publishing with heading errors may impact accessibility and SEO. Continue?')) {
            // Close validation modal
            document.querySelector('.validation-modal')?.remove();
            await this.saveAndDeploy();
        }
    }

    async saveAndDeploy() {
        const markdown = this.editor.getMarkdown();
        const { category, slug } = document.body.dataset;
        
        try {
            // Show saving indicator
            this.showNotification('💾 Saving...', 'info');
            
            // Save content
            const response = await fetch(`/api/content/${category}/${slug}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'text/plain' },
                body: markdown
            });
            
            if (!response.ok) throw new Error('Save failed');
            
            const result = await response.json();
            
            if (result.deploying) {
                this.showNotification('✅ Saved! Deploying...', 'success');
                
                // Wait for deploy (poll status or wait fixed time)
                setTimeout(() => {
                    location.reload();
                }, 3000);
            } else {
                this.showNotification('✅ Saved! Run "gang build" to deploy.', 'success');
            }
            
        } catch (error) {
            console.error('Save failed:', error);
            alert('Failed to save. Please try again.');
        }
    }

    async saveDraft() {
        const markdown = this.editor.getMarkdown();
        const { category, slug } = document.body.dataset;
        const key = `draft_${category}_${slug}`;
        
        // Save to localStorage
        localStorage.setItem(key, JSON.stringify({
            markdown,
            timestamp: Date.now()
        }));
        
        this.showNotification('💾 Draft saved locally', 'info');
    }

    loadDraft() {
        const { category, slug } = document.body.dataset;
        const key = `draft_${category}_${slug}`;
        const draft = localStorage.getItem(key);
        
        if (draft) {
            const { markdown, timestamp } = JSON.parse(draft);
            const age = Math.floor((Date.now() - timestamp) / 1000 / 60);
            
            if (confirm(`Load draft from ${age} minutes ago?`)) {
                this.editor.setMarkdown(markdown);
                this.showNotification('📝 Draft loaded', 'info');
            }
        }
    }

    cancel() {
        if (confirm('Discard changes?')) {
            this.restore();
        }
    }

    restore() {
        // Destroy editor
        if (this.editor) {
            this.editor.destroy();
            this.editor = null;
        }
        
        // Restore original content
        if (this.originalContent) {
            document.querySelector('#content').innerHTML = this.originalContent;
        }
        
        // Hide toolbar
        this.hideToolbar();
        
        // Show edit trigger
        const trigger = document.getElementById('edit-trigger');
        if (trigger) trigger.style.display = 'block';
        
        this.isEditing = false;
    }

    showLoading() {
        const main = document.querySelector('#content');
        main.innerHTML = '<div class="loading">Loading editor...</div>';
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => notification.remove(), 3000);
    }
}

// Initialize global editor instance
window.gangEditor = new InPlaceEditor();

// Expose activation function
window.activateEditor = () => window.gangEditor.activate();

// Auto-load ToastUI Editor from CDN
if (typeof toastui === 'undefined') {
    const script = document.createElement('script');
    script.src = 'https://uicdn.toast.com/editor/latest/toastui-editor-all.min.js';
    script.onload = () => console.log('ToastUI Editor loaded');
    document.head.appendChild(script);
    
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://uicdn.toast.com/editor/latest/toastui-editor.min.css';
    document.head.appendChild(link);
}
```

### `public/editor.css`
```css
/**
 * In-Place Editor Styles
 */

/* Edit trigger button */
.edit-btn {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    z-index: 999;
    
    padding: 0.75rem 1.25rem;
    
    background: #0066cc;
    color: white;
    border: none;
    border-radius: 8px;
    
    font-size: 1rem;
    font-weight: 500;
    
    cursor: pointer;
    
    box-shadow: 0 4px 12px rgba(0, 102, 204, 0.3);
    transition: all 0.2s ease;
}

.edit-btn:hover {
    background: #0052a3;
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0, 102, 204, 0.4);
}

.edit-btn:active {
    transform: translateY(0);
}

/* Floating toolbar */
.editor-toolbar {
    position: sticky;
    top: 0;
    z-index: 1000;
    
    display: none; /* Hidden by default */
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid #e0e0e0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.editor-toolbar button {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background: #0066cc;
    color: white;
}

.btn-primary:hover {
    background: #0052a3;
}

.btn-secondary {
    background: white;
    color: #333;
    border: 1px solid #e0e0e0;
}

.btn-secondary:hover {
    background: #f5f5f5;
}

.btn-cancel {
    background: #ff4444;
    color: white;
    margin-left: auto;
}

.btn-cancel:hover {
    background: #cc0000;
}

.btn-warning {
    background: #ff9800;
    color: white;
}

.btn-warning:hover {
    background: #e68900;
}

/* Validation modal */
.validation-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 2000;
}

.modal-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
}

.modal-content {
    position: relative;
    max-width: 600px;
    margin: 10vh auto;
    padding: 2rem;
    background: white;
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
}

.modal-content h2 {
    margin-bottom: 1rem;
    color: #d32f2f;
}

.errors {
    background: #ffebee;
    border: 1px solid #ef5350;
    padding: 1rem;
    border-radius: 4px;
    margin-bottom: 1rem;
}

.suggestions {
    background: #fff3e0;
    border: 1px solid #ff9800;
    padding: 1rem;
    border-radius: 4px;
    margin-bottom: 1rem;
}

.modal-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    margin-top: 1.5rem;
}

/* Notifications */
.notification {
    position: fixed;
    top: 1rem;
    right: 1rem;
    z-index: 3000;
    
    padding: 1rem 1.5rem;
    border-radius: 4px;
    
    font-size: 0.9rem;
    font-weight: 500;
    
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.notification-success {
    background: #4caf50;
    color: white;
}

.notification-info {
    background: #2196f3;
    color: white;
}

.notification-error {
    background: #f44336;
    color: white;
}

/* Loading state */
.loading {
    padding: 4rem;
    text-align: center;
    color: #999;
    font-size: 1.1rem;
}

/* Editor container adjustments */
#editor-root {
    margin: 2rem auto;
    max-width: 1200px;
}

/* Mobile responsive */
@media (max-width: 768px) {
    .edit-btn {
        bottom: 1rem;
        right: 1rem;
        padding: 0.5rem 1rem;
        font-size: 0.9rem;
    }
    
    .editor-toolbar {
        flex-wrap: wrap;
    }
    
    .editor-toolbar button {
        flex: 1 1 auto;
        font-size: 0.85rem;
    }
    
    .modal-content {
        margin: 5vh 1rem;
    }
}
```

## Step 3: Backend API (Existing Studio APIs)

The backend APIs are already implemented in the studio. We just need to make sure they're available:

### Required Endpoints

1. **GET `/api/content/{category}/{slug}`** - Fetch markdown source
2. **PUT `/api/content/{category}/{slug}`** - Save edited content
3. **POST `/api/validate-headings`** - Validate heading structure
4. **POST `/api/build`** - Trigger deployment (new)

### Add Build Trigger (New)

**`apps/studio/backend/routes/build.py`** (create if doesn't exist):
```python
from flask import jsonify
import subprocess
import os

@app.route('/api/build', methods=['POST'])
def trigger_build():
    """Commit changes and trigger GitHub Actions deploy"""
    
    try:
        # Add all content changes
        subprocess.run(['git', 'add', 'content/'], check=True)
        
        # Commit
        subprocess.run([
            'git', 'commit', 
            '-m', 'Content update via in-place editor'
        ], check=True)
        
        # Push to trigger GitHub Actions
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        
        return jsonify({
            'status': 'building',
            'deploying': True,
            'message': 'Deployment triggered'
        })
        
    except subprocess.CalledProcessError as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
```

## Step 4: Enable Editor Mode

### Option 1: Environment Variable
```bash
# .env
EDITOR_MODE=true
```

Then in build script:
```python
user_authenticated = os.environ.get('EDITOR_MODE') == 'true'
```

### Option 2: Check for Studio Server
```python
# In template context
import requests

def is_editor_available():
    try:
        response = requests.get('http://localhost:5001/api/auth/status', timeout=0.5)
        return response.status_code == 200
    except:
        return False

# In build
user_authenticated = is_editor_available()
```

### Option 3: Cloudflare Access Header
```python
# Check for Cloudflare Access header
user_authenticated = request.headers.get('CF-Access-Authenticated-User-Email') is not None
```

## Step 5: Test It!

### Local Testing

1. **Start studio backend** (if not already running):
```bash
cd apps/studio/backend
python app.py
```

2. **Build site with editor enabled**:
```bash
export EDITOR_MODE=true
gang build
```

3. **Serve locally**:
```bash
python -m http.server 8000 --directory dist
```

4. **Visit page**:
```
http://localhost:8000/pages/manifesto/
```

5. **Should see "✏️ Edit" button** - click it to activate editor!

### Expected Behavior

✅ Edit button appears in bottom-right  
✅ Clicking loads ToastUI Editor  
✅ Original content replaced with editable markdown  
✅ Toolbar appears at top  
✅ Can edit in WYSIWYG or Markdown mode  
✅ "Check Headings" validates structure  
✅ "Publish" saves + triggers deploy  
✅ "Cancel" restores original view  

## Step 6: Deploy to Production

### 1. Push Changes
```bash
git add .
git commit -m "Add in-place editor"
git push origin main
```

### 2. Set Up Authentication

#### Cloudflare Access (Recommended)
1. Go to Cloudflare Zero Trust dashboard
2. Create Access Application:
   - Name: "GANG Editor"
   - Domain: `yourdomain.com`
   - Path: `/api/*`
3. Add Policy:
   - Rule: Email equals `your@email.com`
4. Save

Now `/api/*` routes require authentication automatically!

### 3. Enable Auto-Deploy

In studio backend config:
```python
# config.py
AUTO_DEPLOY = True  # Triggers git push on save
```

Or keep manual and run `gang build` from terminal.

## Troubleshooting

### Editor doesn't load
- Check browser console for errors
- Verify ToastUI CDN is accessible
- Confirm `/api/content/*` endpoints respond

### Publish doesn't deploy
- Check GitHub Actions status
- Verify git credentials are set
- Confirm push permissions

### Mobile issues
- Test responsive toolbar
- Check touch event handling
- Verify virtual keyboard doesn't hide controls

## Next Steps

1. ✅ Add keyboard shortcuts (Cmd+S to save)
2. ✅ Implement auto-save to localStorage
3. ✅ Add slug rename modal
4. ✅ Add redirect management UI
5. ✅ Port product sync to in-place UI
6. ✅ Add collaborative indicators
7. ✅ Build AI writing assistant

---

**Result**: You now have a fully functional in-place editor that feels like a native part of the website, not a separate tool! 🎉



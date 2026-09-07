// GANG In-Place Editor - Notion-style contenteditable editor
// No third-party dependencies - pure vanilla JavaScript

class InPlaceEditor {
    constructor() {
        this.overlay = null;
        this.editorElement = null;
        this.originalContent = '';
        this.preservedFrontmatter = null;
        this.currentFile = '';
        this.floatingToolbar = null;
        this.isActive = false;
    }

    async activate() {
        if (this.isActive) return;
        
        this.isActive = true;
        this.currentFile = this.getCurrentFilePath();
        
        try {
            // Fetch content from API
            const response = await fetch(`http://localhost:5001/api/content/${this.currentFile}`);
            if (!response.ok) {
                throw new Error('Failed to load content: ' + response.status);
            }
            
            this.originalContent = await response.text();
            const split = this.splitFrontmatter(this.originalContent);
            this.preservedFrontmatter = split.frontmatter;
            this.bodyContent = split.body;
            
            // Create and show editor overlay
            this.createOverlay();
            this.showNotification('Editor loaded', 'info');
            
        } catch (error) {
            console.error('Editor activation failed:', error);
            this.showNotification('Failed to load content: ' + error.message, 'error');
            this.isActive = false;
        }
    }

    createOverlay() {
        // Create full-screen overlay
        const overlay = document.createElement('div');
        overlay.className = 'editor-overlay';
        overlay.innerHTML = `
            <div class="editor-container">
                <div class="editor-header">
                    <h2></h2>
                    <div class="editor-header-actions">
                        <button class="editor-actions-btn" id="actions-toggle">
                            <i class="fa-solid fa-bars"></i> Actions
                        </button>
                        <div class="action-menu" id="action-menu">
                            <button data-action="save">
                                <i class="fa-solid fa-floppy-disk"></i> Save Draft
                            </button>
                            <button data-action="validate">
                                <i class="fa-solid fa-check"></i> Validate
                            </button>
                            <button data-action="publish">
                                <i class="fa-solid fa-rocket"></i> Publish
                            </button>
                            <button data-action="cancel">
                                <i class="fa-solid fa-xmark"></i> Cancel
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        const titleEl = overlay.querySelector('h2');
        if (titleEl) {
            titleEl.textContent = 'Edit: ' + this.getPageTitle();
        }
        
        // Create editor content area
        const container = overlay.querySelector('.editor-container');
        this.editorElement = this.initEditor();
        container.appendChild(this.editorElement);
        
        // Setup action menu
        this.setupActionMenu(overlay);
        
        // Add to page
        document.body.appendChild(overlay);
        this.overlay = overlay;
        
        // Focus editor
        this.editorElement.focus();
    }

    initEditor() {
        const editor = document.createElement('div');
        editor.className = 'editor-content';
        editor.contentEditable = 'true';
        editor.setAttribute('data-placeholder', 'Start writing...');
        editor.innerHTML = this.markdownToHtml(this.bodyContent || this.originalContent);
        
        // Keyboard shortcuts
        editor.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                this.saveContent();
            }
            if (e.key === 'Escape') {
                this.cancel();
            }
        });

        editor.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData('text/plain');
            document.execCommand('insertText', false, text || '');
        });
        
        // Show floating toolbar on selection
        editor.addEventListener('mouseup', () => this.handleSelection());
        editor.addEventListener('keyup', () => this.handleSelection());
        
        return editor;
    }

    setupActionMenu(overlay) {
        const actionsBtn = overlay.querySelector('#actions-toggle');
        const actionMenu = overlay.querySelector('#action-menu');
        
        actionsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            actionMenu.classList.toggle('show');
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', () => {
            actionMenu.classList.remove('show');
        });
        
        // Handle menu item clicks
        actionMenu.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                actionMenu.classList.remove('show');
                
                if (action === 'save') this.saveContent();
                if (action === 'validate') this.validateContent();
                if (action === 'publish') this.publishContent();
                if (action === 'cancel') this.cancel();
            });
        });
    }

    handleSelection() {
        const selection = window.getSelection();
        const selectedText = selection.toString().trim();
        
        if (selectedText.length > 0) {
            this.showFloatingToolbar(selection);
        } else {
            this.hideFloatingToolbar();
        }
    }

    showFloatingToolbar(selection) {
        if (!this.floatingToolbar) {
            this.createFloatingToolbar();
        }
        
        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        this.floatingToolbar.style.display = 'flex';
        this.floatingToolbar.style.left = rect.left + (rect.width / 2) - 150 + 'px';
        this.floatingToolbar.style.top = rect.top - 50 + window.scrollY + 'px';
    }

    hideFloatingToolbar() {
        if (this.floatingToolbar) {
            this.floatingToolbar.style.display = 'none';
        }
    }

    createFloatingToolbar() {
        const toolbar = document.createElement('div');
        toolbar.className = 'floating-toolbar';
        toolbar.innerHTML = `
            <button data-cmd="bold" title="Bold (Cmd+B)">
                <i class="fa-solid fa-bold"></i>
            </button>
            <button data-cmd="italic" title="Italic (Cmd+I)">
                <i class="fa-solid fa-italic"></i>
            </button>
            <button data-cmd="heading" title="Heading">
                <i class="fa-solid fa-heading"></i>
            </button>
            <button data-cmd="link" title="Insert Link">
                <i class="fa-solid fa-link"></i>
            </button>
            <button data-cmd="code" title="Code">
                <i class="fa-solid fa-code"></i>
            </button>
        `;
        
        // Add click handlers
        toolbar.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('mousedown', (e) => {
                e.preventDefault(); // Prevent losing selection
                const cmd = btn.dataset.cmd;
                this.applyFormat(cmd);
            });
        });
        
        document.body.appendChild(toolbar);
        this.floatingToolbar = toolbar;
    }

    applyFormat(cmd) {
        if (cmd === 'bold') {
            document.execCommand('bold', false, null);
        } else if (cmd === 'italic') {
            document.execCommand('italic', false, null);
        } else if (cmd === 'heading') {
            document.execCommand('formatBlock', false, '<h2>');
        } else if (cmd === 'code') {
            document.execCommand('formatBlock', false, '<code>');
        } else if (cmd === 'link') {
            const url = prompt('Enter URL:');
            if (url && this.isSafeHref(url)) {
                document.execCommand('createLink', false, url);
            }
        }
        
        this.hideFloatingToolbar();
    }

    escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    splitFrontmatter(markdown) {
        const match = String(markdown || '').match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
        if (!match) {
            return { frontmatter: null, body: markdown || '' };
        }
        return { frontmatter: match[1], body: match[2] };
    }

    joinFrontmatter(body) {
        if (this.preservedFrontmatter == null) {
            return body;
        }
        return '---\n' + this.preservedFrontmatter + '\n---\n' + (body || '');
    }

    decodeHrefEntities(value) {
        let current = String(value);
        for (let i = 0; i < 3; i++) {
            const next = current
                .replace(/&amp;/gi, '&')
                .replace(/&colon;/gi, ':')
                .replace(/&#0*58;/gi, ':')
                .replace(/&#x0*3a;/gi, ':');
            if (next === current) break;
            current = next;
        }
        return current;
    }

    isSafeHref(value) {
        if (!value || typeof value !== 'string') return false;
        const self = this;
        function check(candidate) {
            const trimmed = String(candidate).trim();
            if (!trimmed) return false;
            const normalized = trimmed.replace(/\\/g, '/');
            if (trimmed.startsWith('//') || trimmed.startsWith('/\\') || trimmed.startsWith('\\') || normalized.startsWith('//')) {
                return false;
            }
            const pathPart = normalized.split('?')[0].split('#')[0];
            if (trimmed.indexOf('\0') !== -1 || /%00/i.test(trimmed)) {
                return false;
            }
            if (pathPart.indexOf(':') === -1) {
                return pathPart.split('/').every(function(seg) {
                    return seg !== '..' && seg.indexOf('..') !== 0;
                }) && pathPart.indexOf('//') === -1;
            }
            if (/^mailto:/i.test(trimmed)) {
                const addr = trimmed.slice(7).split('?')[0];
                return Boolean(addr) && addr.split('@')[0].indexOf(':') === -1;
            }
            if (!/^https?:\/\//i.test(trimmed)) {
                return false;
            }
            try {
                const url = new URL(trimmed);
                if (url.username) return false;
                return url.protocol === 'https:' || url.protocol === 'http:';
            } catch (err) {
                return false;
            }
        }
        const normalized = self.decodeHrefEntities(value);
        if (!check(normalized)) return false;
        let decoded = normalized;
        for (let i = 0; i < 3; i++) {
            try {
                const next = self.decodeHrefEntities(decodeURIComponent(decoded));
                if (next === decoded) break;
                decoded = next;
                if (!check(decoded)) return false;
            } catch (err) {
                break;
            }
        }
        return true;
    }

    // Markdown to HTML converter
    markdownToHtml(markdown) {
        const self = this;
        const text = this.escapeHtml(markdown);
        return text
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h2>$1</h2>')
            .replace(/^# (.+)$/gm, '<h1>$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/\[(.+?)\]\((.+?)\)/g, function(_, label, href) {
                const rawHref = String(href).replace(/&amp;/g, '&');
                const url = self.isSafeHref(rawHref) ? rawHref : '#';
                return '<a href="' + self.escapeHtml(url) + '">' + label + '</a>';
            })
            .replace(/`(.+?)`/g, '<code>$1</code>')
            .split('\n\n').map(function(p) { return '<p>' + p + '</p>'; }).join('');
    }

    // HTML to Markdown converter
    htmlToMarkdown(html) {
        const parsed = new DOMParser().parseFromString(
            '<div id="gang-md-root">' + (html || '') + '</div>',
            'text/html'
        );
        const temp = parsed.getElementById('gang-md-root') || parsed.body;
        const self = this;
        temp.querySelectorAll('script, style, iframe, object, embed, form').forEach(function(node) {
            node.remove();
        });
        temp.querySelectorAll('*').forEach(function(node) {
            Array.from(node.attributes).forEach(function(attr) {
                const name = attr.name.toLowerCase();
                if (name.indexOf('on') === 0) {
                    node.removeAttribute(attr.name);
                    return;
                }
                if (['href', 'src', 'srcset', 'action', 'formaction', 'poster', 'xlink:href'].indexOf(name) !== -1) {
                    if (!self.isSafeHref(attr.value)) {
                        node.setAttribute(attr.name, '#');
                    }
                }
            });
        });
        
        return temp.innerHTML
            .replace(/<h1>(.+?)<\/h1>/g, '# $1\n\n')
            .replace(/<h2>(.+?)<\/h2>/g, '## $1\n\n')
            .replace(/<h3>(.+?)<\/h3>/g, '### $1\n\n')
            .replace(/<strong>(.+?)<\/strong>/g, '**$1**')
            .replace(/<em>(.+?)<\/em>/g, '*$1*')
            .replace(/<a href="(.+?)">(.+?)<\/a>/g, '[$2]($1)')
            .replace(/<code>(.+?)<\/code>/g, '`$1`')
            .replace(/<p>(.+?)<\/p>/g, '$1\n\n')
            .trim();
    }

    getContent() {
        return this.htmlToMarkdown(this.editorElement.innerHTML);
    }

    async saveContent() {
        try {
            const content = this.joinFrontmatter(this.getContent());
            
            const response = await fetch(`http://localhost:5001/api/content/${this.currentFile}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'text/plain',
                },
                body: content
            });
            
            if (!response.ok) {
                throw new Error('Failed to save content: ' + response.status);
            }
            
            this.showNotification('Content saved successfully', 'success');
            
        } catch (error) {
            console.error('Save failed:', error);
            this.showNotification('Failed to save: ' + error.message, 'error');
        }
    }

    async validateContent() {
        try {
            const content = this.getContent();
            
            const category = document.body.dataset.sourceCategory || document.body.dataset.category || '';
            const response = await fetch('http://localhost:5001/api/validate-headings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ content, category })
            });
            
            if (!response.ok) {
                throw new Error('Validation failed: ' + response.status);
            }
            
            const result = await response.json();
            
            if (result.valid) {
                this.showNotification('Content validation passed', 'success');
            } else {
                const details = (result.errors && result.errors.length)
                    ? result.errors.join(', ')
                    : (result.message || 'heading issues');
                this.showNotification('Validation failed: ' + details, 'error');
            }
            
        } catch (error) {
            console.error('Validation failed:', error);
            this.showNotification('Validation error: ' + error.message, 'error');
        }
    }

    async publishContent() {
        try {
            // First save the content
            await this.saveContent();
            
            // Then trigger build/deploy
            const buildResponse = await fetch('http://localhost:5001/api/build', { 
                method: 'POST' 
            });
            const buildResult = await buildResponse.json();
            
            if (buildResult.status === 'committed') {
                this.showNotification('Changes committed and site rebuilt! Page will reload in 3 seconds...', 'success');
                setTimeout(() => {
                    location.reload();
                }, 3000);
            } else {
                this.showNotification('Build completed: ' + buildResult.message, 'info');
            }
            
        } catch (error) {
            console.error('Publish failed:', error);
            this.showNotification('Publish failed: ' + error.message, 'error');
        }
    }

    cancel() {
        if (this.overlay) {
            this.overlay.remove();
            this.overlay = null;
        }
        
        if (this.floatingToolbar) {
            this.floatingToolbar.remove();
            this.floatingToolbar = null;
        }
        
        this.isActive = false;
        this.showNotification('Editor closed', 'info');
    }

    getCurrentFilePath() {
        const pageType = document.body.dataset.pageType || 'page';
        const category = document.body.dataset.sourceCategory || document.body.dataset.category || '';
        const slug = document.body.dataset.slug || '';
        
        if (category && slug) {
            return `${category}/${slug}`;
        }
        
        return 'unknown';
    }

    getPageTitle() {
        const h1 = document.querySelector('h1');
        return h1 ? h1.textContent : 'Untitled';
    }

    showNotification(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `editor-toast editor-toast-${type}`;
        toast.textContent = message;
        
        document.body.appendChild(toast);
        
        requestAnimationFrame(() => {
            toast.classList.add('editor-toast-show');
        });
        
        setTimeout(() => {
            toast.classList.remove('editor-toast-show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

// Initialize global editor instance
window.gangEditor = new InPlaceEditor();

// Expose activation function
window.activateEditor = () => window.gangEditor.activate();

// Add loading indicator to page
console.log('GANG In-Place Editor loaded');

// Ensure activateEditor is available immediately for onclick handlers
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log('DOM loaded, editor ready');
    });
} else {
    console.log('DOM already loaded, editor ready');
}
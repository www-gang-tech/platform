// GANG In-Place Editor — local body editing against the website vault.

class InPlaceEditor {
    constructor() {
        this.overlay = null;
        this.editorElement = null;
        this.originalBody = '';
        this.frontmatter = {};
        this.currentFile = '';
        this.revision = '';
        this.visualSafe = true;
        this.floatingToolbar = null;
        this.isActive = false;
        this.apiBase = 'http://127.0.0.1:5001';
    }

    async activate() {
        if (this.isActive) return;
        this.isActive = true;
        this.currentFile = this.getCurrentFilePath();

        try {
            const response = await fetch(`${this.apiBase}/api/content/${this.currentFile}`);
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || ('Failed to load content: ' + response.status));
            }

            this.originalBody = payload.body || '';
            this.frontmatter = payload.frontmatter || {};
            this.revision = payload.revision;
            this.visualSafe = payload.visual_safe !== false;
            this.createOverlay();
            this.showNotification('Editor loaded. Save writes the file only.', 'info');
        } catch (error) {
            console.error('Editor activation failed:', error);
            this.showNotification('Failed to load content: ' + error.message, 'error');
            this.isActive = false;
        }
    }

    createOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'editor-overlay';
        overlay.innerHTML = `
            <div class="editor-container">
                <div class="editor-header">
                    <h2>Edit: ${this.getPageTitle()}</h2>
                    <p class="editor-meta">Frontmatter is kept separate. Saving does not commit or deploy.</p>
                    <div class="editor-header-actions">
                        <button class="editor-actions-btn" id="actions-toggle">Actions</button>
                        <div class="action-menu" id="action-menu">
                            <button data-action="save">Save</button>
                            <button data-action="validate">Validate headings</button>
                            <button data-action="cancel">Cancel</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const container = overlay.querySelector('.editor-container');
        this.editorElement = this.initEditor();
        container.appendChild(this.editorElement);
        this.setupActionMenu(overlay);
        document.body.appendChild(overlay);
        this.overlay = overlay;
        this.editorElement.focus();
    }

    initEditor() {
        const editor = document.createElement(this.visualSafe ? 'div' : 'textarea');
        editor.className = 'editor-content';
        if (this.visualSafe) {
            editor.contentEditable = 'true';
            editor.setAttribute('data-placeholder', 'Start writing...');
            editor.innerHTML = this.markdownToHtml(this.originalBody);
            editor.addEventListener('mouseup', () => this.handleSelection());
            editor.addEventListener('keyup', () => this.handleSelection());
        } else {
            editor.value = this.originalBody;
            editor.setAttribute('aria-label', 'Markdown body');
        }

        editor.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                this.saveContent();
            }
            if (e.key === 'Escape') {
                this.cancel();
            }
        });
        return editor;
    }

    setupActionMenu(overlay) {
        const actionsBtn = overlay.querySelector('#actions-toggle');
        const actionMenu = overlay.querySelector('#action-menu');
        actionsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            actionMenu.classList.toggle('show');
        });
        document.addEventListener('click', () => actionMenu.classList.remove('show'));
        actionMenu.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                actionMenu.classList.remove('show');
                if (action === 'save') this.saveContent();
                if (action === 'validate') this.validateContent();
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
            <button data-cmd="bold" title="Bold">B</button>
            <button data-cmd="italic" title="Italic">I</button>
            <button data-cmd="heading" title="Heading">H</button>
            <button data-cmd="link" title="Insert Link">Link</button>
            <button data-cmd="code" title="Code">Code</button>
        `;
        toolbar.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this.applyFormat(btn.dataset.cmd);
            });
        });
        document.body.appendChild(toolbar);
        this.floatingToolbar = toolbar;
    }

    applyFormat(cmd) {
        if (cmd === 'bold') document.execCommand('bold', false, null);
        else if (cmd === 'italic') document.execCommand('italic', false, null);
        else if (cmd === 'heading') document.execCommand('formatBlock', false, '<h2>');
        else if (cmd === 'code') document.execCommand('formatBlock', false, '<code>');
        else if (cmd === 'link') {
            const url = prompt('Enter URL:');
            if (url) document.execCommand('createLink', false, url);
        }
        this.hideFloatingToolbar();
    }

    markdownToHtml(markdown) {
        return markdown
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h2>$1</h2>')
            .replace(/^# (.+)$/gm, '<h1>$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>')
            .replace(/`(.+?)`/g, '<code>$1</code>')
            .split('\n\n').map(p => `<p>${p}</p>`).join('');
    }

    htmlToMarkdown(html) {
        const temp = document.createElement('div');
        temp.innerHTML = html;
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
        if (this.editorElement.tagName === 'TEXTAREA') {
            return this.editorElement.value;
        }
        return this.htmlToMarkdown(this.editorElement.innerHTML);
    }

    async saveContent() {
        try {
            const body = this.getContent();
            const response = await fetch(`${this.apiBase}/api/content/${this.currentFile}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'If-Match': this.revision || '',
                },
                body: JSON.stringify({ revision: this.revision, body }),
            });
            const result = await response.json();
            if (response.status === 409) {
                this.showNotification(result.message || 'Conflict: file changed elsewhere. Unsaved text kept.', 'error');
                this.revision = result.revision;
                return;
            }
            if (!response.ok) {
                throw new Error(result.error || result.message || ('Failed to save: ' + response.status));
            }
            this.revision = result.revision;
            this.originalBody = result.body;
            this.showNotification('Saved working file. Not committed or deployed.', 'success');
        } catch (error) {
            console.error('Save failed:', error);
            this.showNotification('Failed to save: ' + error.message, 'error');
        }
    }

    async validateContent() {
        try {
            const content = this.getContent();
            const response = await fetch(`${this.apiBase}/api/validate-headings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error('Validation failed: ' + response.status);
            }
            if (result.valid) {
                this.showNotification('Heading check passed', 'success');
            } else {
                this.showNotification('Heading check failed: ' + (result.errors || []).join('; '), 'error');
            }
        } catch (error) {
            console.error('Validation failed:', error);
            this.showNotification('Validation error: ' + error.message, 'error');
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
        const category = document.body.dataset.category || '';
        const slug = document.body.dataset.slug || '';
        if (category && slug) {
            return `${category}/${slug}.md`;
        }
        return 'pages/home.md';
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
        requestAnimationFrame(() => toast.classList.add('editor-toast-show'));
        setTimeout(() => {
            toast.classList.remove('editor-toast-show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

window.gangEditor = new InPlaceEditor();
window.activateEditor = () => window.gangEditor.activate();

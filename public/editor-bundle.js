// GANG In-Place Editor - Notion-style contenteditable editor
// No third-party dependencies - pure vanilla JavaScript

class InPlaceEditor {
    constructor() {
        this.overlay = null;
        this.editorElement = null;
        this.originalContent = '';
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
                    <h2>Edit: ${this.getPageTitle()}</h2>
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
        editor.innerHTML = this.markdownToHtml(this.originalContent);
        
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
            if (url) {
                document.execCommand('createLink', false, url);
            }
        }
        
        this.hideFloatingToolbar();
    }

    // Markdown to HTML converter
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

    // HTML to Markdown converter
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
        return this.htmlToMarkdown(this.editorElement.innerHTML);
    }

    async saveContent() {
        try {
            const content = this.getContent();
            
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
            
            const response = await fetch('http://localhost:5001/api/validate-headings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ content })
            });
            
            if (!response.ok) {
                throw new Error('Validation failed: ' + response.status);
            }
            
            const result = await response.json();
            
            if (result.valid) {
                this.showNotification('Content validation passed', 'success');
            } else {
                this.showNotification('Validation failed: ' + result.message, 'error');
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
        const category = document.body.dataset.category || '';
        const slug = document.body.dataset.slug || '';
        
        if (pageType === 'page' && category && slug) {
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
/**
 * Comments System - Progressive Enhancement
 * 
 * Provides AJAX form submission with fallback to regular form submission.
 * Works without JavaScript (progressive enhancement).
 */

(function() {
    'use strict';
    
    // Wait for DOM to be ready
    document.addEventListener('DOMContentLoaded', function() {
        const commentForm = document.getElementById('comment-form');
        if (!commentForm) return;
        
        // Add event listener for form submission
        commentForm.addEventListener('submit', handleFormSubmit);
        
        // Add character counter for textarea
        const textarea = commentForm.querySelector('textarea[name="comment_content"]');
        if (textarea) {
            addCharacterCounter(textarea);
        }
    });
    
    /**
     * Handle form submission with AJAX
     */
    async function handleFormSubmit(e) {
        e.preventDefault();
        
        const form = e.target;
        const status = form.querySelector('.form-status');
        const button = form.querySelector('button[type="submit"]');
        
        // Check honeypot field for spam
        const honeypot = form.querySelector('[name="website"]');
        if (honeypot && honeypot.value) {
            showStatus(status, 'Error: Spam detected.', 'error');
            return;
        }
        
        // Validate required fields
        if (!validateForm(form)) {
            showStatus(status, 'Please fill in all required fields.', 'error');
            return;
        }
        
        // Disable button and show loading state
        button.disabled = true;
        button.textContent = 'Submitting...';
        showStatus(status, 'Submitting comment...', 'info');
        
        try {
            const formData = new FormData(form);
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                const result = await response.json();
                showStatus(status, '✓ Comment submitted! It will appear after approval.', 'success');
                form.reset();
                resetButton(button);
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            console.error('Comment submission error:', error);
            showStatus(status, '✗ Error submitting comment. Please try again or refresh the page.', 'error');
            resetButton(button);
        }
    }
    
    /**
     * Validate form fields
     */
    function validateForm(form) {
        const requiredFields = form.querySelectorAll('[required]');
        
        for (let field of requiredFields) {
            if (!field.value.trim()) {
                field.focus();
                return false;
            }
        }
        
        // Validate email format
        const emailField = form.querySelector('input[type="email"]');
        if (emailField && emailField.value) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(emailField.value)) {
                emailField.focus();
                return false;
            }
        }
        
        // Validate URL format if provided
        const urlField = form.querySelector('input[type="url"]');
        if (urlField && urlField.value) {
            try {
                new URL(urlField.value);
            } catch {
                urlField.focus();
                return false;
            }
        }
        
        return true;
    }
    
    /**
     * Show status message
     */
    function showStatus(element, message, type) {
        if (!element) return;
        
        element.textContent = message;
        element.className = `form-status ${type}`;
        
        // Auto-hide success messages after 5 seconds
        if (type === 'success') {
            setTimeout(() => {
                element.textContent = '';
                element.className = 'form-status';
            }, 5000);
        }
    }
    
    /**
     * Reset button to original state
     */
    function resetButton(button) {
        button.disabled = false;
        button.textContent = 'Submit Comment';
    }
    
    /**
     * Add character counter to textarea
     */
    function addCharacterCounter(textarea) {
        const maxLength = textarea.getAttribute('maxlength');
        if (!maxLength) return;
        
        const counter = document.createElement('small');
        counter.className = 'character-counter';
        counter.style.color = 'var(--color-muted)';
        counter.style.fontSize = '0.85rem';
        counter.style.marginTop = '0.25rem';
        
        function updateCounter() {
            const remaining = maxLength - textarea.value.length;
            counter.textContent = `${remaining} characters remaining`;
            
            if (remaining < 50) {
                counter.style.color = '#d32f2f';
            } else if (remaining < 100) {
                counter.style.color = '#f57c00';
            } else {
                counter.style.color = 'var(--color-muted)';
            }
        }
        
        textarea.addEventListener('input', updateCounter);
        textarea.parentNode.insertBefore(counter, textarea.nextSibling);
        updateCounter();
    }
})();




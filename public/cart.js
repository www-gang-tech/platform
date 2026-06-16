/**
 * Shopping Cart - Minimal Client-Side Implementation
 * Uses localStorage for persistence, works across pages
 */

(function() {
    'use strict';
    
    const CART_KEY = 'gang_cart';
    
    // Cart storage utilities
    function getCart() {
        try {
            return JSON.parse(localStorage.getItem(CART_KEY) || '[]');
        } catch {
            return [];
        }
    }
    
    function saveCart(cart) {
        localStorage.setItem(CART_KEY, JSON.stringify(cart));
        updateCartCount();
    }
    
    function updateCartCount() {
        const cart = getCart();
        const count = cart.reduce((sum, item) => sum + parseQuantity(item.quantity), 0);
        const badges = document.querySelectorAll('.cart-count');
        badges.forEach(badge => {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        });
    }
    
    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char]));
    }
    
    function safeControlId(value) {
        return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '-');
    }
    
    function parseQuantity(value) {
        const quantity = parseInt(value, 10);
        return Number.isNaN(quantity) ? 1 : Math.max(1, Math.min(99, quantity));
    }
    
    function hasCheckoutUrl(url) {
        return Boolean(url && url !== '#' && !String(url).endsWith('#'));
    }
    
    // Add to cart from product page
    function addToCart(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        const item = {
            id: form.dataset.variantId || Date.now().toString(),
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: parseFloat(form.dataset.price || '0') || 0,
            currency: form.dataset.currency || 'USD',
            quantity: parseQuantity(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            sku: form.dataset.sku || '',
            checkoutUrl: form.dataset.checkoutUrl || form.action || ''
        };
        
        const cart = getCart();
        const existing = cart.find(i => i.id === item.id && i.variant === item.variant);
        
        if (existing) {
            existing.quantity += item.quantity;
        } else {
            cart.push(item);
        }
        
        saveCart(cart);
        
        // Redirect to cart page
        window.location.href = '/cart/';
    }
    
    // Update quantity on cart page
    function updateQuantity(id, variant, quantity) {
        const cart = getCart();
        const item = cart.find(i => i.id === id && i.variant === variant);
        
        if (item) {
            item.quantity = Math.max(1, Math.min(99, quantity));
            saveCart(cart);
            renderCart();
        }
    }
    
    // Remove item from cart
    function removeItem(id, variant) {
        let cart = getCart();
        cart = cart.filter(i => !(i.id === id && i.variant === variant));
        saveCart(cart);
        renderCart();
    }
    
    // Render cart page
    function renderCart() {
        const container = document.getElementById('cart-items');
        const emptyMessage = document.getElementById('cart-empty');
        const cartSummary = document.getElementById('cart-summary');
        
        if (!container) return;
        
        const cart = getCart();
        
        if (cart.length === 0) {
            container.style.display = 'none';
            if (emptyMessage) emptyMessage.style.display = 'block';
            if (cartSummary) cartSummary.style.display = 'none';
            return;
        }
        
        if (emptyMessage) emptyMessage.style.display = 'none';
        if (cartSummary) cartSummary.style.display = 'block';
        container.style.display = 'block';
        
        let html = '';
        let subtotal = 0;
        
        cart.forEach((item, index) => {
            const price = parseFloat(item.price || '0') || 0;
            const quantity = parseQuantity(item.quantity);
            const itemTotal = price * quantity;
            subtotal += itemTotal;
            const id = safeControlId(`${item.id}-${item.variant}-${index}`);
            const escapedId = escapeHtml(item.id);
            const escapedVariant = escapeHtml(item.variant);
            const escapedName = escapeHtml(item.name);
            const escapedImage = escapeHtml(item.image);
            const escapedSku = escapeHtml(item.sku);
            const escapedCurrency = escapeHtml(item.currency);
            
            html += `
                <div class="cart-item">
                    ${item.image ? `<img src="${escapedImage}" alt="${escapedName}" width="80" height="80" class="cart-item-image">` : ''}
                    <div class="cart-item-details">
                        <h3 class="cart-item-name">${escapedName}</h3>
                        ${item.variant ? `<p class="cart-item-variant">${escapedVariant}</p>` : ''}
                        ${item.sku ? `<p class="cart-item-sku">SKU: ${escapedSku}</p>` : ''}
                    </div>
                    <div class="cart-item-quantity">
                        <label for="qty-${id}">Qty:</label>
                        <input type="number" 
                               id="qty-${id}"
                               value="${quantity}" 
                               min="1" 
                               max="99"
                               data-cart-action="quantity"
                               data-item-id="${escapedId}"
                               data-variant="${escapedVariant}">
                    </div>
                    <div class="cart-item-price">
                        <p>${escapedCurrency} ${price.toFixed(2)}</p>
                        <p class="cart-item-total">${escapedCurrency} ${itemTotal.toFixed(2)}</p>
                    </div>
                    <button type="button"
                            class="cart-item-remove"
                            data-cart-action="remove"
                            data-item-id="${escapedId}"
                            data-variant="${escapedVariant}"
                            aria-label="Remove ${escapedName}">
                        ✕
                    </button>
                </div>
            `;
        });
        
        container.innerHTML = html;
        container.querySelectorAll('[data-cart-action="quantity"]').forEach(input => {
            input.addEventListener('change', () => {
                updateQuantity(input.dataset.itemId, input.dataset.variant, parseQuantity(input.value));
            });
        });
        container.querySelectorAll('[data-cart-action="remove"]').forEach(button => {
            button.addEventListener('click', () => {
                removeItem(button.dataset.itemId, button.dataset.variant);
            });
        });
        
        // Update summary
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = `${cart[0].currency} ${subtotal.toFixed(2)}`;
        }
    }
    
    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        const cartItems = cart.map(item => `${item.id}:${parseQuantity(item.quantity)}`).join(',');
        const shopCartBase = cart
            .map(item => hasCheckoutUrl(item.checkoutUrl) ? item.checkoutUrl : '')
            .map(url => {
                try {
                    const parsed = new URL(url);
                    return `${parsed.origin}/cart/`;
                } catch {
                    return '';
                }
            })
            .find(Boolean);
        
        const allNumericVariantIds = cart.every(item => /^\d+$/.test(String(item.id)));
        if (shopCartBase && allNumericVariantIds) {
            window.location.href = `${shopCartBase}${cartItems}`;
            return;
        }
        
        if (cart.length === 1 && hasCheckoutUrl(cart[0].checkoutUrl)) {
            window.location.href = cart[0].checkoutUrl;
            return;
        }
        
        window.location.href = cart[0].url || '/products/';
    }
    
    // Global functions for cart page
    window.updateCartQuantity = updateQuantity;
    window.removeCartItem = removeItem;
    window.proceedToCheckout = proceedToCheckout;
    
    // Initialize
    updateCartCount();
    
    // If on cart page, render cart
    if (document.getElementById('cart-items')) {
        renderCart();
    }
    
    // Attach to product forms
    const productForms = document.querySelectorAll('.product-form');
    productForms.forEach(form => {
        form.addEventListener('submit', addToCart);
    });
})();


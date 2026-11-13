/**
 * Shopping Cart - Minimal Client-Side Implementation
 * Uses localStorage for persistence, works across pages.
 * Stored rows are untrusted: render them as text, never as HTML.
 */

(function() {
    'use strict';
    
    const CART_KEY = 'gang_cart';
    
    function getCart() {
        try {
            const parsed = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch {
            return [];
        }
    }
    
    function saveCart(cart) {
        localStorage.setItem(CART_KEY, JSON.stringify(cart));
        updateCartCount();
    }

    function asText(value) {
        return value == null ? '' : String(value);
    }

    function clampQuantity(value) {
        const number = parseInt(value, 10);
        if (!Number.isFinite(number)) return 1;
        return Math.max(1, Math.min(99, number));
    }

    function money(value) {
        const number = Number(value);
        if (!Number.isFinite(number) || number < 0) return 0;
        return number;
    }

    function imageUrl(value) {
        const raw = asText(value).trim();
        if (!raw || raw.startsWith('//') || raw.startsWith('/\\')) return '';
        if (raw.startsWith('/')) return raw;
        try {
            const url = new URL(raw, window.location.origin);
            if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
        } catch {
            return '';
        }
        return '';
    }

    function lineItem(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const quantity = clampQuantity(raw.quantity);
        return {
            id: asText(raw.id),
            name: asText(raw.name || 'Product'),
            variant: asText(raw.variant),
            price: money(raw.price),
            currency: asText(raw.currency || 'USD') || 'USD',
            quantity: quantity,
            image: imageUrl(raw.image),
            sku: asText(raw.sku)
        };
    }

    function sameLine(item, id, variant) {
        return !!item && asText(item.id) === asText(id) && asText(item.variant) === asText(variant);
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }
    
    function updateCartCount() {
        const cart = getCart();
        const count = cart.reduce((sum, item) => {
            if (!item || typeof item !== 'object') return sum;
            return sum + clampQuantity(item.quantity);
        }, 0);
        const badges = document.querySelectorAll('.cart-count');
        badges.forEach(badge => {
            badge.textContent = String(count);
            if (!badge.closest('.site-cart')) {
                badge.style.display = count > 0 ? 'inline-block' : 'none';
            }
        });
        document.querySelectorAll('.site-cart-link').forEach(link => {
            const noun = count === 1 ? 'item' : 'items';
            link.setAttribute('aria-label', `Cart, ${count} ${noun}`);
        });
    }
    
    // Add to cart from product page
    function addToCart(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        const item = {
            id: form.dataset.variantId || Date.now().toString(),
            name: asText(form.dataset.productName || 'Product'),
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: money(form.dataset.price || '0'),
            currency: asText(form.dataset.currency || 'USD') || 'USD',
            quantity: clampQuantity(formData.get('quantity') || '1'),
            image: imageUrl(form.dataset.image || ''),
            url: asText(form.dataset.productUrl || ''),
            sku: asText(form.dataset.sku || '')
        };
        
        const cart = getCart();
        const existing = cart.find(i => sameLine(i, item.id, item.variant));
        
        if (existing) {
            existing.quantity = clampQuantity(clampQuantity(existing.quantity) + item.quantity);
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
        const item = cart.find(i => sameLine(i, id, variant));
        
        if (item) {
            item.quantity = clampQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }
    
    // Remove item from cart
    function removeItem(id, variant) {
        const cart = getCart().filter(i => !sameLine(i, id, variant));
        saveCart(cart);
        renderCart();
    }

    function showEmpty(container, emptyMessage, cartSummary) {
        container.textContent = '';
        container.style.display = 'none';
        if (emptyMessage) emptyMessage.style.display = 'block';
        if (cartSummary) cartSummary.style.display = 'none';
    }
    
    // Render cart page
    function renderCart() {
        const container = document.getElementById('cart-items');
        const emptyMessage = document.getElementById('cart-empty');
        const cartSummary = document.getElementById('cart-summary');
        
        if (!container) return;
        
        const lines = getCart().map(lineItem).filter(Boolean);
        
        if (lines.length === 0) {
            showEmpty(container, emptyMessage, cartSummary);
            return;
        }
        
        if (emptyMessage) emptyMessage.style.display = 'none';
        if (cartSummary) cartSummary.style.display = 'block';
        container.style.display = 'block';
        container.textContent = '';

        let subtotal = 0;
        const currencies = new Set();
        
        lines.forEach((item, index) => {
            const itemTotal = item.price * item.quantity;
            subtotal += itemTotal;
            currencies.add(item.currency);
            
            const row = element('div', 'cart-item');
            if (item.image) {
                const img = element('img', 'cart-item-image');
                img.src = item.image;
                img.alt = item.name;
                img.width = 80;
                img.height = 80;
                row.append(img);
            }

            const details = element('div', 'cart-item-details');
            details.append(element('h3', 'cart-item-name', item.name));
            if (item.variant) details.append(element('p', 'cart-item-variant', item.variant));
            if (item.sku) details.append(element('p', 'cart-item-sku', `SKU: ${item.sku}`));
            row.append(details);

            const qtyId = `qty-${index}`;
            const quantityWrap = element('div', 'cart-item-quantity');
            const label = element('label', '', 'Qty:');
            label.htmlFor = qtyId;
            const input = element('input');
            input.type = 'number';
            input.id = qtyId;
            input.value = String(item.quantity);
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', function() {
                updateQuantity(item.id, item.variant, input.value);
            });
            quantityWrap.append(label, input);
            row.append(quantityWrap);

            const price = element('div', 'cart-item-price');
            price.append(element('p', '', `${item.currency} ${item.price.toFixed(2)}`));
            price.append(element('p', 'cart-item-total', `${item.currency} ${itemTotal.toFixed(2)}`));
            row.append(price);

            const remove = element('button', 'cart-item-remove', '✕');
            remove.type = 'button';
            remove.setAttribute('aria-label', `Remove ${item.name}`);
            remove.addEventListener('click', function() {
                removeItem(item.id, item.variant);
            });
            row.append(remove);
            container.append(row);
        });
        
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = currencies.size === 1
                ? `${lines[0].currency} ${subtotal.toFixed(2)}`
                : 'Mixed currencies';
        }
    }
    
    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        // Build Shopify cart URL
        // Format: /cart/VARIANT_ID:QUANTITY,VARIANT_ID:QUANTITY
        const cartItems = cart.map(item => `${item.id}:${item.quantity}`).join(',');
        const checkoutUrl = `https://www.shopify.com/cart/${cartItems}`;
        
        window.location.href = checkoutUrl;
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

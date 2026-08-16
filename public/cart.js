/**
 * Shopping Cart - Minimal Client-Side Implementation
 * Uses localStorage for persistence, works across pages
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
    
    function toQuantity(value) {
        const qty = parseInt(value, 10);
        if (!Number.isFinite(qty) || qty < 1) return 1;
        return Math.min(99, qty);
    }
    
    function toPrice(value) {
        const price = parseFloat(value);
        return Number.isFinite(price) ? price : 0;
    }
    
    function isSafeHttpUrl(value) {
        if (!value || typeof value !== 'string') return false;
        try {
            const url = new URL(value, window.location.origin);
            return url.protocol === 'https:' || url.protocol === 'http:';
        } catch {
            return false;
        }
    }
    
    function isNumericVariantId(value) {
        return /^\d+$/.test(String(value || ''));
    }

    function checkoutUrlFromForm(form) {
        const fromData = form.dataset.checkoutUrl || '';
        if (isSafeHttpUrl(fromData)) {
            return fromData;
        }
        const rawAction = form.getAttribute('action') || '';
        if (!rawAction || rawAction === '#') {
            return '';
        }
        if (!isSafeHttpUrl(rawAction)) {
            return '';
        }
        try {
            const url = new URL(rawAction, window.location.origin);
            if (url.origin === window.location.origin) {
                return '';
            }
            return url.href;
        } catch {
            return '';
        }
    }
    
    function updateCartCount() {
        const cart = getCart();
        const count = cart.reduce((sum, item) => sum + toQuantity(item.quantity), 0);
        const badges = document.querySelectorAll('.cart-count');
        badges.forEach(badge => {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        });
    }
    
    function addToCart(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        const checkoutUrl = checkoutUrlFromForm(form);
        const item = {
            id: form.dataset.variantId || '',
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size')
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: toPrice(form.dataset.price || '0'),
            currency: form.dataset.currency || 'USD',
            quantity: toQuantity(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: checkoutUrl || form.dataset.productUrl || '',
            checkoutUrl: checkoutUrl,
            productUrl: form.dataset.productUrl || '',
            sku: form.dataset.sku || ''
        };
        
        const cart = getCart();
        const existing = cart.find(i => i.id === item.id && i.variant === item.variant);
        
        if (existing) {
            existing.quantity = toQuantity(existing.quantity) + item.quantity;
        } else {
            cart.push(item);
        }
        
        saveCart(cart);
        window.location.href = '/cart/';
    }
    
    function updateQuantity(id, variant, quantity) {
        const cart = getCart();
        const item = cart.find(i => i.id === id && i.variant === variant);
        
        if (item) {
            item.quantity = toQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }
    
    function removeItem(id, variant) {
        let cart = getCart();
        cart = cart.filter(i => !(i.id === id && i.variant === variant));
        saveCart(cart);
        renderCart();
    }
    
    function renderCart() {
        const container = document.getElementById('cart-items');
        const emptyMessage = document.getElementById('cart-empty');
        const cartSummary = document.getElementById('cart-summary');
        
        if (!container) return;
        
        const cart = getCart();
        
        if (cart.length === 0) {
            container.style.display = 'none';
            container.replaceChildren();
            if (emptyMessage) emptyMessage.style.display = 'block';
            if (cartSummary) cartSummary.style.display = 'none';
            return;
        }
        
        if (emptyMessage) emptyMessage.style.display = 'none';
        if (cartSummary) cartSummary.style.display = 'block';
        container.style.display = 'block';
        container.replaceChildren();
        
        let subtotal = 0;
        const currencies = new Set();
        
        cart.forEach(item => {
            const quantity = toQuantity(item.quantity);
            const price = toPrice(item.price);
            const itemTotal = price * quantity;
            subtotal += itemTotal;
            currencies.add(item.currency || 'USD');
            
            const row = document.createElement('div');
            row.className = 'cart-item';
            
            if (isSafeHttpUrl(item.image) || (typeof item.image === 'string' && item.image.startsWith('/'))) {
                const img = document.createElement('img');
                img.src = item.image;
                img.alt = '';
                img.width = 80;
                img.height = 80;
                img.className = 'cart-item-image';
                row.appendChild(img);
            }
            
            const details = document.createElement('div');
            details.className = 'cart-item-details';
            const name = document.createElement('h3');
            name.className = 'cart-item-name';
            name.textContent = String(item.name || 'Product');
            details.appendChild(name);
            if (item.variant) {
                const variant = document.createElement('p');
                variant.className = 'cart-item-variant';
                variant.textContent = String(item.variant);
                details.appendChild(variant);
            }
            if (item.sku) {
                const sku = document.createElement('p');
                sku.className = 'cart-item-sku';
                sku.textContent = 'SKU: ' + String(item.sku);
                details.appendChild(sku);
            }
            row.appendChild(details);
            
            const qtyWrap = document.createElement('div');
            qtyWrap.className = 'cart-item-quantity';
            const qtyId = 'qty-' + String(item.id) + '-' + String(item.variant || '');
            const qtyLabel = document.createElement('label');
            qtyLabel.setAttribute('for', qtyId);
            qtyLabel.textContent = 'Qty:';
            const qtyInput = document.createElement('input');
            qtyInput.type = 'number';
            qtyInput.id = qtyId;
            qtyInput.value = String(quantity);
            qtyInput.min = '1';
            qtyInput.max = '99';
            qtyInput.addEventListener('change', function() {
                updateQuantity(item.id, item.variant, this.value);
            });
            qtyWrap.appendChild(qtyLabel);
            qtyWrap.appendChild(qtyInput);
            row.appendChild(qtyWrap);
            
            const priceWrap = document.createElement('div');
            priceWrap.className = 'cart-item-price';
            const unit = document.createElement('p');
            unit.textContent = (item.currency || 'USD') + ' ' + price.toFixed(2);
            const total = document.createElement('p');
            total.className = 'cart-item-total';
            total.textContent = (item.currency || 'USD') + ' ' + itemTotal.toFixed(2);
            priceWrap.appendChild(unit);
            priceWrap.appendChild(total);
            row.appendChild(priceWrap);
            
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'cart-item-remove';
            remove.setAttribute('aria-label', 'Remove ' + String(item.name || 'item'));
            remove.textContent = '✕';
            remove.addEventListener('click', function() {
                removeItem(item.id, item.variant);
            });
            row.appendChild(remove);
            
            container.appendChild(row);
        });
        
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            if (currencies.size > 1) {
                subtotalEl.textContent = 'Mixed currencies — totals shown per line';
            } else {
                const currency = currencies.values().next().value || 'USD';
                subtotalEl.textContent = currency + ' ' + subtotal.toFixed(2);
            }
        }
    }
    
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        const origins = new Set();
        const items = [];
        cart.forEach(item => {
            if (!isNumericVariantId(item.id)) return;
            const source = item.checkoutUrl || item.url || '';
            if (!isSafeHttpUrl(source)) return;
            try {
                const origin = new URL(source, window.location.origin).origin;
                if (origin === 'https://www.shopify.com') return;
                origins.add(origin);
                items.push(item.id + ':' + toQuantity(item.quantity));
            } catch {
                return;
            }
        });
        
        if (origins.size !== 1 || items.length === 0) {
            window.alert('Checkout is not configured for these cart items.');
            return;
        }
        
        window.location.href = origins.values().next().value + '/cart/' + items.join(',');
    }
    
    window.updateCartQuantity = updateQuantity;
    window.removeCartItem = removeItem;
    window.proceedToCheckout = proceedToCheckout;
    
    updateCartCount();
    
    if (document.getElementById('cart-items')) {
        renderCart();
    }
    
    const productForms = document.querySelectorAll('.product-form');
    productForms.forEach(form => {
        form.addEventListener('submit', addToCart);
    });
})();

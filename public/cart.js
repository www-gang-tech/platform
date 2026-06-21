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
        const count = cart.reduce((sum, item) => sum + item.quantity, 0);
        const badges = document.querySelectorAll('.cart-count');
        badges.forEach(badge => {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        });
    }
    
    // Add to cart from product page
    function addToCart(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        const rawAction = form.getAttribute('action');
        
        const item = {
            id: String(form.dataset.variantId || Date.now()),
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: Number.parseFloat(form.dataset.price || '0') || 0,
            currency: form.dataset.currency || 'USD',
            quantity: normalizeQuantity(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            checkoutUrl: rawAction && rawAction !== '#' ? form.action : '',
            checkoutBaseUrl: form.dataset.checkoutBaseUrl || '',
            sku: form.dataset.sku || ''
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
        const item = cart.find(i => String(i.id) === id && String(i.variant || '') === variant);
        
        if (item) {
            item.quantity = normalizeQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }
    
    // Remove item from cart
    function removeItem(id, variant) {
        let cart = getCart();
        cart = cart.filter(i => !(String(i.id) === id && String(i.variant || '') === variant));
        saveCart(cart);
        renderCart();
    }
    
    function normalizeQuantity(quantity) {
        const parsed = Number.parseInt(quantity, 10);
        if (Number.isNaN(parsed)) return 1;
        return Math.max(1, Math.min(99, parsed));
    }
    
    function formatMoney(currency, amount) {
        return `${currency || 'USD'} ${amount.toFixed(2)}`;
    }
    
    function isSafeUrl(url) {
        if (!url) return false;
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:';
        } catch {
            return false;
        }
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
        
        container.textContent = '';
        let subtotal = 0;
        
        cart.forEach((item, index) => {
            const id = String(item.id || '');
            const variant = String(item.variant || '');
            const name = String(item.name || 'Product');
            const currency = String(item.currency || 'USD');
            const price = Number.parseFloat(item.price || '0') || 0;
            const quantity = normalizeQuantity(item.quantity);
            const itemTotal = price * quantity;
            subtotal += itemTotal;
            
            const cartItem = document.createElement('div');
            cartItem.className = 'cart-item';
            
            if (isSafeUrl(item.image)) {
                const image = document.createElement('img');
                image.src = item.image;
                image.alt = name;
                image.width = 80;
                image.height = 80;
                image.className = 'cart-item-image';
                cartItem.appendChild(image);
            }
            
            const details = document.createElement('div');
            details.className = 'cart-item-details';
            
            const title = document.createElement('h3');
            title.className = 'cart-item-name';
            title.textContent = name;
            details.appendChild(title);
            
            if (variant) {
                const variantEl = document.createElement('p');
                variantEl.className = 'cart-item-variant';
                variantEl.textContent = variant;
                details.appendChild(variantEl);
            }
            
            if (item.sku) {
                const sku = document.createElement('p');
                sku.className = 'cart-item-sku';
                sku.textContent = `SKU: ${item.sku}`;
                details.appendChild(sku);
            }
            
            cartItem.appendChild(details);
            
            const quantityWrap = document.createElement('div');
            quantityWrap.className = 'cart-item-quantity';
            
            const quantityId = `qty-${index}`;
            const label = document.createElement('label');
            label.setAttribute('for', quantityId);
            label.textContent = 'Qty:';
            quantityWrap.appendChild(label);
            
            const input = document.createElement('input');
            input.type = 'number';
            input.id = quantityId;
            input.value = String(quantity);
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', () => updateQuantity(id, variant, input.value));
            quantityWrap.appendChild(input);
            cartItem.appendChild(quantityWrap);
            
            const priceWrap = document.createElement('div');
            priceWrap.className = 'cart-item-price';
            
            const priceEl = document.createElement('p');
            priceEl.textContent = formatMoney(currency, price);
            priceWrap.appendChild(priceEl);
            
            const totalEl = document.createElement('p');
            totalEl.className = 'cart-item-total';
            totalEl.textContent = formatMoney(currency, itemTotal);
            priceWrap.appendChild(totalEl);
            cartItem.appendChild(priceWrap);
            
            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'cart-item-remove';
            removeButton.setAttribute('aria-label', `Remove ${name}`);
            removeButton.textContent = '✕';
            removeButton.addEventListener('click', () => removeItem(id, variant));
            cartItem.appendChild(removeButton);
            
            container.appendChild(cartItem);
        });
        
        // Update summary
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = formatMoney(cart[0].currency, subtotal);
        }
    }
    
    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        const checkoutBaseUrl = cart.find(item => isSafeUrl(item.checkoutBaseUrl))?.checkoutBaseUrl;
        const cartItems = cart
            .filter(item => item.id)
            .map(item => `${encodeURIComponent(item.id)}:${normalizeQuantity(item.quantity)}`)
            .join(',');
        
        if (checkoutBaseUrl && cartItems) {
            window.location.href = `${checkoutBaseUrl.replace(/\/$/, '')}/cart/${cartItems}`;
            return;
        }
        
        const directCheckoutUrl = cart.find(item => isSafeUrl(item.checkoutUrl))?.checkoutUrl;
        if (directCheckoutUrl) {
            window.location.href = directCheckoutUrl;
            return;
        }
        
        window.alert('Checkout is not configured for these products.');
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
        const checkoutButton = document.getElementById('checkout-button');
        if (checkoutButton) {
            checkoutButton.addEventListener('click', proceedToCheckout);
        }
    }
    
    // Attach to product forms
    const productForms = document.querySelectorAll('.product-form');
    productForms.forEach(form => {
        form.addEventListener('submit', addToCart);
    });
})();


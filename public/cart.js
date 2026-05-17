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

    function normalizeQuantity(quantity) {
        const parsed = parseInt(quantity, 10);
        if (Number.isNaN(parsed)) return 1;
        return Math.max(1, Math.min(99, parsed));
    }

    function getNumericPrice(price) {
        const parsed = parseFloat(price);
        return Number.isNaN(parsed) ? 0 : parsed;
    }
    
    function updateCartCount() {
        const cart = getCart();
        const count = cart.reduce((sum, item) => sum + normalizeQuantity(item.quantity), 0);
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
        
        const item = {
            id: form.dataset.variantId || Date.now().toString(),
            variantId: form.dataset.variantId || '',
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: getNumericPrice(form.dataset.price || '0'),
            currency: form.dataset.currency || 'USD',
            quantity: normalizeQuantity(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            sku: form.dataset.sku || '',
            checkoutUrl: form.dataset.checkoutUrl || form.action || ''
        };
        
        const cart = getCart();
        const existing = cart.find(i => i.id === item.id && i.variant === item.variant);
        
        if (existing) {
            existing.quantity = normalizeQuantity(normalizeQuantity(existing.quantity) + item.quantity);
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
        const item = cart.find(i => i.id === id && (i.variant || '') === variant);
        
        if (item) {
            item.quantity = normalizeQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }
    
    // Remove item from cart
    function removeItem(id, variant) {
        let cart = getCart();
        cart = cart.filter(i => !(i.id === id && (i.variant || '') === variant));
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
        
        let subtotal = 0;
        let subtotalCurrency = 'USD';
        container.textContent = '';
        
        cart.forEach((item, index) => {
            const price = getNumericPrice(item.price);
            const quantity = normalizeQuantity(item.quantity);
            const currency = item.currency || subtotalCurrency;
            const itemTotal = price * quantity;
            subtotal += itemTotal;
            subtotalCurrency = currency;

            const cartItem = document.createElement('div');
            cartItem.className = 'cart-item';

            if (item.image) {
                const image = document.createElement('img');
                image.src = item.image;
                image.alt = item.name || 'Product';
                image.width = 80;
                image.height = 80;
                image.className = 'cart-item-image';
                cartItem.appendChild(image);
            }

            const details = document.createElement('div');
            details.className = 'cart-item-details';

            const name = document.createElement('h3');
            name.className = 'cart-item-name';
            name.textContent = item.name || 'Product';
            details.appendChild(name);

            if (item.variant) {
                const variant = document.createElement('p');
                variant.className = 'cart-item-variant';
                variant.textContent = item.variant;
                details.appendChild(variant);
            }

            if (item.sku) {
                const sku = document.createElement('p');
                sku.className = 'cart-item-sku';
                sku.textContent = `SKU: ${item.sku}`;
                details.appendChild(sku);
            }

            const quantityWrap = document.createElement('div');
            quantityWrap.className = 'cart-item-quantity';

            const quantityId = `qty-${index}`;
            const label = document.createElement('label');
            label.htmlFor = quantityId;
            label.textContent = 'Qty:';
            quantityWrap.appendChild(label);

            const input = document.createElement('input');
            input.type = 'number';
            input.id = quantityId;
            input.value = String(quantity);
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', () => {
                updateQuantity(item.id, item.variant || '', input.value);
            });
            quantityWrap.appendChild(input);

            const priceWrap = document.createElement('div');
            priceWrap.className = 'cart-item-price';

            const priceText = document.createElement('p');
            priceText.textContent = `${currency} ${price.toFixed(2)}`;
            priceWrap.appendChild(priceText);

            const totalText = document.createElement('p');
            totalText.className = 'cart-item-total';
            totalText.textContent = `${currency} ${itemTotal.toFixed(2)}`;
            priceWrap.appendChild(totalText);

            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'cart-item-remove';
            remove.setAttribute('aria-label', `Remove ${item.name || 'product'}`);
            remove.textContent = '×';
            remove.addEventListener('click', () => {
                removeItem(item.id, item.variant || '');
            });

            cartItem.appendChild(details);
            cartItem.appendChild(quantityWrap);
            cartItem.appendChild(priceWrap);
            cartItem.appendChild(remove);
            container.appendChild(cartItem);
        });
        
        // Update summary
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = `${subtotalCurrency} ${subtotal.toFixed(2)}`;
        }
    }

    function getExternalOrigin(rawUrl) {
        if (!rawUrl) return '';

        try {
            const url = new URL(rawUrl, window.location.origin);
            return url.origin === window.location.origin ? '' : url.origin;
        } catch {
            return '';
        }
    }

    function getFallbackCheckoutUrl(cart) {
        if (cart.length !== 1) return '';

        const checkoutUrl = cart[0].checkoutUrl || '';
        if (!checkoutUrl || checkoutUrl === '#') return '';

        return checkoutUrl;
    }

    function buildCheckoutUrl(cart) {
        const lineItems = [];
        let checkoutOrigin = '';

        for (const item of cart) {
            const variantId = String(item.variantId || item.id || '').trim();
            if (!/^\d+$/.test(variantId)) {
                return getFallbackCheckoutUrl(cart);
            }

            const origin = getExternalOrigin(item.checkoutUrl);
            if (origin && checkoutOrigin && origin !== checkoutOrigin) {
                return getFallbackCheckoutUrl(cart);
            }
            if (origin) checkoutOrigin = origin;

            lineItems.push(`${variantId}:${normalizeQuantity(item.quantity)}`);
        }

        if (!checkoutOrigin || lineItems.length === 0) {
            return getFallbackCheckoutUrl(cart);
        }

        return `${checkoutOrigin}/cart/${lineItems.join(',')}`;
    }
    
    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        const checkoutUrl = buildCheckoutUrl(cart);
        if (!checkoutUrl) {
            window.alert('Checkout is unavailable for the current cart items. Please open the product page to buy directly.');
            return;
        }
        
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


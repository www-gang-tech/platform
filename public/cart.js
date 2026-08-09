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
            const cart = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
            return Array.isArray(cart) ? cart : [];
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
        const count = cart.reduce((sum, item) => sum + normalizeQuantity(item.quantity), 0);
        const badges = document.querySelectorAll('.cart-count');
        badges.forEach(badge => {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        });
    }
    
    function cartLineKey(item) {
        // Prefer variant id; otherwise keep distinct products from collapsing
        // into one row when markdown/catalog items omit variant ids.
        return [
            String(item.id || ''),
            String(item.variant || ''),
            String(item.url || ''),
            String(item.sku || ''),
            String(item.name || ''),
        ].join('\0');
    }

    // Add to cart from product page
    function addToCart(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        const rawAction = form.getAttribute('action');
        const checkoutFromData = safeHttpUrl(form.dataset.checkoutUrl || '');
        const checkoutFromAction = (rawAction && rawAction !== '#')
            ? safeHttpUrl(form.action)
            : null;
        
        const checkoutUrl = (checkoutFromData || checkoutFromAction || { href: '' }).href || '';
        const checkoutBaseParsed = safeHttpUrl(form.dataset.checkoutBaseUrl || '');
        // Prefer a base origin that agrees with the product checkout URL.
        let checkoutBaseUrl = '';
        if (checkoutBaseParsed && checkoutUrl) {
            const checkoutParsed = safeHttpUrl(checkoutUrl);
            if (checkoutParsed && checkoutParsed.origin === checkoutBaseParsed.origin) {
                checkoutBaseUrl = checkoutBaseParsed.origin;
            }
        } else if (checkoutBaseParsed && !checkoutUrl) {
            checkoutBaseUrl = checkoutBaseParsed.origin;
        } else if (checkoutUrl) {
            const checkoutParsed = safeHttpUrl(checkoutUrl);
            if (checkoutParsed) checkoutBaseUrl = checkoutParsed.origin;
        }

        const item = {
            id: String(form.dataset.variantId || ''),
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: Number.parseFloat(form.dataset.price || '0') || 0,
            currency: form.dataset.currency || 'USD',
            quantity: normalizeQuantity(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            checkoutUrl,
            checkoutBaseUrl,
            sku: form.dataset.sku || ''
        };
        
        const cart = getCart();
        const existing = cart.find(i => cartLineKey(i) === cartLineKey(item));
        
        if (existing) {
            // Coerce before add — string quantities from older carts would
            // concatenate ("2"+3 → "23") instead of summing.
            existing.quantity = normalizeQuantity(
                normalizeQuantity(existing.quantity) + item.quantity
            );
        } else {
            cart.push(item);
        }
        
        saveCart(cart);
        
        // Redirect to cart page
        window.location.href = '/cart/';
    }
    
    // Update quantity on cart page by stable cart line key
    function updateQuantity(lineKey, quantity) {
        const cart = getCart();
        const item = cart.find(i => cartLineKey(i) === lineKey);
        
        if (item) {
            item.quantity = normalizeQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }
    
    // Remove item from cart by stable cart line key
    function removeItem(lineKey) {
        let cart = getCart();
        cart = cart.filter(i => cartLineKey(i) !== lineKey);
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

    function safeHttpUrl(url) {
        if (!url) return null;
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed : null;
        } catch {
            return null;
        }
    }

    function allowedCheckoutOrigins() {
        const meta = document.querySelector('meta[name="gang-checkout-origins"]');
        if (!meta || !meta.content) return null;
        const origins = meta.content.split(/\s+/).map(s => s.trim()).filter(Boolean);
        return origins.length ? new Set(origins) : null;
    }

    function isAllowedCheckoutUrl(parsed) {
        if (!parsed) return false;
        const allow = allowedCheckoutOrigins();
        // Pages without an allowlist keep http(s)-only behavior.
        if (!allow) return true;
        return allow.has(parsed.origin);
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
            const lineKey = cartLineKey(item);
            const variant = String(item.variant || '');
            const name = String(item.name || 'Product');
            const currency = String(item.currency || 'USD');
            const price = Number.parseFloat(item.price || '0') || 0;
            const quantity = normalizeQuantity(item.quantity);
            const itemTotal = price * quantity;
            subtotal += itemTotal;

            const cartItem = document.createElement('div');
            cartItem.className = 'cart-item';

            const imageUrl = safeHttpUrl(item.image);
            if (imageUrl) {
                const image = document.createElement('img');
                image.src = imageUrl.href;
                image.alt = name;
                image.width = 80;
                image.height = 80;
                image.loading = 'lazy';
                image.decoding = 'async';
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
                const variantElement = document.createElement('p');
                variantElement.className = 'cart-item-variant';
                variantElement.textContent = variant;
                details.appendChild(variantElement);
            }
            if (item.sku) {
                const sku = document.createElement('p');
                sku.className = 'cart-item-sku';
                sku.textContent = `SKU: ${String(item.sku)}`;
                details.appendChild(sku);
            }
            cartItem.appendChild(details);

            const quantityWrap = document.createElement('div');
            quantityWrap.className = 'cart-item-quantity';
            const quantityId = `qty-${index}`;
            const label = document.createElement('label');
            label.htmlFor = quantityId;
            label.textContent = 'Qty:';
            const input = document.createElement('input');
            input.type = 'number';
            input.id = quantityId;
            input.value = String(quantity);
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', () => updateQuantity(lineKey, input.value));
            quantityWrap.append(label, input);
            cartItem.appendChild(quantityWrap);

            const priceWrap = document.createElement('div');
            priceWrap.className = 'cart-item-price';
            const unitPrice = document.createElement('p');
            unitPrice.textContent = formatMoney(currency, price);
            const totalPrice = document.createElement('p');
            totalPrice.className = 'cart-item-total';
            totalPrice.textContent = formatMoney(currency, itemTotal);
            priceWrap.append(unitPrice, totalPrice);
            cartItem.appendChild(priceWrap);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'cart-item-remove';
            removeButton.setAttribute('aria-label', `Remove ${name}`);
            removeButton.textContent = '✕';
            removeButton.addEventListener('click', () => removeItem(lineKey));
            cartItem.appendChild(removeButton);

            container.appendChild(cartItem);
        });
        
        // Update summary — mixed-currency carts cannot share one total label.
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            const currencies = [...new Set(cart.map(i => String(i.currency || 'USD')))];
            if (currencies.length > 1) {
                subtotalEl.textContent = 'Mixed currencies — checkout per merchant';
            } else {
                subtotalEl.textContent = formatMoney(currencies[0], subtotal);
            }
        }
    }
    
    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;
        
        const baseUrl = safeHttpUrl(cart[0].checkoutBaseUrl);
        const isNumericId = value => /^\d+$/.test(String(value || ''));
        const sameMerchantItems = baseUrl && isAllowedCheckoutUrl(baseUrl)
            ? cart.filter(item => {
                const itemBase = safeHttpUrl(item.checkoutBaseUrl);
                return itemBase
                    && itemBase.origin === baseUrl.origin
                    && isAllowedCheckoutUrl(itemBase)
                    && isNumericId(item.id);
            })
            : [];

        if (baseUrl && sameMerchantItems.length === cart.length) {
            const cartItems = sameMerchantItems
                .map(item => `${item.id}:${normalizeQuantity(item.quantity)}`)
                .join(',');
            window.location.href = `${baseUrl.origin}/cart/${cartItems}`;
            return;
        }

        if (cart.length === 1) {
            const directCheckoutUrl = safeHttpUrl(cart[0].checkoutUrl);
            if (directCheckoutUrl && isAllowedCheckoutUrl(directCheckoutUrl)) {
                window.location.href = directCheckoutUrl.href;
                return;
            }
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


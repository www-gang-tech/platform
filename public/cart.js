/**
 * Shopping Cart - Minimal Client-Side Implementation
 * Uses localStorage for persistence, works across pages.
 */

(function() {
    'use strict';

    const CART_KEY = 'gang_cart';

    function toString(value, fallback = '') {
        return value === undefined || value === null ? fallback : String(value);
    }

    function toQuantity(value) {
        const parsed = parseInt(value, 10);
        if (!Number.isFinite(parsed)) return 1;
        return Math.max(1, Math.min(99, parsed));
    }

    function toPrice(value) {
        const parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function normalizeStoreDomain(domain) {
        const rawDomain = toString(domain).trim();
        if (!rawDomain) return '';

        try {
            return new URL(rawDomain.startsWith('http') ? rawDomain : `https://${rawDomain}`).hostname;
        } catch {
            return '';
        }
    }

    function safeImageUrl(url) {
        const rawUrl = toString(url).trim();
        if (!rawUrl) return '';

        try {
            const parsed = new URL(rawUrl, window.location.origin);
            if (['http:', 'https:'].includes(parsed.protocol)) {
                return parsed.href;
            }
        } catch {
            return '';
        }

        return '';
    }

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
        const color = toString(formData.get('color'));
        const size = toString(formData.get('size'));

        const item = {
            id: toString(form.dataset.variantId || form.dataset.sku || Date.now()),
            name: toString(form.dataset.productName, 'Product'),
            variant: color && size ? `${color} / ${size}` : '',
            price: toPrice(form.dataset.price),
            currency: toString(form.dataset.currency, 'USD'),
            quantity: toQuantity(formData.get('quantity')),
            image: toString(form.dataset.image),
            url: toString(form.dataset.productUrl),
            sku: toString(form.dataset.sku),
            storeDomain: normalizeStoreDomain(form.dataset.shopifyStoreDomain || document.body.dataset.shopifyStoreDomain)
        };

        const cart = getCart();
        const existing = cart.find(i => toString(i.id) === item.id && toString(i.variant) === item.variant);

        if (existing) {
            existing.quantity = toQuantity(existing.quantity) + item.quantity;
            existing.storeDomain = existing.storeDomain || item.storeDomain;
        } else {
            cart.push(item);
        }

        saveCart(cart);
        window.location.href = '/cart/';
    }

    function updateQuantity(id, variant, quantity) {
        const itemId = toString(id);
        const itemVariant = toString(variant);
        const cart = getCart();
        const item = cart.find(i => toString(i.id) === itemId && toString(i.variant) === itemVariant);

        if (item) {
            item.quantity = toQuantity(quantity);
            saveCart(cart);
            renderCart();
        }
    }

    function removeItem(id, variant) {
        const itemId = toString(id);
        const itemVariant = toString(variant);
        const cart = getCart().filter(i => !(toString(i.id) === itemId && toString(i.variant) === itemVariant));
        saveCart(cart);
        renderCart();
    }

    function appendText(parent, tagName, text, className) {
        const element = document.createElement(tagName);
        if (className) element.className = className;
        element.textContent = text;
        parent.appendChild(element);
        return element;
    }

    function renderCart() {
        const container = document.getElementById('cart-items');
        const emptyMessage = document.getElementById('cart-empty');
        const cartSummary = document.getElementById('cart-summary');

        if (!container) return;

        const cart = getCart();
        container.replaceChildren();

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

        cart.forEach((item, index) => {
            const itemId = toString(item.id);
            const itemVariant = toString(item.variant);
            const itemName = toString(item.name, 'Product');
            const itemPrice = toPrice(item.price);
            const itemQuantity = toQuantity(item.quantity);
            const itemCurrency = toString(item.currency, 'USD');
            const itemTotal = itemPrice * itemQuantity;
            const quantityInputId = `qty-${index}`;

            subtotal += itemTotal;
            subtotalCurrency = itemCurrency;

            const row = document.createElement('div');
            row.className = 'cart-item';

            const imageUrl = safeImageUrl(item.image);
            if (imageUrl) {
                const image = document.createElement('img');
                image.src = imageUrl;
                image.alt = itemName;
                image.width = 80;
                image.height = 80;
                image.className = 'cart-item-image';
                row.appendChild(image);
            }

            const details = document.createElement('div');
            details.className = 'cart-item-details';
            appendText(details, 'h3', itemName, 'cart-item-name');
            if (itemVariant) appendText(details, 'p', itemVariant, 'cart-item-variant');
            if (item.sku) appendText(details, 'p', `SKU: ${toString(item.sku)}`, 'cart-item-sku');
            row.appendChild(details);

            const quantity = document.createElement('div');
            quantity.className = 'cart-item-quantity';

            const label = document.createElement('label');
            label.setAttribute('for', quantityInputId);
            label.textContent = 'Qty:';
            quantity.appendChild(label);

            const input = document.createElement('input');
            input.type = 'number';
            input.id = quantityInputId;
            input.value = itemQuantity;
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', () => updateQuantity(itemId, itemVariant, input.value));
            quantity.appendChild(input);
            row.appendChild(quantity);

            const price = document.createElement('div');
            price.className = 'cart-item-price';
            appendText(price, 'p', `${itemCurrency} ${itemPrice.toFixed(2)}`);
            appendText(price, 'p', `${itemCurrency} ${itemTotal.toFixed(2)}`, 'cart-item-total');
            row.appendChild(price);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'cart-item-remove';
            removeButton.setAttribute('aria-label', `Remove ${itemName}`);
            removeButton.textContent = 'Remove';
            removeButton.addEventListener('click', () => removeItem(itemId, itemVariant));
            row.appendChild(removeButton);

            container.appendChild(row);
        });

        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = `${subtotalCurrency} ${subtotal.toFixed(2)}`;
        }
    }

    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;

        const storeDomain = normalizeStoreDomain(
            cart.find(item => item.storeDomain)?.storeDomain || document.body.dataset.shopifyStoreDomain
        );

        if (!storeDomain) {
            window.alert('Checkout is not configured for this store.');
            return;
        }

        const cartItems = cart
            .filter(item => toString(item.id))
            .map(item => `${encodeURIComponent(toString(item.id))}:${toQuantity(item.quantity)}`)
            .join(',');

        if (!cartItems) {
            window.alert('No checkout-ready items found in the cart.');
            return;
        }

        window.location.href = `https://${storeDomain}/cart/${cartItems}`;
    }

    window.updateCartQuantity = updateQuantity;
    window.removeCartItem = removeItem;
    window.proceedToCheckout = proceedToCheckout;

    updateCartCount();

    if (document.getElementById('cart-items')) {
        renderCart();
    }

    const checkoutButton = document.getElementById('checkout-button');
    if (checkoutButton) {
        checkoutButton.addEventListener('click', proceedToCheckout);
    }

    const productForms = document.querySelectorAll('.product-form');
    productForms.forEach(form => {
        form.addEventListener('submit', addToCart);
    });
})();


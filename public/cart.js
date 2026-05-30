/**
 * Shopping Cart - Minimal Client-Side Implementation
 * Uses localStorage for persistence, works across pages
 */

(function() {
    'use strict';

    const CART_KEY = 'gang_cart';

    function toQuantity(value) {
        const quantity = parseInt(value || '1', 10);
        if (Number.isNaN(quantity)) return 1;
        return Math.max(1, Math.min(99, quantity));
    }

    function normalizeShopifyDomain(value) {
        return (value || '')
            .replace(/^https?:\/\//, '')
            .replace(/\/.*$/, '')
            .trim();
    }

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
        const count = cart.reduce((sum, item) => sum + toQuantity(item.quantity), 0);
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
        const variantId = form.dataset.variantId || form.dataset.sku || Date.now().toString();

        const item = {
            id: variantId,
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size')
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: parseFloat(form.dataset.price || '0'),
            currency: form.dataset.currency || 'USD',
            quantity: toQuantity(formData.get('quantity')),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            sku: form.dataset.sku || '',
            shopifyStoreDomain: normalizeShopifyDomain(form.dataset.shopifyStoreDomain)
        };

        const cart = getCart();
        const existing = cart.find(i => i.id === item.id && i.variant === item.variant);

        if (existing) {
            existing.quantity = toQuantity(existing.quantity) + item.quantity;
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
            item.quantity = toQuantity(quantity);
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

    function appendText(parent, tagName, className, text) {
        const element = document.createElement(tagName);
        if (className) element.className = className;
        element.textContent = text;
        parent.appendChild(element);
        return element;
    }

    function renderCartItem(container, item, index) {
        const quantity = toQuantity(item.quantity);
        let price = parseFloat(item.price || '0');
        if (Number.isNaN(price)) price = 0;
        const itemTotal = price * quantity;
        const currency = item.currency || 'USD';

        const row = document.createElement('div');
        row.className = 'cart-item';

        if (item.image) {
            const image = document.createElement('img');
            image.src = item.image;
            image.alt = item.name || 'Product image';
            image.width = 80;
            image.height = 80;
            image.className = 'cart-item-image';
            row.appendChild(image);
        }

        const details = document.createElement('div');
        details.className = 'cart-item-details';
        appendText(details, 'h3', 'cart-item-name', item.name || 'Product');
        if (item.variant) appendText(details, 'p', 'cart-item-variant', item.variant);
        if (item.sku) appendText(details, 'p', 'cart-item-sku', `SKU: ${item.sku}`);
        row.appendChild(details);

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
        input.dataset.cartId = item.id || '';
        input.dataset.cartVariant = item.variant || '';
        input.addEventListener('change', () => {
            updateQuantity(input.dataset.cartId, input.dataset.cartVariant, input.value);
        });
        quantityWrap.appendChild(input);
        row.appendChild(quantityWrap);

        const priceWrap = document.createElement('div');
        priceWrap.className = 'cart-item-price';
        appendText(priceWrap, 'p', '', `${currency} ${price.toFixed(2)}`);
        appendText(priceWrap, 'p', 'cart-item-total', `${currency} ${itemTotal.toFixed(2)}`);
        row.appendChild(priceWrap);

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'cart-item-remove';
        removeButton.textContent = 'Remove';
        removeButton.setAttribute('aria-label', `Remove ${item.name || 'product'}`);
        removeButton.addEventListener('click', () => removeItem(item.id || '', item.variant || ''));
        row.appendChild(removeButton);

        container.appendChild(row);
        return itemTotal;
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
        cart.forEach((item, index) => {
            subtotal += renderCartItem(container, item, index);
        });

        // Update summary
        const subtotalEl = document.getElementById('cart-subtotal');
        if (subtotalEl) {
            subtotalEl.textContent = `${cart[0].currency || 'USD'} ${subtotal.toFixed(2)}`;
        }
    }

    // Build Shopify checkout URL with all cart items
    function proceedToCheckout() {
        const cart = getCart();
        if (cart.length === 0) return;

        const bodyDomain = document.body ? document.body.dataset.shopifyStoreDomain : '';
        const shopifyStoreDomain = normalizeShopifyDomain(
            cart.find(item => item.shopifyStoreDomain)?.shopifyStoreDomain || bodyDomain
        );

        if (!shopifyStoreDomain) {
            window.alert('Checkout is unavailable because the Shopify store domain is not configured.');
            return;
        }

        const checkoutItems = cart
            .filter(item => item.id)
            .map(item => `${encodeURIComponent(item.id)}:${toQuantity(item.quantity)}`)
            .join(',');

        if (!checkoutItems) {
            window.alert('Checkout is unavailable because cart items are missing Shopify variant IDs.');
            return;
        }

        window.location.href = `https://${shopifyStoreDomain}/cart/${checkoutItems}`;
    }

    // Global functions retained for backwards compatibility with older generated pages.
    window.updateCartQuantity = updateQuantity;
    window.removeCartItem = removeItem;
    window.proceedToCheckout = proceedToCheckout;

    // Initialize
    updateCartCount();

    // If on cart page, render cart
    if (document.getElementById('cart-items')) {
        renderCart();
    }

    const checkoutButton = document.getElementById('checkout-button');
    if (checkoutButton) {
        checkoutButton.addEventListener('click', proceedToCheckout);
    }

    // Attach to product forms
    const productForms = document.querySelectorAll('.product-form');
    productForms.forEach(form => {
        form.addEventListener('submit', addToCart);
    });
})();

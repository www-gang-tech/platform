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

    function toSafeNumber(value, fallback) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function getCheckoutBase(form) {
        try {
            const action = form.getAttribute('action');
            if (!action || action === '#') return '';
            const url = new URL(action, window.location.href);
            return url.protocol === 'http:' || url.protocol === 'https:' ? url.origin : '';
        } catch {
            return '';
        }
    }
    
    function updateCartCount() {
        const cart = getCart();
        const count = cart.reduce((sum, item) => sum + (parseInt(item.quantity, 10) || 0), 0);
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
        const quantity = Math.max(1, Math.min(99, parseInt(formData.get('quantity') || '1', 10) || 1));
        const price = toSafeNumber(form.dataset.price, 0);
        
        const item = {
            id: form.dataset.variantId || form.dataset.sku || Date.now().toString(),
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: price,
            currency: form.dataset.currency || 'USD',
            quantity: quantity,
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            sku: form.dataset.sku || '',
            checkoutBase: getCheckoutBase(form)
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
            item.quantity = Math.max(1, Math.min(99, parseInt(quantity, 10) || 1));
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
        
        let subtotal = 0;
        container.textContent = '';
        
        cart.forEach((item, index) => {
            const price = toSafeNumber(item.price, 0);
            const quantity = Math.max(1, Math.min(99, parseInt(item.quantity, 10) || 1));
            const itemTotal = price * quantity;
            const currency = item.currency || 'USD';
            subtotal += itemTotal;

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

            cartItem.appendChild(details);

            const quantityContainer = document.createElement('div');
            quantityContainer.className = 'cart-item-quantity';

            const quantityId = `qty-${index}`;
            const label = document.createElement('label');
            label.htmlFor = quantityId;
            label.textContent = 'Qty:';
            quantityContainer.appendChild(label);

            const input = document.createElement('input');
            input.type = 'number';
            input.id = quantityId;
            input.value = String(quantity);
            input.min = '1';
            input.max = '99';
            input.addEventListener('change', () => updateQuantity(item.id, item.variant || '', input.value));
            quantityContainer.appendChild(input);
            cartItem.appendChild(quantityContainer);

            const priceContainer = document.createElement('div');
            priceContainer.className = 'cart-item-price';

            const unitPrice = document.createElement('p');
            unitPrice.textContent = `${currency} ${price.toFixed(2)}`;
            priceContainer.appendChild(unitPrice);

            const totalPrice = document.createElement('p');
            totalPrice.className = 'cart-item-total';
            totalPrice.textContent = `${currency} ${itemTotal.toFixed(2)}`;
            priceContainer.appendChild(totalPrice);
            cartItem.appendChild(priceContainer);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'cart-item-remove';
            removeButton.setAttribute('aria-label', `Remove ${item.name || 'product'}`);
            removeButton.textContent = 'Remove';
            removeButton.addEventListener('click', () => removeItem(item.id, item.variant || ''));
            cartItem.appendChild(removeButton);

            container.appendChild(cartItem);
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
        
        const checkoutBase = cart.find(item => item.checkoutBase)?.checkoutBase;
        if (!checkoutBase) {
            alert('Checkout is not configured for these cart items.');
            return;
        }

        // Build Shopify cart URL on the merchant store domain.
        // Format: /cart/VARIANT_ID:QUANTITY,VARIANT_ID:QUANTITY
        const cartItems = cart.map(item => {
            const quantity = Math.max(1, Math.min(99, parseInt(item.quantity, 10) || 1));
            return `${encodeURIComponent(item.id)}:${quantity}`;
        }).join(',');
        const checkoutUrl = `${checkoutBase}/cart/${cartItems}`;
        
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


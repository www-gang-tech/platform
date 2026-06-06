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
        
        const item = {
            id: form.dataset.variantId || Date.now().toString(),
            name: form.dataset.productName || 'Product',
            variant: formData.get('color') && formData.get('size') 
                ? `${formData.get('color')} / ${formData.get('size')}`
                : '',
            price: parseFloat(form.dataset.price || '0'),
            currency: form.dataset.currency || 'USD',
            quantity: parseInt(formData.get('quantity') || '1'),
            image: form.dataset.image || '',
            url: form.dataset.productUrl || '',
            sku: form.dataset.sku || '',
            checkoutBaseUrl: form.dataset.checkoutBaseUrl || ''
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
        
        let subtotal = 0;
        container.textContent = '';
        
        cart.forEach((item, index) => {
            const itemTotal = item.price * item.quantity;
            subtotal += itemTotal;

            const cartItem = document.createElement('div');
            cartItem.className = 'cart-item';

            if (item.image) {
                const image = document.createElement('img');
                image.src = item.image;
                image.alt = item.name;
                image.width = 80;
                image.height = 80;
                image.className = 'cart-item-image';
                cartItem.appendChild(image);
            }

            const details = document.createElement('div');
            details.className = 'cart-item-details';

            const name = document.createElement('h3');
            name.className = 'cart-item-name';
            name.textContent = item.name;
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

            const quantity = document.createElement('div');
            quantity.className = 'cart-item-quantity';

            const quantityId = `qty-${index}`;
            const quantityLabel = document.createElement('label');
            quantityLabel.htmlFor = quantityId;
            quantityLabel.textContent = 'Qty:';
            quantity.appendChild(quantityLabel);

            const quantityInput = document.createElement('input');
            quantityInput.type = 'number';
            quantityInput.id = quantityId;
            quantityInput.value = item.quantity;
            quantityInput.min = '1';
            quantityInput.max = '99';
            quantityInput.addEventListener('change', () => {
                updateQuantity(item.id, item.variant, parseInt(quantityInput.value || '1'));
            });
            quantity.appendChild(quantityInput);
            cartItem.appendChild(quantity);

            const price = document.createElement('div');
            price.className = 'cart-item-price';

            const unitPrice = document.createElement('p');
            unitPrice.textContent = `${item.currency} ${item.price.toFixed(2)}`;
            price.appendChild(unitPrice);

            const totalPrice = document.createElement('p');
            totalPrice.className = 'cart-item-total';
            totalPrice.textContent = `${item.currency} ${itemTotal.toFixed(2)}`;
            price.appendChild(totalPrice);
            cartItem.appendChild(price);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'cart-item-remove';
            removeButton.setAttribute('aria-label', `Remove ${item.name}`);
            removeButton.textContent = 'x';
            removeButton.addEventListener('click', () => removeItem(item.id, item.variant));
            cartItem.appendChild(removeButton);

            container.appendChild(cartItem);
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
        
        const checkoutBaseUrl = cart.find(item => item.checkoutBaseUrl)?.checkoutBaseUrl ||
            document.body?.dataset.checkoutBaseUrl;

        if (!checkoutBaseUrl) {
            alert('Checkout is unavailable for this cart.');
            return;
        }

        // Build Shopify cart URL
        // Format: /cart/VARIANT_ID:QUANTITY,VARIANT_ID:QUANTITY
        const cartItems = cart.map(item => `${encodeURIComponent(item.id)}:${item.quantity}`).join(',');
        const checkoutUrl = `${checkoutBaseUrl.replace(/\/$/, '')}/cart/${cartItems}`;
        
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


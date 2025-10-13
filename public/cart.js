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
        
        cart.forEach(item => {
            const itemTotal = item.price * item.quantity;
            subtotal += itemTotal;
            
            html += `
                <div class="cart-item">
                    ${item.image ? `<img src="${item.image}" alt="${item.name}" width="80" height="80" class="cart-item-image">` : ''}
                    <div class="cart-item-details">
                        <h3 class="cart-item-name">${item.name}</h3>
                        ${item.variant ? `<p class="cart-item-variant">${item.variant}</p>` : ''}
                        ${item.sku ? `<p class="cart-item-sku">SKU: ${item.sku}</p>` : ''}
                    </div>
                    <div class="cart-item-quantity">
                        <label for="qty-${item.id}-${item.variant}">Qty:</label>
                        <input type="number" 
                               id="qty-${item.id}-${item.variant}"
                               value="${item.quantity}" 
                               min="1" 
                               max="99"
                               onchange="updateCartQuantity('${item.id}', '${item.variant}', this.value)">
                    </div>
                    <div class="cart-item-price">
                        <p>${item.currency} ${item.price.toFixed(2)}</p>
                        <p class="cart-item-total">${item.currency} ${itemTotal.toFixed(2)}</p>
                    </div>
                    <button onclick="removeCartItem('${item.id}', '${item.variant}')" 
                            class="cart-item-remove" 
                            aria-label="Remove ${item.name}">
                        ✕
                    </button>
                </div>
            `;
        });
        
        container.innerHTML = html;
        
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


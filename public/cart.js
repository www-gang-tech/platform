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
    
    function decodeHref(value) {
        let decoded = value;
        for (let i = 0; i < 3; i++) {
            try {
                const next = decodeURIComponent(decoded);
                if (next === decoded) break;
                decoded = next;
            } catch (err) {
                break;
            }
        }
        return decoded;
    }

    function normalizeHref(value) {
        let current = String(value);
        for (let i = 0; i < 3; i++) {
            const next = current
                .replace(/&amp;/gi, '&')
                .replace(/&colon;/gi, ':')
                .replace(/&#0*58;/gi, ':')
                .replace(/&#x0*3a;/gi, ':');
            if (next === current) break;
            current = next;
        }
        return decodeHref(current);
    }

    function isSafeHttpUrl(value) {
        if (!value || typeof value !== 'string') return false;
        const trimmed = value.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('/\\') || trimmed.startsWith('\\')) {
            return false;
        }
        const decoded = normalizeHref(trimmed);
        if (decoded.startsWith('//') || decoded.startsWith('/\\') || decoded.startsWith('\\')) {
            return false;
        }
        if (/%00/i.test(trimmed) || decoded.indexOf('\0') !== -1 || /%00/i.test(decoded)) {
            return false;
        }
        if (decoded.split('/').some(function(seg) { return seg === '..' || seg.indexOf('..') === 0; })) {
            return false;
        }
        const pathPart = decoded.replace(/\\/g, '/').split('?')[0].split('#')[0];
        const isRelative = decoded.charAt(0) === '/' && decoded.charAt(1) !== '/';
        if (isRelative) {
            return pathPart.indexOf('//') === -1;
        }
        if (!/^https?:\/\//i.test(decoded)) {
            return false;
        }
        try {
            const url = new URL(decoded);
            if (url.username) return false;
            return url.protocol === 'https:' || url.protocol === 'http:';
        } catch {
            return false;
        }
    }

    function isExplicitlyInStock(value) {
        return value === true || value === 'true';
    }
    
    function isNumericVariantId(value) {
        let text = String(value == null ? '' : value).trim();
        if (/^\d+\.0+$/.test(text)) {
            text = text.split('.')[0];
        }
        return /^\d+$/.test(text);
    }

    function isSafeCartImage(value) {
        if (!value || typeof value !== 'string') return false;
        if (value.startsWith('//') || value.startsWith('/\\') || value.startsWith('\\')) return false;
        const decoded = decodeHref(value);
        if (decoded.startsWith('//') || decoded.startsWith('/\\') || decoded.startsWith('\\')) return false;
        if (/%00/i.test(value) || decoded.indexOf('\0') !== -1) return false;
        if (decoded.split('/').some(function(seg) { return seg === '..' || seg.indexOf('..') === 0; })) return false;
        if (value.startsWith('/') && !value.startsWith('//')) return true;
        return isSafeHttpUrl(value);
    }

    function allowedCheckoutOrigins() {
        const meta = document.querySelector('meta[name="gang-checkout-origins"]');
        if (!meta) return new Set();
        const origins = String(meta.content || '').split(/\s+/).map(s => s.trim()).filter(Boolean);
        return new Set(origins.flatMap(function(s) {
            try {
                return [new URL(s).origin];
            } catch (err) {
                return [];
            }
        }));
    }

    function isAllowedCheckoutUrl(parsed) {
        if (!parsed) return false;
        const allow = allowedCheckoutOrigins();
        if (!allow.size) return false;
        return allow.has(parsed.origin);
    }

    function parseVariantsData() {
        const el = document.getElementById('variants-data');
        if (!el) return [];
        try {
            const parsed = JSON.parse(el.textContent);
            return Array.isArray(parsed) ? parsed : [];
        } catch {
            return [];
        }
    }

    function isVariantInStock(variant) {
        const avail = String((variant && variant.availability) || '').trim();
        if (!avail || avail === 'OutOfStock' || avail.slice(-11) === '/OutOfStock') return false;
        return avail === 'InStock' || avail.slice(-8) === '/InStock';
    }

    function resolveSelectedVariant(form, formData) {
        const variants = parseVariantsData();
        if (!variants.length) return null;
        const colorSelect = form.querySelector('[name="color"]');
        const sizeSelect = form.querySelector('[name="size"]');
        const option3Select = form.querySelector('[name="option3"]');
        const selectedColor = colorSelect ? String(formData.get('color') ?? '') : null;
        const selectedSize = sizeSelect ? String(formData.get('size') ?? '') : null;
        const selectedOption3 = option3Select ? String(formData.get('option3') ?? '') : null;
        const matches = variants.filter(function(variant) {
            const colorMatch = colorSelect ? String(variant.color ?? '') === selectedColor : true;
            const sizeMatch = sizeSelect ? String(variant.size ?? '') === selectedSize : true;
            const extraMatch = option3Select ? String(variant.option3 ?? '') === selectedOption3 : true;
            return colorMatch && sizeMatch && extraMatch;
        });
        if (!matches.length) return null;
        const inStockMatches = matches.filter(isVariantInStock);
        if (inStockMatches.length === 1) return inStockMatches[0];
        if (inStockMatches.length > 1 || matches.length > 1) return null;
        return matches[0];
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
        const variants = parseVariantsData();
        const selected = resolveSelectedVariant(form, formData);
        if (variants.length && !selected) {
            window.alert('This combination is unavailable.');
            return;
        }
        const variantId = selected && selected.id != null ? String(selected.id) : (form.dataset.variantId || '');
        const selectedInStock = selected
            ? isVariantInStock(selected)
            : form.dataset.inStock === 'true';
        if (!selectedInStock) {
            window.alert('This item is out of stock.');
            return;
        }
        if (!isNumericVariantId(variantId)) {
            window.alert('Checkout is not configured for this product.');
            return;
        }
        
        let checkoutUrl = '';
        if (selected && selected.url && isSafeHttpUrl(String(selected.url))) {
            checkoutUrl = String(selected.url);
        } else {
            checkoutUrl = checkoutUrlFromForm(form);
        }
        if (checkoutUrl) {
            try {
                const parsed = new URL(checkoutUrl, window.location.origin);
                if (parsed.origin === window.location.origin) {
                    checkoutUrl = '';
                } else if (!isAllowedCheckoutUrl(parsed)) {
                    window.alert('Checkout is not configured for this product.');
                    return;
                } else {
                    checkoutUrl = parsed.href;
                }
            } catch (err) {
                checkoutUrl = '';
            }
        }
        if (!checkoutUrl) {
            window.alert('Checkout is not configured for this product.');
            return;
        }
        const variantParts = [];
        if (form.querySelector('[name="color"]')) variantParts.push(String(formData.get('color') ?? ''));
        if (form.querySelector('[name="size"]')) variantParts.push(String(formData.get('size') ?? ''));
        if (form.querySelector('[name="option3"]')) variantParts.push(String(formData.get('option3') ?? ''));
        const nextCurrency = String((selected && selected.currency) || form.dataset.currency || 'USD').toUpperCase();
        const existingCart = getCart();
        if (existingCart.some(function(row) {
            return String(row.currency || 'USD').toUpperCase() !== nextCurrency;
        })) {
            window.alert('Checkout cannot mix currencies. Remove items so the cart uses one currency.');
            return;
        }
        const rawImage = (selected && selected.image) || form.dataset.image || '';
        const item = {
            id: variantId,
            name: form.dataset.productName || 'Product',
            variant: variantParts.join(' / '),
            price: toPrice((selected && selected.price != null ? selected.price : form.dataset.price) || '0'),
            currency: nextCurrency,
            quantity: toQuantity(formData.get('quantity') || '1'),
            image: isSafeCartImage(rawImage) ? rawImage : '',
            url: checkoutUrl || form.dataset.productUrl || '',
            checkoutUrl: checkoutUrl,
            productUrl: form.dataset.productUrl || '',
            sku: (selected && selected.sku != null ? String(selected.sku) : form.dataset.sku) || '',
            inStock: selectedInStock
        };
        
        for (let attempt = 0; attempt < 3; attempt++) {
            const raw = localStorage.getItem(CART_KEY);
            const cart = getCart();
            const existing = cart.find(i => i.id === item.id && i.variant === item.variant);

            if (existing) {
                existing.quantity = Math.min(99, toQuantity(existing.quantity) + toQuantity(item.quantity));
            } else {
                cart.push(item);
            }

            if (localStorage.getItem(CART_KEY) !== raw) {
                continue;
            }
            saveCart(cart);
            window.location.href = '/cart/';
            return;
        }
        window.alert('Cart was updated in another tab. Please add the item again.');
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
            currencies.add(String(item.currency || 'USD').toUpperCase());
            
            const row = document.createElement('div');
            row.className = 'cart-item';
            
            if (isSafeCartImage(item.image)) {
                const img = document.createElement('img');
                img.src = item.image;
                img.alt = String(item.name || 'Product');
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
            unit.textContent = String(item.currency || 'USD').toUpperCase() + ' ' + price.toFixed(2);
            const total = document.createElement('p');
            total.className = 'cart-item-total';
            total.textContent = String(item.currency || 'USD').toUpperCase() + ' ' + itemTotal.toFixed(2);
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

        const currencies = new Set(cart.map(item => String(item.currency || 'USD').toUpperCase()));
        if (currencies.size > 1) {
            window.alert('Checkout cannot mix currencies. Remove items so the cart uses one currency.');
            return;
        }
        
        const allow = allowedCheckoutOrigins();
        const origins = new Set();
        const items = [];
        const skipped = [];
        cart.forEach(item => {
            if (!isExplicitlyInStock(item.inStock)) {
                skipped.push(item);
                return;
            }
            if (!isNumericVariantId(item.id)) {
                skipped.push(item);
                return;
            }
            const source = item.checkoutUrl || item.url || '';
            let parsed = null;
            if (isSafeHttpUrl(source)) {
                try {
                    parsed = new URL(source, window.location.origin);
                } catch {
                    parsed = null;
                }
            }
            if (!parsed || parsed.origin === window.location.origin) {
                if (allow.size !== 1) {
                    skipped.push(item);
                    return;
                }
                parsed = new URL(Array.from(allow)[0]);
            }
            const host = String(parsed.hostname || '').toLowerCase();
            if (host === 'shopify.com' || host.endsWith('.shopify.com')) {
                skipped.push(item);
                return;
            }
            if (!isAllowedCheckoutUrl(parsed)) {
                skipped.push(item);
                return;
            }
            origins.add(parsed.origin);
            items.push(item.id + ':' + toQuantity(item.quantity));
        });
        
        if (skipped.length || origins.size !== 1 || items.length !== cart.length) {
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

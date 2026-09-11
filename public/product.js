/**
 * Product Variant Selector - Progressive Enhancement
 * Works without JS, enhanced with JS for better UX
 */

(function() {
    'use strict';
    
    const form = document.querySelector('.product-form');
    if (!form) return;
    
    const colorSelect = form.querySelector('[name="color"]');
    const sizeSelect = form.querySelector('[name="size"]');
    const option3Select = form.querySelector('[name="option3"]');
    const quantityInput = form.querySelector('[name="quantity"]');
    const priceDisplay = document.querySelector('[data-price]');
    const stockMessage = document.querySelector('[data-stock-message]');
    const buyButton = form.querySelector('[type="submit"]');
    const productImages = document.querySelectorAll('[data-variant-image]');
    
    const variantsData = document.getElementById('variants-data');
    let variants = [];
    try {
        variants = variantsData ? JSON.parse(variantsData.textContent) : [];
    } catch (err) {
        variants = [];
    }
    if (!Array.isArray(variants)) {
        variants = [];
    }
    
    function isInStock(variant) {
        const avail = String((variant && variant.availability) || '').trim();
        if (!avail || avail === 'OutOfStock' || avail.slice(-11) === '/OutOfStock') return false;
        return avail === 'InStock' || avail.slice(-8) === '/InStock';
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

    function isSafeActionUrl(value) {
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
        } catch (err) {
            return false;
        }
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

    function isAllowedCheckoutUrl(value) {
        if (!isSafeActionUrl(value)) return false;
        try {
            const parsed = new URL(value, window.location.origin);
            if (parsed.origin === window.location.origin) return false;
            const allow = allowedCheckoutOrigins();
            if (!allow.size) return false;
            return allow.has(parsed.origin);
        } catch (err) {
            return false;
        }
    }
    
    function findVariant(selectedColor, selectedSize, selectedOption3) {
        const matches = variants.filter(function(variant) {
            const colorMatch = colorSelect ? String(variant.color ?? '') === String(selectedColor ?? '') : true;
            const sizeMatch = sizeSelect ? String(variant.size ?? '') === String(selectedSize ?? '') : true;
            const extraMatch = option3Select ? String(variant.option3 ?? '') === String(selectedOption3 ?? '') : true;
            return colorMatch && sizeMatch && extraMatch;
        });
        if (!matches.length) return undefined;
        const inStockMatches = matches.filter(isInStock);
        if (inStockMatches.length === 1) return inStockMatches[0];
        if (inStockMatches.length > 1 || matches.length > 1) return undefined;
        return matches[0];
    }

    function markUnavailable(message) {
        if (stockMessage) {
            stockMessage.textContent = message || 'Combination unavailable';
            stockMessage.style.color = '#dc3545';
        }
        if (buyButton) {
            buyButton.disabled = true;
            buyButton.style.opacity = '0.5';
            buyButton.style.cursor = 'not-allowed';
        }
        form.dataset.inStock = 'false';
        form.dataset.variantId = '';
        form.action = '#';
        delete form.dataset.checkoutUrl;
    }
    
    function updateProduct() {
        const selectedColor = colorSelect ? colorSelect.value : undefined;
        const selectedSize = sizeSelect ? sizeSelect.value : undefined;
        const selectedOption3 = option3Select ? option3Select.value : undefined;
        const variant = findVariant(selectedColor, selectedSize, selectedOption3);
        
        if (!variant) {
            markUnavailable('Combination unavailable');
            return;
        }
        
        if (priceDisplay) {
            priceDisplay.textContent = `${variant.currency} ${variant.price}`;
        }
        
        const inStock = isInStock(variant);
        
        if (stockMessage) {
            if (inStock) {
                stockMessage.textContent = '✓ In Stock';
                stockMessage.style.color = '#28a745';
            } else {
                stockMessage.textContent = '✗ Out of Stock';
                stockMessage.style.color = '#dc3545';
            }
        }
        
        form.dataset.inStock = inStock ? 'true' : 'false';
        
        if (variant.image_index !== undefined && productImages.length > 0) {
            productImages.forEach(function(img, idx) {
                img.style.display = idx === variant.image_index ? 'block' : 'none';
            });
        }
        
        // Keep a live merchant action only for in-stock, allowlisted variants so
        // form.submit() cannot bypass the out-of-stock or origin guards.
        const checkoutHref = inStock && isAllowedCheckoutUrl(variant.url) ? variant.url : '';
        if (checkoutHref) {
            form.action = checkoutHref;
            form.dataset.checkoutUrl = checkoutHref;
            form.dataset.variantId = variant.id != null ? String(variant.id) : '';
        } else {
            form.action = '#';
            delete form.dataset.checkoutUrl;
            form.dataset.variantId = '';
        }
        if (buyButton) {
            const canBuy = inStock && Boolean(checkoutHref);
            buyButton.disabled = !canBuy;
            buyButton.style.opacity = canBuy ? '1' : '0.5';
            buyButton.style.cursor = canBuy ? 'pointer' : 'not-allowed';
        }
        form.dataset.sku = variant.sku == null ? '' : String(variant.sku);
        form.dataset.price = (variant.price == null || variant.price === '') ? '0' : String(variant.price);
        form.dataset.currency = variant.currency ? String(variant.currency) : (form.dataset.currency || 'USD');
        form.dataset.image = (variant.image && isSafeActionUrl(variant.image)) ? variant.image : '';
    }

    function applyInStockDefaults() {
        const current = findVariant(
            colorSelect ? colorSelect.value : undefined,
            sizeSelect ? sizeSelect.value : undefined,
            option3Select ? option3Select.value : undefined
        );
        if (current && isInStock(current)) {
            return;
        }
        const inStock = variants.find(isInStock);
        if (!inStock) {
            return;
        }
        if (colorSelect) {
            colorSelect.value = inStock.color != null ? inStock.color : '';
        }
        if (sizeSelect) {
            sizeSelect.value = inStock.size != null ? inStock.size : '';
        }
        if (option3Select) {
            option3Select.value = inStock.option3 != null ? inStock.option3 : '';
        }
    }
    
    if (colorSelect) {
        colorSelect.addEventListener('change', updateProduct);
    }
    
    if (sizeSelect) {
        sizeSelect.addEventListener('change', updateProduct);
    }

    if (option3Select) {
        option3Select.addEventListener('change', updateProduct);
    }
    
    applyInStockDefaults();
    updateProduct();
    
    if (quantityInput) {
        quantityInput.addEventListener('input', function() {
            const val = parseInt(this.value, 10);
            if (!Number.isFinite(val) || val < 1) this.value = 1;
            if (val > 99) this.value = 99;
        });
    }
})();

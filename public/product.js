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
        try { current = current.normalize('NFKC'); } catch (err) { /* ignore */ }
        for (let i = 0; i < 3; i++) {
            const next = current
                .replace(/&amp;/gi, '&')
                .replace(/&colon;/gi, ':')
                .replace(/&#0*58;/gi, ':')
                .replace(/&#x0*3a;/gi, ':');
            let folded = next;
            try { folded = next.normalize('NFKC'); } catch (err) { /* ignore */ }
            if (folded === current) break;
            current = folded;
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
            if (!(url.protocol === 'https:' || url.protocol === 'http:')) return false;
            return isPublicHttpHost(url.hostname);
        } catch (err) {
            return false;
        }
    }

    function isPublicHttpHost(host) {
        host = String(host || '').trim().toLowerCase().replace(/^\[|\]$/g, '');
        while (host.length > 1 && host.endsWith('.')) {
            host = host.slice(0, -1);
        }
        if (!host || host === 'localhost' || host === '0.0.0.0' || host === '::' || host === '::1') {
            return false;
        }
        if (/\.(localhost|local|internal|lan)$/.test(host)) return false;
        if (host === 'localtest.me' || /\.(nip\.io|sslip\.io|xip\.io|localtest\.me)$/.test(host)) {
            return false;
        }
        if (host.split('.').some(function(label) { return /^0x[0-9a-f]+$/i.test(label); })) {
            return false;
        }
        function blockedV4(a, b) {
            if (a === 0 || a === 10 || a === 127) return true;
            if (a === 192 && b === 168) return true;
            if (a === 172 && b >= 16 && b <= 31) return true;
            if (a === 169 && b === 254) return true;
            if (a === 100 && b >= 64 && b <= 127) return true;
            if (a >= 224) return true;
            return false;
        }
        const dotted = host.split('.');
        const decimalOctet = function(part) {
            return /^\d+$/.test(part) && !(part.length > 1 && part.charAt(0) === '0');
        };
        if (/^\d+(\.\d+){1,3}$/.test(host)) {
            if (!dotted.every(decimalOctet)) return false;
            const nums = dotted.map(Number);
            if (nums.some(function(n) { return n > 255; })) return false;
            while (nums.length < 4) nums.push(0);
            return !blockedV4(nums[0], nums[1]);
        }
        if (/^\d+$/.test(host)) {
            if (!decimalOctet(host)) return false;
            const value = Number(host);
            if (value < 0 || value > 0xffffffff) return false;
            return !blockedV4((value >>> 24) & 255, (value >>> 16) & 255);
        }
        if (host.indexOf(':') !== -1) {
            if (host === '::1' || host === '::') return false;
            if (/^64:ff9b:/i.test(host)) return false;
            const teredo = host.match(/^2001:([0-9a-f]{0,4}):/i);
            if (teredo && parseInt(teredo[1] || '0', 16) === 0) return false;
            if (/^2002:/i.test(host)) {
                const six = host.match(/^2002:([0-9a-f]{0,4}):([0-9a-f]{0,4})/i);
                if (!six) return false;
                const hi = parseInt(six[1] || '0', 16);
                return !blockedV4((hi >> 8) & 255, hi & 255);
            }
            const dottedTail = host.match(/(?:^|:)(\d+\.\d+\.\d+\.\d+)$/);
            if (dottedTail) {
                const parts = dottedTail[1].split('.').map(Number);
                if (parts.some(function(n) { return n > 255; })) return false;
                return !blockedV4(parts[0], parts[1]);
            }
            const compactCompat = host.match(/^:?:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i);
            if (compactCompat && !/:ffff:/i.test(host)) {
                const hi = parseInt(compactCompat[1], 16);
                return !blockedV4((hi >> 8) & 255, hi & 255);
            }
            const hextets = host.split(':');
            if (hextets.length === 8 && hextets.every(function(part) { return /^[0-9a-f]{0,4}$/.test(part); })) {
                const nums = hextets.map(function(part) { return parseInt(part || '0', 16); });
                if (nums[5] === 0xffff || (nums[4] === 0xffff && nums[5] === 0) || nums.slice(0, 6).every(function(n) { return n === 0; })) {
                    return !blockedV4((nums[6] >> 8) & 255, nums[6] & 255);
                }
            }
            const mappedHex = host.match(/(?:^|:)ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i);
            if (mappedHex) {
                const hi = parseInt(mappedHex[1], 16);
                return !blockedV4((hi >> 8) & 255, hi & 255);
            }
            const first = host.split(':').find(function(part) { return part.length; }) || '0';
            const n = parseInt(first, 16);
            if (!isNaN(n) && ((n & 0xfe00) === 0xfc00 || (n & 0xffc0) === 0xfe80 || (n & 0xff00) === 0xff00)) {
                return false;
            }
            return true;
        }
        return host.indexOf('.') !== -1 && host.charAt(0) !== '.';
    }

    function allowedCheckoutOrigins() {
        const meta = document.querySelector('meta[name="gang-checkout-origins"]');
        if (!meta) return new Set();
        const origins = String(meta.content || '').split(/\s+/).map(s => s.trim()).filter(Boolean);
        return new Set(origins.flatMap(function(s) {
            try {
                const parsed = new URL(s);
                if (parsed.username) return [];
                if (!(parsed.protocol === 'https:' || parsed.protocol === 'http:')) return [];
                if (!isPublicHttpHost(parsed.hostname)) return [];
                return [parsed.origin];
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

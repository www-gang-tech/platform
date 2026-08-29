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
        const avail = String((variant && variant.availability) || '');
        return avail.indexOf('InStock') !== -1 && avail.indexOf('OutOfStock') === -1;
    }
    
    function isSafeActionUrl(value) {
        if (!value || typeof value !== 'string') return false;
        if (value.charAt(0) === '/' && value.charAt(1) !== '/') return true;
        try {
            const url = new URL(value, window.location.origin);
            return url.protocol === 'https:' || url.protocol === 'http:';
        } catch (err) {
            return false;
        }
    }
    
    function findVariant(selectedColor, selectedSize, selectedOption3) {
        const matches = variants.filter(function(variant) {
            const colorMatch = !selectedColor || variant.color === selectedColor;
            const sizeMatch = !selectedSize || variant.size === selectedSize;
            const extraMatch = !selectedOption3 || variant.option3 === selectedOption3;
            return colorMatch && sizeMatch && extraMatch;
        });
        return matches.find(isInStock) || matches[0];
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
        
        if (buyButton) {
            buyButton.disabled = !inStock;
            buyButton.style.opacity = inStock ? '1' : '0.5';
            buyButton.style.cursor = inStock ? 'pointer' : 'not-allowed';
        }
        form.dataset.inStock = inStock ? 'true' : 'false';
        
        if (variant.image_index !== undefined && productImages.length > 0) {
            productImages.forEach(function(img, idx) {
                img.style.display = idx === variant.image_index ? 'block' : 'none';
            });
        }
        
        // Keep a live merchant action only for in-stock variants so form.submit()
        // cannot bypass the out-of-stock guard.
        const checkoutHref = inStock && isSafeActionUrl(variant.url) ? variant.url : '';
        if (checkoutHref) {
            form.action = checkoutHref;
            form.dataset.checkoutUrl = checkoutHref;
        } else {
            form.action = '#';
            delete form.dataset.checkoutUrl;
        }
        form.dataset.variantId = variant.id == null ? '' : String(variant.id);
        form.dataset.sku = variant.sku == null ? '' : String(variant.sku);
        form.dataset.price = (variant.price == null || variant.price === '') ? '0' : String(variant.price);
        if (variant.currency) {
            form.dataset.currency = String(variant.currency);
        }
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
            colorSelect.value = inStock.color || '';
        }
        if (sizeSelect) {
            sizeSelect.value = inStock.size || '';
        }
        if (option3Select) {
            option3Select.value = inStock.option3 || '';
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

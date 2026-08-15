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
    const quantityInput = form.querySelector('[name="quantity"]');
    const priceDisplay = document.querySelector('[data-price]');
    const stockMessage = document.querySelector('[data-stock-message]');
    const buyButton = form.querySelector('[type="submit"]');
    const productImages = document.querySelectorAll('[data-variant-image]');
    
    const variantsData = document.getElementById('variants-data');
    const variants = variantsData ? JSON.parse(variantsData.textContent) : [];
    
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
    
    function findVariant(selectedColor, selectedSize) {
        const matches = variants.filter(function(variant) {
            const colorMatch = !selectedColor || variant.color === selectedColor;
            const sizeMatch = !selectedSize || variant.size === selectedSize;
            return colorMatch && sizeMatch;
        });
        return matches.find(isInStock) || matches[0];
    }
    
    function updateProduct() {
        const selectedColor = colorSelect ? colorSelect.value : undefined;
        const selectedSize = sizeSelect ? sizeSelect.value : undefined;
        const variant = findVariant(selectedColor, selectedSize);
        
        if (!variant) return;
        
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
        
        if (variant.image_index !== undefined && productImages.length > 0) {
            productImages.forEach(function(img, idx) {
                img.style.display = idx === variant.image_index ? 'block' : 'none';
            });
        }
        
        if (isSafeActionUrl(variant.url)) {
            form.action = variant.url;
        }
        if (variant.id) {
            form.dataset.variantId = String(variant.id);
        }
        if (variant.sku) {
            form.dataset.sku = String(variant.sku);
        }
        if (variant.price !== undefined && variant.price !== null) {
            form.dataset.price = String(variant.price);
        }
        if (variant.currency) {
            form.dataset.currency = String(variant.currency);
        }
    }

    function applyInStockDefaults() {
        const current = findVariant(
            colorSelect ? colorSelect.value : undefined,
            sizeSelect ? sizeSelect.value : undefined
        );
        if (current && isInStock(current)) {
            return;
        }
        const inStock = variants.find(isInStock);
        if (!inStock) {
            return;
        }
        if (colorSelect && inStock.color) {
            colorSelect.value = inStock.color;
        }
        if (sizeSelect && inStock.size) {
            sizeSelect.value = inStock.size;
        }
    }
    
    if (colorSelect) {
        colorSelect.addEventListener('change', updateProduct);
    }
    
    if (sizeSelect) {
        sizeSelect.addEventListener('change', updateProduct);
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

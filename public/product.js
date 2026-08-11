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
    const materialSelect = form.querySelector('[name="material"]');
    const quantityInput = form.querySelector('[name="quantity"]');
    const priceDisplay = document.querySelector('[data-price]');
    const stockMessage = document.querySelector('[data-stock-message]');
    const buyButton = form.querySelector('[type="submit"]');
    const productImages = document.querySelectorAll('[data-variant-image]');
    
    // Get all variant data from hidden input
    const variantsData = document.getElementById('variants-data');
    let variants = [];
    if (variantsData) {
        try {
            variants = JSON.parse(variantsData.textContent || '[]');
            if (!Array.isArray(variants)) {
                variants = [];
            }
        } catch (e) {
            // Keep progressive enhancement working when variant JSON is malformed.
            variants = [];
        }
    }

    function merchantCheckoutHref(rawUrl) {
        // Reject empty/fragment placeholders that resolve to this origin.
        if (!rawUrl || rawUrl === '#' || rawUrl === '/') {
            return '';
        }
        try {
            // Absolute URLs only — relative/'#' would become this site.
            const parsed = new URL(rawUrl);
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                return '';
            }
            return parsed.href;
        } catch (e) {
            return '';
        }
    }

    function clearCheckoutIdentity() {
        form.action = '#';
        delete form.dataset.checkoutUrl;
        form.dataset.variantId = '';
        form.dataset.sku = '';
        if (buyButton) {
            buyButton.disabled = true;
            buyButton.style.opacity = '0.5';
            buyButton.style.cursor = 'not-allowed';
        }
        if (stockMessage) {
            stockMessage.textContent = 'Select an available option';
            stockMessage.style.color = '#dc3545';
        }
    }
    
    function updateProduct() {
        const selectedColor = colorSelect?.value;
        const selectedSize = sizeSelect?.value;
        const selectedMaterial = materialSelect?.value;
        
        // Find matching variant (include option3/material when present).
        const variant = variants.find(v => {
            const colorMatch = !selectedColor || v.color === selectedColor;
            const sizeMatch = !selectedSize || v.size === selectedSize;
            const materialMatch = !selectedMaterial || v.material === selectedMaterial;
            return colorMatch && sizeMatch && materialMatch;
        });
        
        // Impossible combo must not keep the previous variant identity.
        if (!variant) {
            clearCheckoutIdentity();
            return;
        }
        
        // Update price
        if (priceDisplay) {
            priceDisplay.textContent = `${variant.currency} ${variant.price}`;
        }
        
        // Update stock message
        const inStock = variant.availability === 'https://schema.org/InStock' || 
                       variant.availability === 'InStock';
        
        if (stockMessage) {
            if (inStock) {
                stockMessage.textContent = '✓ In Stock';
                stockMessage.style.color = '#28a745';
            } else {
                stockMessage.textContent = '✗ Out of Stock';
                stockMessage.style.color = '#dc3545';
            }
        }
        
        // Enable/disable buy button
        if (buyButton) {
            buyButton.disabled = !inStock;
            buyButton.style.opacity = inStock ? '1' : '0.5';
            buyButton.style.cursor = inStock ? 'pointer' : 'not-allowed';
        }
        
        // Update product image based on variant's image index
        if (variant.image_index !== undefined && productImages.length > 0) {
            productImages.forEach((img, idx) => {
                img.style.display = idx === variant.image_index ? 'block' : 'none';
            });
        }
        
        // Update form action to point to correct variant URL (absolute http/https only).
        // Always clear/replace — truthy checks left stale checkout identity when
        // switching to a variant with empty SKU, zero price, or missing URL.
        const checkoutHref = merchantCheckoutHref(variant.url);
        if (checkoutHref) {
            form.action = checkoutHref;
            form.dataset.checkoutUrl = checkoutHref;
        } else {
            form.action = '#';
            delete form.dataset.checkoutUrl;
        }

        // Keep cart data aligned with the selected Shopify variant.
        form.dataset.variantId = variant.id == null ? '' : String(variant.id);
        form.dataset.sku = variant.sku == null ? '' : String(variant.sku);
        form.dataset.price = variant.price == null || variant.price === ''
            ? '0'
            : String(variant.price);
        form.dataset.currency = variant.currency ? String(variant.currency) : 'USD';
        if (Object.prototype.hasOwnProperty.call(variant, 'image') && variant.image) {
            form.dataset.image = String(variant.image);
        }
    }
    
    // Listen for changes
    if (colorSelect) {
        colorSelect.addEventListener('change', updateProduct);
    }
    
    if (sizeSelect) {
        sizeSelect.addEventListener('change', updateProduct);
    }

    if (materialSelect) {
        materialSelect.addEventListener('change', updateProduct);
    }
    
    // Initial update
    updateProduct();
    
    // Quantity validation
    if (quantityInput) {
        quantityInput.addEventListener('input', function() {
            const val = parseInt(this.value);
            if (val < 1) this.value = 1;
            if (val > 99) this.value = 99;
        });
    }
})();

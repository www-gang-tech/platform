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
    
    // Get all variant data from hidden input
    const variantsData = document.getElementById('variants-data');
    const variants = variantsData ? JSON.parse(variantsData.textContent) : [];
    
    function updateProduct() {
        const selectedColor = colorSelect?.value;
        const selectedSize = sizeSelect?.value;
        
        // Find matching variant
        const variant = variants.find(v => {
            const colorMatch = !selectedColor || v.color === selectedColor;
            const sizeMatch = !selectedSize || v.size === selectedSize;
            return colorMatch && sizeMatch;
        });
        
        if (!variant) return;
        
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
        
        // Update form action to point to correct variant URL
        if (variant.url) {
            form.action = variant.url;
        }
    }
    
    // Listen for changes
    if (colorSelect) {
        colorSelect.addEventListener('change', updateProduct);
    }
    
    if (sizeSelect) {
        sizeSelect.addEventListener('change', updateProduct);
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


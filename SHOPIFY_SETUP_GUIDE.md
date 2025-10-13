# Shopify Integration Setup

## Your Store

**Store URL:** www-gang-tech.myshopify.com ✅
**Status:** Ready to connect

## Quick Setup (5 minutes)

### Step 1: Get API Token

1. Go to: https://admin.shopify.com/store/www-gang-tech/settings/apps

2. Scroll down and click **"Develop apps"**

3. Click **"Create an app"**
   - Name: GANG Platform
   - Click "Create app"

4. Click **"Configure Admin API scopes"**

5. Enable these permissions:
   - ✅ `read_products`
   - ✅ `read_product_listings`
   - ✅ `read_inventory` (optional)

6. Click **"Save"**

7. Go to **"API credentials"** tab

8. Click **"Install app"**

9. Copy the **"Admin API access token"**
   - Starts with `shpat_`
   - Keep this secret!

### Step 2: Configure GANG

```bash
# Add to your environment
export SHOPIFY_STORE_URL=www-gang-tech.myshopify.com
export SHOPIFY_ACCESS_TOKEN=shpat_your_token_here

# Test the connection
gang products sync
```

### Step 3: Verify

You should see:
```
🛒 Syncing products...
✅ Fetched X product(s)
  • Your Product 1 (from shopify)
  • Your Product 2 (from shopify)
  ...
```

## What Happens Next

1. **Products are fetched** from Shopify API
2. **Normalized to Schema.org** format
3. **Cached locally** in `.products-cache.json`
4. **Product pages generated** in `/products/`
5. **JSON API created** at `/api/products.json`
6. **AgentMap updated** with product info

## Testing Without API Token

The system works in demo mode:
```bash
gang products sync  # Uses demo products
gang products list  # Shows 3 demo products
```

Once you add your real token, it fetches your actual products!

## Troubleshooting

### Error: "403 Forbidden"
- API token doesn't have required permissions
- Go back to step 4 and enable `read_products`

### Error: "Store not found"
- Check store URL is correct: `www-gang-tech.myshopify.com`
- No https://, no trailing slash

### Products not showing
- Run `gang products sync` first
- Check `.products-cache.json` exists
- Verify products exist in your Shopify store

## What Gets Synced

From Shopify, we fetch:
- Product title
- Description
- Images
- Variants (sizes, colors, etc.)
- Prices
- SKUs
- Availability
- Product URLs

All normalized to Schema.org for:
- Google Shopping
- AI agents
- SEO optimization

## Commands

```bash
# Sync products from Shopify
gang products sync

# View synced products
gang products list

# View as JSON
gang products list --format json

# Build product pages
gang build  # (once build bug is fixed)
```

## Next Steps

1. Get your API token (5 min)
2. Export environment variables
3. Run `gang products sync`
4. Check `.products-cache.json`
5. Build and deploy!

**Your Shopify products will be:**
- ✅ Static pages (ultra-fast)
- ✅ SEO optimized (Schema.org)
- ✅ Accessible (WCAG AA)
- ✅ No Shopify fees on traffic
- ✅ Full control over design


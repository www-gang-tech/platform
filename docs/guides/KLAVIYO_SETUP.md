# Klaviyo Integration for GANG Platform

## Why Klaviyo + Shopify?

**Perfect for e-commerce** because Klaviyo:
- ✅ **Native Shopify integration** - Syncs products, orders, customers automatically
- ✅ **Abandoned cart recovery** - Recovers 10-15% of lost sales
- ✅ **Product recommendations** - AI-powered, increases AOV
- ✅ **Revenue attribution** - See exactly how much $ each email generates
- ✅ **Customer segmentation** - RFM analysis, predictive analytics
- ✅ **SMS + Email** - Unified platform
- ✅ **Post-purchase flows** - Thank you, review requests, upsells

---

## Setup Guide

### 1. Create Klaviyo Account

1. Go to [klaviyo.com](https://www.klaviyo.com)
2. Sign up (free for up to 250 contacts)
3. Connect your Shopify store (one-click integration)

### 2. Get API Key

1. Go to **Settings** → **Account** → **API Keys**
2. Create **Private API Key** (full access)
3. Copy the key (starts with `pk_`)

### 3. Configure GANG

Add to your `.env` file:

```bash
KLAVIYO_API_KEY=pk_your_private_key_here
```

### 4. Connect Shopify

Klaviyo will automatically:
- ✅ Import all products
- ✅ Import all customers
- ✅ Track orders in real-time
- ✅ Track cart events
- ✅ Track product views

---

## CLI Commands

### Create Campaign from Post

```bash
# Get your list ID first
gang email klaviyo-lists

# Create campaign
gang email klaviyo-create content/posts/my-post.md \
  --list-id YOUR_LIST_ID \
  --from-email newsletter@yourdomain.com \
  --from-name "GANG"
```

### List Your Lists

```bash
gang email klaviyo-lists
```

### View Campaigns

```bash
# Draft campaigns
gang email klaviyo-campaigns --status draft

# Sent campaigns
gang email klaviyo-campaigns --status sent
```

---

## Recommended Flows

### 1. Abandoned Cart (Must-Have)

**ROI:** Recovers 10-15% of abandoned carts

**Setup in Klaviyo:**
1. Go to **Flows** → **Create Flow** → **Abandoned Cart**
2. Use Klaviyo's template
3. Customize timing:
   - Email 1: 1 hour after abandonment
   - Email 2: 24 hours (with 10% discount)
   - Email 3: 48 hours (final reminder)

**Expected Results:**
- Open rate: 40-50%
- Click rate: 15-20%
- Conversion rate: 5-10%
- Revenue: $500-2,000/month (varies by AOV)

### 2. Welcome Series

**ROI:** Builds relationship, drives first purchase

**Flow:**
1. Immediate: Welcome email
2. Day 3: Brand story + best sellers
3. Day 7: First purchase discount

### 3. Post-Purchase

**ROI:** Increases LTV, builds loyalty

**Flow:**
1. Immediate: Order confirmation
2. Day 3: How to use product
3. Day 14: Review request
4. Day 30: Complementary product recommendation

### 4. Browse Abandonment

**ROI:** Captures interest before cart

**Flow:**
1. Customer views product but doesn't add to cart
2. Wait 4 hours
3. Send email with product + similar items

### 5. Customer Win-Back

**ROI:** Re-engages inactive customers

**Flow:**
1. No purchase in 90 days
2. Send "We miss you" email
3. Offer 15% discount
4. Highlight new products

---

## Klaviyo + GANG Workflow

### For Content Newsletters

```bash
# 1. Write post in Studio
# 2. Build site
gang build

# 3. Create Klaviyo campaign
gang email klaviyo-create content/posts/my-article.md \
  --list-id YOUR_NEWSLETTER_LIST

# 4. Review in Klaviyo dashboard
# 5. Schedule send
```

### For Product Launches

```bash
# 1. Sync products from Shopify
gang products sync

# 2. Product appears on site automatically

# 3. Klaviyo detects new product (automatic)

# 4. Create campaign in Klaviyo dashboard
#    (or use CLI to create from template)

# 5. Send to VIP segment first
# 6. Send to full list 24 hours later
```

### For Abandoned Carts

**Automatic!** Klaviyo handles this once you set up the flow.

---

## Segmentation Strategies

### 1. VIP Customers
- Placed 3+ orders
- Total spend >$500
- Last purchase <90 days

**Use for:** Early access, exclusive offers

### 2. At-Risk Customers
- Placed 1+ orders
- No purchase in 90+ days
- High engagement (opens emails)

**Use for:** Win-back campaigns

### 3. High AOV Customers
- Average order value >$100

**Use for:** Premium product launches

### 4. Engaged Non-Buyers
- Opens emails regularly
- Clicks products
- Never purchased

**Use for:** First purchase incentive

---

## Email Types

### Content Newsletters (Buttondown OR Klaviyo)

**Buttondown:**
- ✅ Simpler, cheaper
- ✅ Better for pure content
- ✅ Privacy-focused

**Klaviyo:**
- ✅ Better segmentation
- ✅ Product recommendations
- ✅ Revenue tracking

**Recommendation:** Use Klaviyo if you want to include product recommendations in newsletters.

### E-commerce Emails (Klaviyo ONLY)

- Abandoned cart
- Order confirmations
- Shipping notifications
- Review requests
- Product recommendations
- Win-back campaigns

---

## Cost Comparison

### Buttondown
- Free: 100 subscribers
- $9/mo: 1,000 subscribers
- $29/mo: 10,000 subscribers

### Klaviyo
- Free: 250 contacts (500 emails/mo)
- $20/mo: 500 contacts
- $60/mo: 1,500 contacts
- $150/mo: 5,000 contacts
- $700/mo: 20,000 contacts

**Note:** Klaviyo charges by contacts, not subscribers. A contact is anyone who's interacted with your store (customer, subscriber, cart abandoner).

---

## Recommended Setup for GANG

### Option 1: Klaviyo Only (Simple)

**Use Klaviyo for everything:**
- Content newsletters
- Product launches
- Abandoned carts
- All e-commerce flows

**Cost:** $20-60/mo depending on list size

**Pros:**
- Single platform
- Unified analytics
- Product recommendations in newsletters

**Cons:**
- More expensive
- Overkill for simple newsletters

### Option 2: Buttondown + Klaviyo (Optimized)

**Buttondown for:**
- Weekly/monthly content newsletter
- Blog post notifications
- Company updates

**Klaviyo for:**
- Abandoned cart
- Product launches (to customers)
- Order confirmations
- Review requests
- Win-back campaigns

**Cost:** $9 (Buttondown) + $20 (Klaviyo) = $29/mo

**Pros:**
- Best tool for each job
- Lower cost
- Privacy-focused content newsletter

**Cons:**
- Two platforms to manage
- Separate analytics

---

## My Recommendation for You

**Start with Klaviyo only** because:

1. ✅ You already have Shopify
2. ✅ You need abandoned cart recovery (immediate ROI)
3. ✅ You can send content newsletters through Klaviyo
4. ✅ Unified customer data
5. ✅ Product recommendations boost revenue

**Later, add Buttondown if:**
- You're sending lots of content newsletters (not product-focused)
- You want to separate content from commerce
- You want a simpler, privacy-focused newsletter tool

---

## Next Steps

### 1. Install Klaviyo on Shopify

1. Go to Shopify App Store
2. Install "Klaviyo: Email Marketing & SMS"
3. Connect your account
4. Wait 24 hours for full data sync

### 2. Set Up Flows

**Priority order:**
1. ✅ Abandoned Cart (highest ROI)
2. ✅ Welcome Series (builds relationship)
3. ✅ Post-Purchase (increases LTV)
4. ✅ Browse Abandonment (captures interest)
5. ✅ Win-Back (re-engages inactive)

### 3. Create First Campaign

```bash
export KLAVIYO_API_KEY=your_key
gang email klaviyo-create content/posts/qi2-launch.md \
  --from-email hello@yourdomain.com \
  --from-name "GANG"
```

### 4. Set Up DNS

```bash
gang email check-deliverability yourdomain.com
```

Follow the guide to add SPF/DKIM/DMARC records.

### 5. Monitor & Optimize

**Week 1:**
- Check deliverability (aim for >98%)
- Monitor bounce rate (<2%)
- Test all flows

**Week 2-4:**
- A/B test subject lines
- Optimize send times
- Refine segmentation

**Month 2+:**
- Analyze revenue attribution
- Optimize flow timing
- Add advanced segments

---

## Expected Results

### Abandoned Cart Flow
- **Recovery rate:** 10-15% of abandoned carts
- **Revenue:** $500-2,000/month (varies by traffic & AOV)
- **ROI:** 30-50x (Klaviyo pays for itself many times over)

### Welcome Series
- **First purchase rate:** 15-25% of new subscribers
- **Time to first purchase:** Reduced by 30-40%

### Product Launch Campaigns
- **Open rate:** 25-35%
- **Click rate:** 5-10%
- **Conversion rate:** 2-5%

---

## Resources

- **Klaviyo Help:** [help.klaviyo.com](https://help.klaviyo.com)
- **API Docs:** [developers.klaviyo.com](https://developers.klaviyo.com)
- **Shopify Integration:** [klaviyo.com/shopify](https://www.klaviyo.com/shopify)
- **Best Practices:** [klaviyo.com/blog](https://www.klaviyo.com/blog)

---

*Klaviyo is the industry standard for Shopify email marketing. With your GANG platform, you get the best of both worlds: static site performance + powerful e-commerce email automation.*


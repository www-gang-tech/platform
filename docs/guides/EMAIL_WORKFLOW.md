# Email Newsletter Workflow

## Overview

Convert any post into a newsletter email with minimal, accessible templates.

## Quick Start

### 1. Create Email from Post

```bash
gang email create-from-post content/posts/my-post.md
```

This generates:
- `emails/my-post-20251012.html` (HTML version)
- `emails/my-post-20251012.txt` (Plain text version)
- `emails/my-post-20251012.json` (Metadata)

### 2. Review Email

Open the HTML file in your browser to preview:

```bash
open emails/my-post-20251012.html
```

### 3. Send to ESP

```bash
export ESP_API_KEY=your_api_key
gang email send-draft my-post-20251012 --from-email newsletter@yourdomain.com
```

### 4. Approve & Send

Go to your ESP dashboard and:
1. Review the draft
2. Schedule or send immediately
3. Monitor delivery

---

## Email Template Features

### ✅ Accessibility
- Semantic HTML structure
- High contrast (WCAG AA)
- Alt text on all images
- Descriptive link text
- 16px base font size
- System fonts (no web fonts)

### ✅ Compatibility
- Works in all major email clients
- Outlook-compatible
- Mobile-responsive
- Single column layout (600px max)
- Table-based structure

### ✅ Privacy-First
- No open-tracking pixels
- No invisible images
- Track via click-throughs with UTM
- Measure on-site conversions

### ✅ Legal Compliance
- Unsubscribe link (ESP-managed)
- View in browser link
- Footer with sender info
- CAN-SPAM compliant

---

## ESP Providers

### Buttondown (Recommended)
**Why:** Simple, privacy-focused, great for indie publishers

```bash
gang email create-from-post content/posts/my-post.md --esp buttondown
export ESP_API_KEY=your_buttondown_key
gang email send-draft my-post-20251012 --from-email you@yourdomain.com
```

**Setup:**
1. Sign up at [buttondown.email](https://buttondown.email)
2. Get API key from Settings
3. Set `ESP_API_KEY` environment variable

### ConvertKit
**Why:** Creator-focused, powerful automation

```bash
gang email create-from-post content/posts/my-post.md --esp convertkit
```

### MailerLite
**Why:** Affordable, good UI, solid deliverability

```bash
gang email create-from-post content/posts/my-post.md --esp mailerlite
```

### Postmark
**Why:** Transactional + broadcast, excellent deliverability

```bash
gang email create-from-post content/posts/my-post.md --esp postmark
```

### SendGrid
**Why:** Enterprise-grade, detailed analytics

```bash
gang email create-from-post content/posts/my-post.md --esp sendgrid
```

---

## Deliverability Setup

### Check Your DNS

```bash
gang email check-deliverability yourdomain.com
```

This checks for:
- SPF record
- DMARC record
- MX records

### Required DNS Records

#### 1. SPF Record
```
Host: @
Type: TXT
Value: v=spf1 include:_spf.buttondown.email ~all
```

#### 2. DKIM Record
Your ESP will provide this. Example:
```
Host: buttondown._domainkey
Type: TXT
Value: [Provided by ESP]
```

#### 3. DMARC Record
```
Host: _dmarc
Type: TXT
Value: v=DMARC1; p=quarantine; rua=mailto:dmarc@yourdomain.com; pct=100
```

### Dedicated Sending Subdomain

**Recommended:** Use `news.yourdomain.com` or `mail.yourdomain.com`

**Benefits:**
- Isolates reputation
- Better deliverability
- Cleaner analytics
- Protects main domain

**Setup:**
1. Create subdomain in DNS
2. Add SPF/DKIM/DMARC for subdomain
3. Configure ESP to use subdomain
4. Warm up subdomain gradually

---

## Workflow Integration

### Option 1: Manual (Simple)

1. Write post in Studio
2. Publish post (`gang build`)
3. Create email (`gang email create-from-post`)
4. Review HTML
5. Send to ESP
6. Approve in ESP dashboard
7. Schedule send

### Option 2: CI/CD (Automated)

**GitHub Actions Example:**

```yaml
name: Newsletter
on:
  push:
    paths:
      - 'content/posts/*.md'

jobs:
  create-email:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Create email draft
        run: |
          gang email create-from-post ${{ github.event.head_commit.modified[0] }}
          gang email send-draft $(ls emails/*.json | tail -1) \
            --from-email newsletter@yourdomain.com
        env:
          ESP_API_KEY: ${{ secrets.ESP_API_KEY }}
```

### Option 3: n8n (No-Code)

**Workflow:**
1. Trigger: Webhook (from `gang build`)
2. Action: Read post file
3. Action: Create email template
4. Action: Send to ESP API
5. Action: Wait for approval
6. Action: Schedule send

---

## Best Practices

### Content

✅ **Do:**
- Keep emails focused (one main idea)
- Use clear, descriptive subject lines
- Include preview text (first 50-100 chars)
- Add clear CTA
- Link to full post on website

❌ **Don't:**
- Use tiny fonts (<14px)
- Rely on images for content
- Use complex layouts
- Include too many CTAs
- Forget alt text

### Deliverability

✅ **Do:**
- Warm up new domains gradually
- Monitor bounce rates (<2%)
- Keep complaint rate low (<0.1%)
- Use double opt-in
- Clean inactive subscribers

❌ **Don't:**
- Send from no-reply@ addresses
- Buy email lists
- Send without permission
- Use misleading subject lines
- Forget unsubscribe link

### Privacy

✅ **Do:**
- Skip open-tracking pixels
- Use UTM parameters for clicks
- Measure on-site conversions
- Be transparent about data use
- Honor unsubscribes immediately

❌ **Don't:**
- Track without consent
- Share subscriber data
- Use invisible tracking images
- Sell email addresses

---

## Testing

### Before Sending

1. **Mail-Tester.com**
   - Aim for 10/10 score
   - Check spam triggers
   - Verify DNS records

2. **Email Client Testing**
   - Gmail (web + mobile)
   - Outlook (desktop + web)
   - Apple Mail
   - Yahoo Mail

3. **Accessibility**
   - Screen reader test
   - Keyboard navigation
   - Color contrast check
   - Alt text verification

4. **Links**
   - All links work
   - UTM parameters correct
   - Unsubscribe works
   - View in browser works

### Send Test Email

```bash
# Most ESPs support test sends
# Check your ESP documentation
```

---

## Monitoring

### Key Metrics

**Delivery:**
- Delivery rate (aim: >99%)
- Bounce rate (keep: <2%)
- Complaint rate (keep: <0.1%)

**Engagement:**
- Click-through rate (benchmark: 2-5%)
- On-site conversion rate
- Time on site from email
- Pages per session

**List Health:**
- Unsubscribe rate (benchmark: <0.5%)
- Growth rate
- Active vs. inactive subscribers

### Tools

- **ESP Dashboard:** Basic metrics
- **Google Analytics:** UTM tracking
- **Plausible/Fathom:** Privacy-friendly analytics
- **Cloudflare Analytics:** Server-side tracking

---

## Troubleshooting

### Email Goes to Spam

**Check:**
1. SPF/DKIM/DMARC records
2. Sender reputation
3. Content (spam triggers)
4. Engagement rates
5. Bounce rates

**Fix:**
- Use Mail-Tester.com
- Warm up domain
- Clean inactive subscribers
- Improve content quality

### Images Not Loading

**Check:**
1. Image URLs are absolute
2. Images are publicly accessible
3. No authentication required
4. Proper MIME types

### Links Not Working

**Check:**
1. URLs are absolute (not relative)
2. No localhost URLs
3. HTTPS enabled
4. No broken links

---

## Example Workflow

### Publishing a Post as Newsletter

```bash
# 1. Write post in Studio
# (content/posts/my-article.md)

# 2. Build site
gang build

# 3. Create email
gang email create-from-post content/posts/my-article.md

# 4. Review
open emails/my-article-20251012.html

# 5. Send to ESP
export ESP_API_KEY=your_key
gang email send-draft my-article-20251012 \
  --from-email newsletter@yourdomain.com

# 6. Approve in ESP dashboard

# 7. Schedule send

# 8. Monitor results
```

---

## Cost Estimate

### ESP Pricing (as of 2025)

**Buttondown:**
- Free: 100 subscribers
- $9/mo: 1,000 subscribers
- $29/mo: 10,000 subscribers

**ConvertKit:**
- Free: 1,000 subscribers
- $25/mo: 1,000 subscribers (premium)
- $50/mo: 3,000 subscribers

**MailerLite:**
- Free: 1,000 subscribers
- $10/mo: 1,000 subscribers (premium)
- $20/mo: 2,500 subscribers

**Postmark:**
- $15/mo: 10,000 emails
- Pay as you go: $1.25/1,000 emails

**SendGrid:**
- Free: 100 emails/day
- $19.95/mo: 50,000 emails
- $89.95/mo: 100,000 emails

---

*For most indie publishers: Start with Buttondown (free tier) or MailerLite*


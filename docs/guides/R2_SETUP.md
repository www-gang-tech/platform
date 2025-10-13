# Cloudflare R2 Media Storage Setup

**Complete guide to setting up unlimited media storage with zero egress fees.**

## Why Cloudflare R2?

### vs Other Options

| Feature | R2 | S3 | Git LFS |
|---------|----|----|---------|
| Storage cost | $0.015/GB | $0.023/GB | Included |
| **Egress cost** | **$0** 🎉 | $0.09/GB | Limited |
| Bandwidth | Unlimited | Pay per GB | 1GB/month free |
| CDN | Included | Extra cost | N/A |
| API | S3-compatible | Native | Git |

**Winner: R2** for any production site with images!

**Example savings:**
- 1TB bandwidth/month on S3: ~$90
- 1TB bandwidth/month on R2: **$0**
- **Savings: $90/month = $1,080/year!**

---

## Step-by-Step Setup

### Step 1: Create R2 Bucket

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Navigate to **R2 Object Storage**
3. Click **Create bucket**
4. Bucket name: `gang-media` (matches your config)
5. Location: **Automatic** (global distribution)
6. Click **Create bucket**

✅ Bucket created!

---

### Step 2: Enable Public Access (Optional)

**Option A: Public Bucket (Simple)**

1. Go to bucket settings
2. Enable **Public access**
3. Your media will be at: `https://pub-xxxxx.r2.dev/images/file.jpg`

**Option B: Custom Domain (Recommended)**

1. Go to bucket settings → **Connect Domain**
2. Add your domain: `media.yourdomain.com`
3. Update DNS (Cloudflare does this automatically)
4. Your media will be at: `https://media.yourdomain.com/images/file.jpg`

**Option C: Cloudflare Workers (Advanced)**

Use Workers for:
- Image resizing on-the-fly
- Access control
- Custom URLs
- Watermarks

---

### Step 3: Create API Token

1. In Cloudflare Dashboard → **R2**
2. Click **Manage R2 API Tokens**
3. Click **Create API Token**
4. Permissions:
   - ✅ Read (Object Read)
   - ✅ Write (Object Write)
5. Copy the credentials:
   - Access Key ID
   - Secret Access Key

⚠️ **Save these securely!** You won't see the secret again.

---

### Step 4: Configure Environment Variables

```bash
# Add to your .env file
cat >> .env << 'EOF'

# Cloudflare R2 Configuration
CLOUDFLARE_ACCOUNT_ID=your-account-id-here
CLOUDFLARE_R2_ACCESS_KEY_ID=your-access-key-id-here
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-secret-access-key-here
EOF

# Source the env file
source .env

# Or export directly
export CLOUDFLARE_ACCOUNT_ID=abc123
export CLOUDFLARE_R2_ACCESS_KEY_ID=xyz789
export CLOUDFLARE_R2_SECRET_ACCESS_KEY=secret123
```

**Where to find Account ID:**
- Cloudflare Dashboard → Any domain → **Account ID** in the sidebar

---

### Step 5: Update Config (Optional)

```yaml
# gang.config.yml
hosting:
  provider: "cloudflare"
  pages_project: "gang-platform"
  r2_bucket: "gang-media"
  r2_custom_domain: "media.yourdomain.com"  # If using custom domain
```

---

### Step 6: Test Upload

```bash
# Create test image
echo "test" > test.txt

# Upload to R2
gang media upload test.txt

# Output:
📤 Uploading test.txt to images/test.txt...
✅ Uploaded successfully (0.0KB)
📍 Public URL: https://media.yourdomain.com/images/test.txt

💡 Use in markdown:
   ![Alt text](https://media.yourdomain.com/images/test.txt)
```

✅ **R2 is working!**

---

## Usage Guide

### Upload Single File

```bash
gang media upload image.jpg

# Upload to specific path
gang media upload hero.jpg --path banners/hero.jpg
```

### Upload Directory

```bash
# Upload all images in a directory
gang media upload public/images/

# Result:
📁 Uploading directory: public/images/
✅ Uploaded 5 file(s) (2.3MB)
  ✓ hero.jpg
    https://media.yourdomain.com/images/hero.jpg
  ✓ product-1.jpg
    https://media.yourdomain.com/images/product-1.jpg
  ...
```

### List Files in R2

```bash
# List all files
gang media list

# List specific folder
gang media list --prefix images/

# Limit results
gang media list --limit 50
```

### Sync Directory

```bash
# Sync local directory to R2
gang media sync public/images/

# Sync with delete (removes remote files not in local)
gang media sync public/images/ --delete
```

### Delete File

```bash
gang media delete images/old-photo.jpg

# Asks for confirmation:
Delete images/old-photo.jpg from R2? [y/N]: y
✅ Deleted: images/old-photo.jpg
```

---

## Workflow Examples

### Scenario 1: Add New Image to Article

```bash
# 1. Upload image
gang media upload ~/Downloads/product.jpg --path images/products/widget.jpg

# Output:
✅ Uploaded successfully (145KB)
📍 Public URL: https://media.yourdomain.com/images/products/widget.jpg

# 2. Copy the URL and use in markdown
vim content/posts/product-launch.md

# Add:
![Widget product shot](https://media.yourdomain.com/images/products/widget.jpg)

# 3. Build and publish
gang build
```

---

### Scenario 2: Bulk Upload Existing Images

```bash
# 1. Organize images locally
mkdir -p media-to-upload/images
cp ~/Photos/*.jpg media-to-upload/images/

# 2. Upload all at once
gang media upload media-to-upload/

# 3. Get URLs
gang media list --prefix images/

# 4. Update markdown files with URLs
```

---

### Scenario 3: Sync Images Regularly

```bash
# Keep local and R2 in sync
gang media sync public/images/ --prefix images/

# Run this:
# - After adding new images
# - Before deploying
# - In CI/CD pipeline
```

---

## In Your Markdown

### Basic Image

```markdown
![Product shot](https://media.yourdomain.com/images/product.jpg)
```

### With AI-Generated Alt Text

```bash
# First upload
gang media upload product.jpg

# Then run optimizer (auto-generates alt text)
gang optimize

# Result in markdown:
![Professional product photography showing the widget in natural lighting](https://media.yourdomain.com/images/product.jpg)
```

---

## Custom Domain Setup

### Why Use Custom Domain?

✅ **Better branding:** `media.yourdomain.com` vs `pub-xxxxx.r2.dev`  
✅ **Easier to migrate:** Change backend without changing URLs  
✅ **SSL included:** Cloudflare handles certificates  
✅ **CDN optimized:** Global edge caching  

### Setup Steps

1. **In Cloudflare R2 Bucket Settings:**
   - Click "Connect Domain"
   - Enter: `media.yourdomain.com`

2. **Cloudflare handles:**
   - DNS configuration
   - SSL certificate
   - CDN setup

3. **Update your config:**
   ```yaml
   hosting:
     r2_custom_domain: "media.yourdomain.com"
   ```

4. **Use in markdown:**
   ```markdown
   ![Image](https://media.yourdomain.com/images/photo.jpg)
   ```

---

## CI/CD Integration

### Sync Media Before Deploy

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Sync media to R2
        env:
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CLOUDFLARE_R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          CLOUDFLARE_R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_KEY }}
        run: gang media sync public/images/ --prefix images/
      
      - name: Build site
        run: gang build
      
      - name: Deploy to Cloudflare Pages
        run: wrangler pages deploy dist/
```

**Add secrets to GitHub:**
- `CLOUDFLARE_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_KEY`

---

## Security Best Practices

### 1. Keep Credentials Secret

```bash
# ✅ GOOD: Use environment variables
export CLOUDFLARE_R2_ACCESS_KEY_ID=xxx

# ✅ GOOD: Use .env file (add to .gitignore)
echo "CLOUDFLARE_R2_ACCESS_KEY_ID=xxx" >> .env

# ❌ BAD: Commit to git
echo "access_key: xxx" >> gang.config.yml  # DON'T!
```

### 2. Add .env to .gitignore

```bash
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Ignore .env file"
```

### 3. Use Least Privilege

API token permissions:
- ✅ Read + Write to specific bucket
- ❌ Account-wide admin access

### 4. Rotate Keys Regularly

```bash
# Every 90 days:
# 1. Create new API token
# 2. Update .env
# 3. Test: gang media list
# 4. Delete old token
```

---

## Troubleshooting

### "R2 not configured"

**Problem:** Missing environment variables

**Solution:**
```bash
# Check what's missing
gang media upload test.jpg

# Output shows missing vars:
❌ R2 not configured. Missing environment variables:
  - CLOUDFLARE_ACCOUNT_ID
  - CLOUDFLARE_R2_ACCESS_KEY_ID
  - CLOUDFLARE_R2_SECRET_ACCESS_KEY

# Add them to .env
```

### "Access Denied"

**Problem:** API token doesn't have permissions

**Solution:**
- Recreate API token with Read + Write
- Check bucket name matches config
- Verify account ID

### "Bucket not found"

**Problem:** Bucket name mismatch

**Solution:**
```yaml
# gang.config.yml - must match bucket name exactly
hosting:
  r2_bucket: "gang-media"  # Must match Cloudflare
```

### "No module named 'boto3'"

**Problem:** boto3 not installed

**Solution:**
```bash
pip install boto3
# Or
pip install -r requirements.txt
```

---

## File Organization in R2

### Recommended Structure

```
gang-media/  (your R2 bucket)
├── images/
│   ├── posts/
│   │   ├── 2025/
│   │   │   └── product-launch.jpg
│   │   └── hero-shots/
│   ├── projects/
│   ├── authors/
│   └── general/
├── videos/
│   └── demos/
└── documents/
    └── pdfs/
```

### Upload with Structure

```bash
# Upload to organized paths
gang media upload product.jpg --path images/posts/2025/product-launch.jpg
gang media upload demo.mp4 --path videos/demos/onboarding.mp4
```

---

## Performance Tips

### 1. Optimize Before Upload

```bash
# Process images first
gang image public/images/ -o optimized/

# Then upload optimized versions
gang media upload optimized/ --prefix images/
```

### 2. Use Appropriate Formats

```
Photos: AVIF > WebP > JPEG
Graphics: WebP > PNG
Icons: SVG (no upload needed, use Git)
Videos: H.264/H.265 MP4
```

### 3. Lazy Loading

```markdown
<!-- All R2 images should be lazy-loaded -->
![Description](https://media.yourdomain.com/images/photo.jpg)

<!-- Becomes in HTML -->
<img src="..." alt="Description" loading="lazy" decoding="async">
```

### 4. Responsive Images

```bash
# Generate multiple sizes
gang image hero.jpg -o variants/

# Upload all variants
gang media upload variants/ --prefix images/hero/

# Use in markdown with picture element
```

---

## Costs Breakdown

### Your Projected Costs

**Assumptions:**
- 100 images (~50MB)
- 10,000 pageviews/month
- 1M image requests/month

**Monthly costs:**
```
Storage (50MB):        $0.00075
Class B operations:    $0.36
Egress:                $0 (FREE!)
─────────────────────────────
Total:                 ~$0.36/month
```

**Compare to S3:**
```
Storage:               $0.00115
Operations:            $0.40
Egress (50GB):         $4.50
─────────────────────────────
Total:                 ~$5/month

Savings with R2: $4.64/month ($55/year)
```

---

## Next Steps

### 1. Create R2 Bucket

Go to: https://dash.cloudflare.com → R2 Object Storage → Create Bucket

### 2. Get Credentials

Go to: R2 → Manage API Tokens → Create Token

### 3. Configure

```bash
# Add to .env
echo "CLOUDFLARE_ACCOUNT_ID=your-account-id" >> .env
echo "CLOUDFLARE_R2_ACCESS_KEY_ID=your-access-key" >> .env
echo "CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-secret-key" >> .env

# Load environment
source .env
```

### 4. Test Upload

```bash
# Upload test file
echo "test" > test.txt
gang media upload test.txt

# Should see:
✅ Uploaded successfully
📍 Public URL: https://...
```

### 5. Use in Content

```markdown
![My Image](https://media.yourdomain.com/images/photo.jpg)
```

---

## Commands Reference

```bash
# Upload single file
gang media upload image.jpg
gang media upload image.jpg --path custom/path.jpg

# Upload directory
gang media upload images/

# List files
gang media list
gang media list --prefix images/

# Sync directory
gang media sync public/images/
gang media sync public/images/ --delete

# Delete file
gang media delete images/old.jpg
```

---

## What You Get

✅ **Unlimited bandwidth** - Zero egress fees  
✅ **Global CDN** - Fast worldwide  
✅ **Simple CLI** - Upload in one command  
✅ **S3-compatible** - Use existing tools  
✅ **Version control** - Markdown stays in Git  
✅ **Scalable** - Handle any amount of media  

---

## Your Complete Workflow

### Adding Media to Posts

```bash
# 1. Upload image to R2
gang media upload ~/Downloads/hero.jpg --path images/posts/my-post-hero.jpg

# Output:
📍 Public URL: https://media.yourdomain.com/images/posts/my-post-hero.jpg

# 2. Copy URL to markdown
vim content/posts/my-post.md

# Add:
![Hero image](https://media.yourdomain.com/images/posts/my-post-hero.jpg)

# 3. (Optional) Generate alt text with AI
gang optimize

# 4. Build and publish
gang build
```

**That's it!** Media is on global CDN, markdown is in Git. Perfect separation.

---

## Pro Tips

### 1. Organize by Content

```
images/
  posts/           # Blog post images
  projects/        # Project screenshots
  authors/         # Author photos
  general/         # Reusable assets
```

### 2. Use Descriptive Names

```
✅ GOOD: product-iphone-15-front-view.jpg
❌ BAD:  IMG_1234.jpg
```

### 3. Optimize Before Upload

```bash
# Resize and compress locally first
gang image large-photo.jpg -o optimized/
gang media upload optimized/large-photo.jpg
```

### 4. Keep Originals Safe

```
Local:  ~/Originals/photos/  # High-res originals
R2:     images/              # Optimized for web
Git:    (markdown only)       # No binaries
```

---

## Migration from Git LFS

If you're currently using Git LFS:

```bash
# 1. Upload all LFS files to R2
gang media upload public/images/ --prefix images/

# 2. Get list of uploaded URLs
gang media list --prefix images/ > r2-urls.txt

# 3. Update markdown files to use R2 URLs
# (Search/replace /assets/images/ with https://media.yourdomain.com/images/)

# 4. Remove from Git LFS
git lfs untrack "public/images/**/*"
rm -rf public/images/
git add -A
git commit -m "Migrate images to R2"

# 5. Savings: Repo goes from 500MB to 5MB!
```

---

## Cloudflare Dashboard Quick Links

- **R2 Buckets:** https://dash.cloudflare.com → R2 Object Storage
- **API Tokens:** R2 → Manage R2 API Tokens
- **Usage Stats:** R2 → Analytics
- **Billing:** Account Home → Billing

---

## Ready to Set Up?

Follow these steps:

1. ✅ Create R2 bucket: `gang-media`
2. ✅ Get API credentials
3. ✅ Add to `.env` file
4. ✅ Test: `gang media upload test.jpg`
5. ✅ Upload your images
6. ✅ Use URLs in markdown
7. ✅ Build and deploy

**You'll have production-grade media storage in ~10 minutes!**

Need help with any step? I'm here!


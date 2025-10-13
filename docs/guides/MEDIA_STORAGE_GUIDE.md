# Media Storage Guide for GANG Platform

**How to store and manage images, videos, and media files in your CMS.**

## 🎯 Two Storage Strategies

### 1. **Cloudflare R2** (Recommended for Production)
- ✅ Unlimited bandwidth (no egress fees!)
- ✅ S3-compatible API
- ✅ Global CDN
- ✅ Keeps Git repo small
- ✅ Scales to any size

### 2. **Git + Git LFS** (Simple for Small Sites)
- ✅ Everything in one repo
- ✅ Version control for images
- ✅ Works with GitHub
- ✅ Good for small sites (<100MB)

---

## Option 1: Cloudflare R2 Setup

### Step 1: Create R2 Bucket

```bash
# In Cloudflare Dashboard:
# 1. Go to R2 Object Storage
# 2. Create bucket: "gang-media"
# 3. Set public access or configure Workers
```

### Step 2: Get API Credentials

```bash
# Cloudflare Dashboard → R2 → Manage R2 API Tokens
# Create API token with:
# - Read access
# - Write access (for uploads)
```

### Step 3: Configure Environment

```bash
# Add to .env
cat >> .env << 'EOF'
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_R2_ACCESS_KEY_ID=your-access-key
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-secret-key
EOF
```

### Step 4: Upload Media

```bash
# Using AWS CLI (R2 is S3-compatible)
aws s3 cp local-image.jpg s3://gang-media/images/ \
  --endpoint-url https://your-account-id.r2.cloudflarestorage.com \
  --profile r2

# Or use the gang CLI (we'll add this)
gang media upload image.jpg
```

### Step 5: Use in Markdown

```markdown
<!-- Reference R2 URL -->
![Product shot](https://media.your-domain.com/images/product.jpg)

<!-- Or use custom domain -->
![Product shot](https://cdn.your-domain.com/images/product.jpg)
```

---

## Option 2: Git + Git LFS (Simple Start)

### Step 1: Install Git LFS

```bash
# macOS
brew install git-lfs

# Initialize in repo
cd /path/to/gang-platform
git lfs install
```

### Step 2: Configure Git LFS

```bash
# Track image files
git lfs track "public/images/**/*.jpg"
git lfs track "public/images/**/*.png"
git lfs track "public/images/**/*.webp"
git lfs track "public/images/**/*.avif"
git lfs track "public/images/**/*.gif"

# Track video files (if needed)
git lfs track "public/videos/**/*.mp4"
git lfs track "public/videos/**/*.webm"

# Commit .gitattributes
git add .gitattributes
git commit -m "Configure Git LFS for media"
```

### Step 3: Add Images

```bash
# Create images directory
mkdir -p public/images

# Add your images
cp ~/Downloads/hero.jpg public/images/

# Commit (Git LFS handles large files)
git add public/images/hero.jpg
git commit -m "Add hero image"
git push
```

### Step 4: Use in Markdown

```markdown
<!-- Reference from public directory -->
![Hero image](/assets/images/hero.jpg)

<!-- During build, this becomes -->
<picture>
  <source type="image/avif" srcset="/assets/images/hero-640w.avif 640w, /assets/images/hero-1024w.avif 1024w">
  <source type="image/webp" srcset="/assets/images/hero-640w.webp 640w, /assets/images/hero-1024w.webp 1024w">
  <img src="/assets/images/hero-1024w.webp" alt="Hero image" loading="lazy" decoding="async">
</picture>
```

---

## Option 3: Hybrid Approach (Best of Both)

### Small Images in Git LFS

```bash
# Icons, logos, small assets (< 1MB each)
public/images/logo.svg
public/images/favicon.png
public/icons/
```

### Large Images in R2

```bash
# Photos, hero images, videos
https://media.your-domain.com/images/hero.jpg
https://media.your-domain.com/videos/demo.mp4
```

---

## GANG Media Upload Command

Let me create a media upload command for you:

```bash
# Upload to R2
gang media upload image.jpg

# Upload directory
gang media upload images/

# Sync directory
gang media sync public/images/
```

### Implementation

```python
# cli/gang/commands/media.py
@cli.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('--bucket', help='R2 bucket name (default from config)')
def upload(ctx, source, bucket):
    """Upload media to Cloudflare R2"""
    config = ctx.obj
    bucket_name = bucket or config['hosting']['r2_bucket']
    
    # Use boto3 (AWS SDK) for R2
    import boto3
    
    s3 = boto3.client(
        's3',
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['CLOUDFLARE_R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['CLOUDFLARE_R2_SECRET_ACCESS_KEY']
    )
    
    # Upload
    s3.upload_file(source, bucket_name, f'images/{Path(source).name}')
    click.echo(f"✅ Uploaded to {bucket_name}/images/{Path(source).name}")
```

---

## Recommended Workflow

### For Your Setup (Cloudflare)

1. **Small assets** → Git
   ```
   public/icons/     # SVG icons
   public/fonts/     # Web fonts
   ```

2. **Content images** → R2
   ```
   R2: gang-media/images/    # JPG, PNG, WebP
   R2: gang-media/videos/    # MP4, WebM
   ```

3. **Reference in markdown**
   ```markdown
   ![Hero](https://media.yourdomain.com/images/hero.jpg)
   ```

### During Build

```bash
# Build with image optimization
gang build --optimize-images

# Processes:
# 1. Local images in public/ → AVIF/WebP variants
# 2. References to R2 URLs → Pass through
# 3. External images → Warning (recommend hosting locally)
```

---

## Studio CMS Integration

### Future: Media Library in Studio

```
┌─────────────────────────────────────┐
│  📁 Media Library                   │
│                                     │
│  [Upload]  [From R2]  [From URL]    │
│                                     │
│  📸 Images (23)                     │
│  ├─ hero.jpg (1.2MB)                │
│  ├─ product-1.jpg (450KB)           │
│  └─ logo.png (12KB)                 │
│                                     │
│  🎬 Videos (2)                      │
│  └─ demo.mp4 (5.2MB)                │
│                                     │
│  [Insert into Editor]               │
└─────────────────────────────────────┘
```

**Features:**
- Drag & drop upload to R2
- Auto-generate responsive variants
- Copy markdown snippet
- AI-generated alt text
- Organize into folders

---

## Quick Start: Add Your First Image

### Using Git (Simple)

```bash
# 1. Create images directory
mkdir -p public/images

# 2. Add an image
cp ~/Downloads/my-image.jpg public/images/

# 3. Use in markdown
echo '![My Image](/assets/images/my-image.jpg)' >> content/posts/my-post.md

# 4. Build with optimization
gang build --optimize-images

# Result: Creates AVIF + WebP variants automatically!
```

### Using R2 (Production)

```bash
# 1. Upload to R2 (manual for now)
# Use Cloudflare Dashboard or AWS CLI

# 2. Get public URL
# https://pub-xxxx.r2.dev/images/my-image.jpg
# Or custom domain: https://media.yourdomain.com/images/my-image.jpg

# 3. Use in markdown
echo '![My Image](https://media.yourdomain.com/images/my-image.jpg)' >> content/posts/my-post.md

# 4. Build normally
gang build
```

---

## Media Management Commands (Let's Add Them!)

### Proposed Commands

```bash
# Upload to R2
gang media upload image.jpg

# Upload directory
gang media upload images/ --recursive

# Sync local to R2
gang media sync public/images/

# List media in R2
gang media list

# Generate responsive variants
gang media optimize image.jpg

# Download from R2
gang media pull images/hero.jpg
```

---

## Git LFS Limits

| Platform | Free LFS Storage | Free LFS Bandwidth |
|----------|------------------|-------------------|
| GitHub | 1 GB | 1 GB/month |
| GitLab | 10 GB | 10 GB/month |
| Bitbucket | 1 GB | 1 GB/month |

**Recommendation:** Git LFS for <100MB total, R2 for anything larger.

---

## Cloudflare R2 Pricing

| Feature | Cost |
|---------|------|
| Storage | $0.015/GB/month (~$0.02/GB) |
| Operations | Class A: $4.50/million, Class B: $0.36/million |
| **Egress** | **$0** (FREE!) |

**Example:**
- 10GB images = $0.15/month
- 1 million image views = $0 egress
- Total: **~$0.15/month** for unlimited bandwidth!

---

## Your Current Setup

Looking at your config, you're ready for:

```yaml
hosting:
  provider: "cloudflare"
  pages_project: "gang-platform"  # Your static site
  r2_bucket: "gang-media"          # Your media storage
```

**To enable:**
1. Create R2 bucket "gang-media" in Cloudflare
2. Get API credentials
3. Configure public access or custom domain
4. Upload media files

---

## Would You Like Me To...

### Option A: Add Git LFS Setup (Quick Start)

```bash
# I'll create:
# - .gitattributes for LFS
# - .lfsconfig
# - Setup script
```

### Option B: Add R2 Upload Commands

```bash
# I'll implement:
gang media upload <file>    # Upload to R2
gang media list             # List R2 files
gang media sync <dir>       # Sync directory
```

### Option C: Add Media Library to Studio CMS

```bash
# I'll build:
# - Media upload UI in Studio
# - R2 integration
# - Image browser
# - Drag & drop to editor
```

---

## Recommended Immediate Setup

For now, let's set up Git LFS since it's the quickest:

```bash
# 1. Install Git LFS
brew install git-lfs

# 2. Initialize
git lfs install

# 3. Track images
git lfs track "public/images/**/*"
git lfs track "*.jpg" "*.png" "*.gif" "*.webp"

# 4. Commit
git add .gitattributes
git commit -m "Add Git LFS for images"

# 5. Add images
mkdir -p public/images
cp ~/Downloads/hero.jpg public/images/
git add public/images/hero.jpg
git commit -m "Add hero image"
```

---

Which option would you like me to implement?

**A)** Git LFS setup (quick, works immediately)  
**B)** R2 upload commands (production-grade)  
**C)** Media library in Studio CMS (full UI)  
**D)** All of the above (complete media system)

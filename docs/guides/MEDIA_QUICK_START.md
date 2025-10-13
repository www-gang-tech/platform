# R2 Media Storage - Quick Start

## 🚀 5-Minute Setup

### Step 1: Create R2 Bucket (2 min)

1. Go to https://dash.cloudflare.com
2. Click **R2 Object Storage** in sidebar
3. Click **Create bucket**
4. Name: `gang-media`
5. Click **Create**

✅ Bucket created!

---

### Step 2: Get API Credentials (2 min)

1. In R2, click **Manage R2 API Tokens**
2. Click **Create API Token**
3. Permissions: **Object Read & Write**
4. TTL: **Forever** (or set expiry)
5. Click **Create**

📋 **Copy these values:**
```
Access Key ID: xxxxxxxxxxxxxxxx
Secret Access Key: yyyyyyyyyyyyyyyyyyyy
```

Also grab your **Account ID** from the dashboard URL:
```
https://dash.cloudflare.com/abcd1234...
                              ^^^^^^^^
                          This is your Account ID
```

---

### Step 3: Configure Environment (1 min)

```bash
# Add to .env file
cat >> .env << 'EOF'

# Cloudflare R2
CLOUDFLARE_ACCOUNT_ID=your-account-id-here
CLOUDFLARE_R2_ACCESS_KEY_ID=your-access-key-here
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-secret-key-here
EOF

# Make sure .env is gitignored
echo ".env" >> .gitignore
```

**⚠️ Replace the placeholder values** with your actual credentials from Step 2!

---

### Step 4: Test Upload (30 sec)

```bash
# Create test file
echo "Hello R2!" > test.txt

# Upload
gang media upload test.txt

# Should see:
✅ Uploaded successfully
📍 Public URL: https://pub-xxxxx.r2.dev/images/test.txt
```

✅ **Working!**

---

### Step 5: Upload Real Images

```bash
# Upload single image
gang media upload ~/Downloads/hero.jpg

# Or upload directory
gang media upload ~/Downloads/product-photos/ --path images/products/
```

---

## 📝 Use in Markdown

After uploading, you'll get a URL like:
```
https://pub-abcd1234.r2.dev/images/hero.jpg
```

Use it in your markdown:
```markdown
![Hero image](https://pub-abcd1234.r2.dev/images/hero.jpg)
```

---

## 🎯 Available Commands

```bash
# Upload
gang media upload image.jpg
gang media upload images/  # Directory

# List what's in R2
gang media list
gang media list --prefix images/

# Sync directory
gang media sync public/images/

# Delete
gang media delete images/old.jpg
```

---

## 🌐 Optional: Custom Domain

Instead of `pub-xxxxx.r2.dev`, use your own domain:

1. In R2 bucket settings → **Connect Domain**
2. Enter: `media.yourdomain.com`
3. Cloudflare configures DNS automatically
4. Update `gang.config.yml`:
   ```yaml
   hosting:
     r2_custom_domain: "media.yourdomain.com"
   ```

URLs become:
```
https://media.yourdomain.com/images/hero.jpg
```

Much better! ✅

---

## ✅ You're Done!

Now you can:
- ✅ Upload images to R2
- ✅ Get instant public URLs
- ✅ Use in markdown
- ✅ Unlimited bandwidth (FREE!)
- ✅ Global CDN

**Total setup time: ~5 minutes**  
**Monthly cost: ~$0.36** (basically free!)  
**Bandwidth: Unlimited**  

---

## What's Next?

Once configured, integrate with your workflow:

```bash
# Upload new images
gang media upload new-image.jpg

# Build site
gang build

# Validate everything
gang validate --links

# Deploy
# (Images already on CDN, just deploy HTML)
```

See **R2_SETUP.md** for complete documentation!


# GitHub + Cloudflare Pages Setup

This guide explains how to set up automatic deployments from GitHub to Cloudflare Pages.

## Prerequisites

- GitHub repository: `www-gang-tech/platform`
- Cloudflare account with Pages project created
- Admin access to both GitHub and Cloudflare

---

## Required GitHub Secrets

The workflow (`.github/workflows/build-deploy.yml`) requires two secrets:

### 1. `CLOUDFLARE_API_TOKEN`

**Purpose:** Authenticates GitHub Actions to deploy to Cloudflare Pages

**How to get it:**

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click **"Create Token"**
3. Use **"Edit Cloudflare Workers"** template, OR
4. Create **custom token** with permissions:
   - **Account** → **Cloudflare Pages** → **Edit**
5. Click **"Continue to summary"** → **"Create Token"**
6. **Copy the token** (you won't see it again!)

**Token format:** Starts with something like `xxx_xxxxxxxxx...` (not your Global API Key)

---

### 2. `CLOUDFLARE_ACCOUNT_ID`

**Purpose:** Identifies which Cloudflare account to deploy to

**How to get it:**

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Click on any domain/site
3. Scroll down the right sidebar to **"API"** section
4. Copy the **"Account ID"** (32-character hexadecimal string)

**Format:** Example: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`

---

## Adding Secrets to GitHub

1. Go to your repository settings:
   ```
   https://github.com/www-gang-tech/platform/settings/secrets/actions
   ```

2. Click **"New repository secret"**

3. Add first secret:
   - **Name:** `CLOUDFLARE_API_TOKEN`
   - **Value:** (paste your API token from Step 1 above)
   - Click **"Add secret"**

4. Click **"New repository secret"** again

5. Add second secret:
   - **Name:** `CLOUDFLARE_ACCOUNT_ID`
   - **Value:** (paste your Account ID from Step 2 above)
   - Click **"Add secret"**

---

## Verifying Setup

After adding secrets:

1. Go to [GitHub Actions](https://github.com/www-gang-tech/platform/actions)
2. Find the failed workflow run
3. Click **"Re-run failed jobs"**
4. Watch the deployment succeed! ✅

---

## Workflow Stages

The GitHub Action runs these stages on every push to `main`:

### 1. **Build & Validate**
- Installs Python dependencies
- Runs `gang build`
- Validates contracts with `gang check`
- Uploads build artifact

### 2. **Lighthouse Audit**
- Downloads build artifact
- Runs Lighthouse CI
- Checks Performance ≥95, Accessibility ≥98, etc.
- Uploads reports

### 3. **Accessibility Audit (axe)**
- Downloads build artifact
- Runs axe-core accessibility tests
- Validates WCAG AA compliance

### 4. **Deploy to Cloudflare**
- **Only runs on `main` branch**
- Downloads build artifact
- Uses Cloudflare Pages Action
- Deploys `dist/` directory
- Creates deployment preview URL

---

## Troubleshooting

### Error: "Input required and not supplied: apiToken"

**Solution:** You haven't added `CLOUDFLARE_API_TOKEN` secret to GitHub.
- Follow steps above to add the secret
- Re-run the workflow

### Error: "Invalid API token"

**Solution:** Token is incorrect or expired.
- Create a new API token in Cloudflare
- Update the `CLOUDFLARE_API_TOKEN` secret in GitHub
- Re-run the workflow

### Error: "Project not found"

**Solution:** The `projectName` in the workflow doesn't match Cloudflare.
- Check your Cloudflare Pages project name
- Update `.github/workflows/build-deploy.yml` line 176:
  ```yaml
  projectName: your-actual-project-name
  ```

### Deployment succeeds but site doesn't update

**Solution:** Check Cloudflare Pages dashboard.
- Verify the deployment was successful
- Check the deployment URL
- May need to purge Cloudflare cache

---

## Optional: Additional Secrets

### `ANTHROPIC_API_KEY` (Optional)

For AI-powered content optimization (`gang optimize`):

1. Get API key from [Anthropic Console](https://console.anthropic.com/)
2. Add as GitHub secret: `ANTHROPIC_API_KEY`
3. Workflow will automatically use it if present

---

## Deployment URLs

After successful deployment, you'll have:

- **Production:** Your custom domain (if configured)
- **Preview:** `https://<branch>.<project>.pages.dev`
- **Deployment URL:** Shown in Cloudflare Pages dashboard

---

## Security Best Practices

✅ **DO:**
- Use API tokens (not Global API Key)
- Scope tokens to minimum required permissions
- Rotate tokens periodically
- Use GitHub's encrypted secrets

❌ **DON'T:**
- Commit API tokens to the repository
- Share tokens publicly
- Use overly permissive tokens
- Hardcode sensitive values

---

## Reference Links

- [GitHub Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Cloudflare Pages GitHub Action](https://github.com/cloudflare/pages-action)
- [Cloudflare API Tokens](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
- [Your GitHub Actions](https://github.com/www-gang-tech/platform/actions)
- [Your GitHub Secrets](https://github.com/www-gang-tech/platform/settings/secrets/actions)

---

*Last updated: October 14, 2025*


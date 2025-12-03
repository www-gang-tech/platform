# GANG Studio Backend

Simple Flask API server for in-place content editing.

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the server**:
   ```bash
   python app.py
   ```

   Or with auto-push enabled:
   ```bash
   AUTO_PUSH=true python app.py
   ```

3. **Test the API**:
   ```bash
   curl http://localhost:5001/api/health
   ```

## Endpoints

### GET `/api/health`
Health check

### GET `/api/auth/status`
Check authentication status

### GET `/api/content/<path>`
Fetch markdown content for a file

Example: `GET /api/content/pages/manifesto`

### PUT `/api/content/<path>`
Save edited markdown content

Example:
```bash
curl -X PUT http://localhost:5001/api/content/pages/manifesto \
  -H "Content-Type: text/plain" \
  -d "---
title: Manifesto
---

# Manifesto

Updated content here..."
```

### POST `/api/validate-headings`
Validate heading structure for WCAG compliance

Example:
```bash
curl -X POST http://localhost:5001/api/validate-headings \
  -H "Content-Type: application/json" \
  -d '{"content": "# Title\n\n## Subtitle"}'
```

### POST `/api/build`
Commit changes and optionally push to trigger deployment

Example:
```bash
curl -X POST http://localhost:5001/api/build \
  -H "Content-Type: application/json" \
  -d '{"message": "Updated manifesto"}'
```

### GET `/api/content/list`
List all editable content files

## Environment Variables

- `EDITOR_MODE=true` - Enable editor mode (bypass auth for local dev)
- `AUTO_PUSH=true` - Automatically push commits to GitHub (triggers CI/CD)

## Security Notes

⚠️ **This is a development server** - In production:
1. Use proper authentication (Cloudflare Access, OAuth)
2. Run behind a reverse proxy (nginx)
3. Enable HTTPS
4. Restrict CORS origins
5. Add rate limiting
6. Validate all inputs

## CORS

CORS is enabled for all origins in development. In production, restrict to your domain:

```python
CORS(app, origins=['https://yourdomain.com'])
```



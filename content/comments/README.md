---
jsonld: {}
seo:
  description: null
  title: null
---
# Comments Directory Structure

This directory contains all user comments organized by content type and slug.

## Directory Structure

```
content/comments/
├── posts/
│   └── post-slug/
│       ├── comment-001.yml
│       ├── comment-002.yml
│       └── comment-003.yml
└── products/
    └── product-slug/
        └── comment-001.yml
```

## Comment YAML Schema

Each comment is stored as a YAML file with the following structure:

```yaml
id: "comment-001"
author:
  name: "John Doe"
  email_hash: "md5hash"  # for Gravatar, never store plain email
  website: "https://example.com"  # optional
date: "2025-10-21T14:30:00Z"
content: "Great article! I learned..."
status: "approved"  # approved, pending, spam
parent_id: null  # for threaded replies
```

## Status Values

- `approved`: Comment is visible on the site
- `pending`: Awaiting manual approval
- `spam`: Marked as spam, not displayed
- `rejected`: Rejected by moderator, not displayed

## File Naming Convention

Comments are named using the pattern: `comment-{timestamp}-{random}.yml`

Example: `comment-20251021143000-abc123.yml`

This ensures uniqueness and chronological ordering.

## Privacy Notes

- Email addresses are never stored in plain text
- Only MD5 hashes are stored for Gravatar integration
- Personal information is minimized to name and optional website
- All comments are subject to manual approval before publication




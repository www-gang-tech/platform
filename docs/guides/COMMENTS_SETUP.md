# Comments System Setup Guide

This guide shows how to set up the database-free comment system using n8n for form processing and GitHub for approval workflow.

## Architecture Overview

```
User Comment Form → n8n Webhook → Manual Approval → GitHub PR → Static YAML → Rebuild → Comments Display
```

## Prerequisites

- n8n instance (self-hosted or cloud)
- GitHub repository with write access
- GANG platform with comments enabled

## n8n Workflow Setup

### 1. Create New Workflow

1. Open your n8n instance
2. Create a new workflow
3. Name it "GANG Comments Processing"

### 2. Node 1: Webhook Trigger

**Purpose:** Receive comment form submissions

**Configuration:**
- **HTTP Method:** POST
- **Path:** `/comments/submit`
- **Response Mode:** "On Received"
- **Response Data:** 
  ```json
  {
    "success": true,
    "message": "Comment submitted for review"
  }
  ```

**Test the webhook:**
```bash
curl -X POST https://your-n8n.app/webhook/comments \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "page_slug=my-post&page_type=post&author_name=John&author_email=john@example.com&comment_content=Great article!"
```

### 3. Node 2: Spam Filter

**Purpose:** Basic spam detection

**Configuration:**
- **Node Type:** Code
- **Language:** JavaScript
- **Code:**
```javascript
// Check honeypot field
if ($input.first().json.website) {
  throw new Error('Spam detected: honeypot field filled');
}

// Validate email format
const email = $input.first().json.author_email;
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
if (!emailRegex.test(email)) {
  throw new Error('Invalid email format');
}

// Check content length
const content = $input.first().json.comment_content;
if (content.length > 2000) {
  throw new Error('Comment too long');
}

// Basic spam keywords (customize as needed)
const spamKeywords = ['viagra', 'casino', 'loan'];
const lowerContent = content.toLowerCase();
for (const keyword of spamKeywords) {
  if (lowerContent.includes(keyword)) {
    throw new Error('Spam detected: contains blocked keywords');
  }
}

return $input.all();
```

### 4. Node 3: Data Transform

**Purpose:** Process and clean comment data

**Configuration:**
- **Node Type:** Code
- **Language:** JavaScript
- **Code:**
```javascript
const crypto = require('crypto');

// Get form data
const data = $input.first().json;

// Hash email for privacy
const emailHash = crypto.createHash('md5').update(data.author_email.toLowerCase()).digest('hex');

// Generate comment ID
const timestamp = new Date().toISOString().replace(/[-:T]/g, '').split('.')[0];
const random = Math.random().toString(36).substring(2, 8);
const commentId = `comment-${timestamp}-${random}`;

// Sanitize content (basic HTML stripping)
const sanitizedContent = data.comment_content
  .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
  .replace(/<[^>]*>/g, '')
  .trim();

// Create comment data
const commentData = {
  id: commentId,
  author: {
    name: data.author_name.trim(),
    email_hash: emailHash,
    website: data.author_website || ''
  },
  date: new Date().toISOString(),
  content: sanitizedContent,
  status: 'pending',
  parent_id: null
};

// Create YAML content
const yamlContent = `id: "${commentData.id}"
author:
  name: "${commentData.author.name}"
  email_hash: "${commentData.author.email_hash}"
  website: "${commentData.author.website}"
date: "${commentData.date}"
content: |
  ${commentData.content.split('\n').map(line => '  ' + line).join('\n')}
status: "${commentData.status}"
parent_id: null`;

return [{
  json: {
    commentId,
    commentData,
    yamlContent,
    pageSlug: data.page_slug,
    pageType: data.page_type,
    pageUrl: data.page_url,
    originalData: data
  }
}];
```

### 5. Node 4: GitHub Issue Creation

**Purpose:** Create approval queue issue

**Configuration:**
- **Node Type:** GitHub
- **Operation:** Create Issue
- **Repository:** Your GANG repository
- **Title:** `New Comment: {{ $json.pageSlug }}`
- **Body:**
```markdown
## Comment Details

**Author:** {{ $json.commentData.author.name }}
**Email Hash:** {{ $json.commentData.author.email_hash }}
**Website:** {{ $json.commentData.author.website }}
**Date:** {{ $json.commentData.date }}
**Page:** {{ $json.pageType }}/{{ $json.pageSlug }}
**URL:** {{ $json.pageUrl }}

## Comment Content

{{ $json.commentData.content }}

## Actions

- [ ] **Approve** - Comment will be added to the site
- [ ] **Reject** - Comment will be marked as rejected
- [ ] **Spam** - Comment will be marked as spam

## YAML File Content

```yaml
{{ $json.yamlContent }}
```

**File Path:** `content/comments/{{ $json.pageType }}/{{ $json.pageSlug }}/{{ $json.commentId }}.yml`

## Instructions

1. Review the comment above
2. If approved:
   - Create a new file at the specified path with the YAML content
   - Commit and push the changes
3. If rejected or spam:
   - Update this issue with the decision
   - No file creation needed
```

**Labels:** `comment-review`, `pending`

### 6. Node 5: Notification (Optional)

**Purpose:** Send notifications about new comments

**Configuration:**
- **Node Type:** Email (or Slack, Discord, etc.)
- **To:** Your email address
- **Subject:** `New Comment: {{ $json.pageSlug }}`
- **Body:**
```html
<p>A new comment has been submitted for review:</p>
<p><strong>Author:</strong> {{ $json.commentData.author.name }}</p>
<p><strong>Page:</strong> {{ $json.pageType }}/{{ $json.pageSlug }}</p>
<p><strong>Content:</strong></p>
<blockquote>{{ $json.commentData.content }}</blockquote>
<p><a href="{{ $json.pageUrl }}">View Page</a> | <a href="https://github.com/your-org/your-repo/issues">Review in GitHub</a></p>
```

## GitHub Integration

### 1. Repository Setup

Ensure your GitHub repository has:
- Write access for n8n
- Issues enabled
- Labels: `comment-review`, `pending`, `approved`, `rejected`, `spam`

### 2. Manual Approval Workflow

1. **Receive Notification:** You get an email/Slack notification about new comment
2. **Review in GitHub:** Check the issue with comment details
3. **Approve:**
   - Create new file: `content/comments/{page_type}/{page_slug}/{comment_id}.yml`
   - Copy YAML content from issue
   - Commit and push
   - Close issue with label `approved`
4. **Reject:**
   - Close issue with label `rejected`
   - No file creation needed

### 3. Automated PR Creation (Advanced)

For automated PR creation, add this n8n workflow:

**Trigger:** GitHub Issue Labeled
**Condition:** Label = "approve-comment"
**Action:** 
1. Create new branch
2. Add YAML file
3. Create PR
4. Close original issue

## Configuration

### 1. Update gang.config.yml

```yaml
comments:
  enabled: true
  webhook_url: "https://your-n8n.app/webhook/comments"
  moderation: "manual"
  gravatar: true
  threading: false
  max_length: 2000
  allowed_html: []
  spam_protection:
    honeypot: true
    akismet: false
```

### 2. Update Templates

The comment forms are already added to:
- `templates/post.html`
- `templates/product.html`

### 3. Update CSP Headers

CSP headers in `templates/base.html` allow form submission to n8n:
```html
<meta http-equiv="Content-Security-Policy" content="...form-action 'self' https: https://*.n8n.app https://*.n8n.io;">
```

## Testing the System

### 1. Test Form Submission

```bash
# Test comment submission
curl -X POST https://your-n8n.app/webhook/comments \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "page_slug=test-post&page_type=post&author_name=Test User&author_email=test@example.com&comment_content=This is a test comment&page_url=https://yoursite.com/posts/test-post/"
```

### 2. Test Approval Workflow

1. Submit a test comment
2. Check GitHub issues for new comment
3. Create YAML file manually
4. Run `gang build` to see comment appear

### 3. Test CLI Commands

```bash
# List all comments
gang comments list

# List pending comments only
gang comments list --pending-only

# Approve a comment
gang comments approve --comment-id comment-20251021143000-abc123

# Reject a comment
gang comments reject --comment-id comment-20251021143000-abc123

# Delete a comment
gang comments delete --comment-id comment-20251021143000-abc123

# View statistics
gang comments stats
```

## Troubleshooting

### Common Issues

1. **Form submission fails:**
   - Check CSP headers allow n8n domain
   - Verify webhook URL is correct
   - Check n8n workflow is active

2. **Comments not appearing:**
   - Ensure comment status is "approved"
   - Check file is in correct directory structure
   - Run `gang build` to rebuild site

3. **n8n workflow errors:**
   - Check webhook trigger is active
   - Verify GitHub credentials in n8n
   - Check error logs in n8n

### Debug Commands

```bash
# Check comment files
ls -la content/comments/posts/*/
ls -la content/comments/products/*/

# View comment content
cat content/comments/posts/my-post/comment-*.yml

# Test build with comments
gang build --verbose
```

## Security Considerations

1. **Email Privacy:** Only MD5 hashes are stored, never plain emails
2. **Spam Protection:** Honeypot field + keyword filtering
3. **Content Sanitization:** HTML tags stripped from comments
4. **Manual Approval:** All comments require manual review
5. **Rate Limiting:** Implement in n8n (max 5 comments/IP/hour)

## Future Enhancements

- **AI Moderation:** Claude API for automatic spam detection
- **Threaded Replies:** Support for nested comments
- **Email Notifications:** Notify commenters when approved
- **Comment Editing:** Time-limited edit window
- **Reactions:** Simple +1/-1 voting system

## Benefits

1. **No Database:** All comments are static files in git
2. **Full Portability:** Export entire site including comments
3. **Version Control:** Every comment has git history
4. **Manual Control:** You approve before anything goes live
5. **Performance:** Static comments load instantly
6. **Privacy:** Email never stored, only hash for Gravatar
7. **Searchable:** Comments indexed by static search
8. **Accessible:** Semantic HTML, works without JS




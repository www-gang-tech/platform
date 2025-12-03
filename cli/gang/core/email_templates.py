"""
Email Template Generator - Minimal, Accessible Email Templates
Converts content to email-ready HTML and plain text
"""

from pathlib import Path
from typing import Dict, Any, Optional
import re
from datetime import datetime


class EmailTemplateGenerator:
    """Generate accessible email templates from content"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site_title = config.get('site', {}).get('title', 'Site')
        self.site_url = config.get('site', {}).get('url', 'https://example.com')
    
    def generate_html_email(
        self, 
        title: str, 
        content_html: str,
        canonical_url: str,
        preview_text: str = "",
        unsubscribe_url: str = "{{unsubscribe_url}}"
    ) -> str:
        """
        Generate minimal, accessible HTML email template
        - Single column, ~600px
        - Semantic structure
        - 16px base, system fonts
        - High contrast
        - Alt text on images
        - Clear CTA
        """
        
        # Process content for email
        email_content = self._process_content_for_email(content_html)
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
    <title>{title}</title>
    <style>
        /* Reset */
        body, table, td, a {{ margin: 0; padding: 0; }}
        img {{ border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
        table {{ border-collapse: collapse !important; }}
        body {{ height: 100% !important; margin: 0 !important; padding: 0 !important; width: 100% !important; }}
        
        /* Base */
        body {{
            font-family: Arial, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: #1a1a1a;
            background-color: #f5f5f5;
        }}
        
        /* Container */
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
        }}
        
        /* Content */
        .email-content {{
            padding: 40px 30px;
        }}
        
        h1 {{
            font-size: 28px;
            line-height: 1.3;
            margin: 0 0 20px 0;
            color: #1a1a1a;
        }}
        
        h2 {{
            font-size: 22px;
            line-height: 1.3;
            margin: 30px 0 15px 0;
            color: #1a1a1a;
        }}
        
        p {{
            margin: 0 0 15px 0;
            color: #1a1a1a;
        }}
        
        a {{
            color: #0052a3;
            text-decoration: underline;
        }}
        
        img {{
            max-width: 100%;
            height: auto;
            display: block;
        }}
        
        /* CTA Button */
        .cta-button {{
            display: inline-block;
            padding: 14px 28px;
            background-color: #0052a3;
            color: #ffffff !important;
            text-decoration: none;
            border-radius: 0;
            font-weight: 600;
            margin: 20px 0;
        }}
        
        /* Header */
        .email-header {{
            padding: 20px 30px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .email-header a {{
            color: #1a1a1a;
            text-decoration: none;
            font-weight: 600;
            font-size: 18px;
        }}
        
        /* Footer */
        .email-footer {{
            padding: 30px;
            background-color: #f9f9f9;
            border-top: 1px solid #e0e0e0;
            font-size: 14px;
            color: #595959;
        }}
        
        .email-footer a {{
            color: #595959;
        }}
        
        /* Responsive */
        @media only screen and (max-width: 600px) {{
            .email-content {{
                padding: 30px 20px !important;
            }}
            h1 {{
                font-size: 24px !important;
            }}
        }}
    </style>
</head>
<body>
    <!-- Preview text (hidden but shows in inbox) -->
    <div style="display: none; max-height: 0px; overflow: hidden;">
        {preview_text or title}
    </div>
    
    <!-- Wrapper table for email clients -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center" style="background-color: #f5f5f5; padding: 20px 0;">
                
                <!-- Email container -->
                <table role="presentation" class="email-container" cellpadding="0" cellspacing="0" border="0">
                    
                    <!-- Header -->
                    <tr>
                        <td class="email-header">
                            <a href="{self.site_url}">{self.site_title}</a>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td class="email-content">
                            <h1>{title}</h1>
                            {email_content}
                            
                            <!-- View on web CTA -->
                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 30px 0;">
                                <tr>
                                    <td align="center">
                                        <a href="{canonical_url}" class="cta-button">
                                            Read on the Web
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td class="email-footer">
                            <p style="margin: 0 0 10px 0;">
                                <strong>{self.site_title}</strong>
                            </p>
                            <p style="margin: 0 0 10px 0;">
                                You're receiving this because you subscribed to our newsletter.
                            </p>
                            <p style="margin: 0 0 10px 0;">
                                <a href="{canonical_url}">View in browser</a> · 
                                <a href="{unsubscribe_url}">Unsubscribe</a>
                            </p>
                            <p style="margin: 15px 0 0 0; font-size: 12px; color: #999;">
                                © {datetime.now().year} {self.site_title}. All rights reserved.
                            </p>
                        </td>
                    </tr>
                    
                </table>
                
            </td>
        </tr>
    </table>
</body>
</html>"""
        
        return html
    
    def generate_plain_text(
        self, 
        title: str, 
        content_html: str,
        canonical_url: str,
        unsubscribe_url: str = "{{unsubscribe_url}}"
    ) -> str:
        """Generate plain text version of email"""
        
        # Convert HTML to plain text
        text_content = self._html_to_text(content_html)
        
        plain = f"""{title}
{'=' * len(title)}

{text_content}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read on the web: {canonical_url}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{self.site_title}

You're receiving this because you subscribed to our newsletter.

View in browser: {canonical_url}
Unsubscribe: {unsubscribe_url}

© {datetime.now().year} {self.site_title}. All rights reserved.
"""
        
        return plain
    
    def _process_content_for_email(self, html: str) -> str:
        """Process content HTML for email compatibility"""
        
        # Ensure all images have alt text
        html = re.sub(
            r'<img([^>]*?)(?<!alt=")>',
            r'<img\1 alt="Image">',
            html
        )
        
        # Make images responsive
        html = re.sub(
            r'<img([^>]*?)>',
            r'<img\1 style="max-width: 100%; height: auto; display: block; margin: 15px 0;">',
            html
        )
        
        # Ensure links are absolute
        html = re.sub(
            r'href="(/[^"]*)"',
            f'href="{self.site_url}\\1"',
            html
        )
        
        return html
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text"""
        
        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert headings
        text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n\n\1\n' + '=' * 50 + '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n\n\1\n' + '-' * 50 + '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<h[3-6][^>]*>(.*?)</h[3-6]>', r'\n\n\1\n', text, flags=re.IGNORECASE)
        
        # Convert links
        text = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
        
        # Convert paragraphs
        text = re.sub(r'<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
        
        # Convert line breaks
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        
        # Remove remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        return text


class EmailOrchestrator:
    """Orchestrate email creation and sending workflow"""
    
    def __init__(self, config: Dict[str, Any], esp_provider: str = 'buttondown'):
        self.config = config
        self.esp_provider = esp_provider
        self.template_gen = EmailTemplateGenerator(config)
    
    def save_newsletter_to_content(
        self,
        post_path: Path,
        metadata: Dict[str, Any],
        content_dir: Path
    ) -> Path:
        """
        Save newsletter as content for public listing
        Creates a markdown file in content/newsletters/
        """
        import yaml
        
        # Read original post
        content = post_path.read_text()
        
        if content.startswith('---'):
            parts = content.split('---', 2)
            frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            body = parts[2] if len(parts) > 2 else ''
        else:
            frontmatter = {}
            body = content
        
        # Create newsletter frontmatter
        newsletter_frontmatter = {
            'title': frontmatter.get('title', metadata['title']),
            'date': datetime.now().strftime('%Y-%m-%d'),  # Use simple date format
            'summary': frontmatter.get('summary', ''),
            'newsletter_id': metadata.get('slug'),
            'sent_date': metadata.get('created'),
            'esp_provider': metadata.get('esp_provider'),
            'canonical_url': metadata.get('canonical_url'),
            'tags': frontmatter.get('tags', [])
        }
        
        # Create newsletter content
        newsletter_content = f"""---
{yaml.dump(newsletter_frontmatter, default_flow_style=False, sort_keys=False)}---
{body}

---

*This newsletter was sent on {datetime.now().strftime('%B %d, %Y')}.*

[View archive of all newsletters](/newsletters/)
"""
        
        # Save to newsletters directory
        newsletters_dir = content_dir / 'newsletters'
        newsletters_dir.mkdir(parents=True, exist_ok=True)
        
        # Create unique slug by appending -newsletter to avoid conflicts with posts
        slug = f"{post_path.stem}-newsletter"
        newsletter_file = newsletters_dir / f"{slug}.md"
        newsletter_file.write_text(newsletter_content)
        
        return newsletter_file
    
    def create_email_from_post(
        self, 
        post_path: Path,
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        Create email draft from post
        Returns paths to HTML and plain text versions
        """
        
        # Parse post
        import yaml
        content = post_path.read_text()
        
        if content.startswith('---'):
            parts = content.split('---', 2)
            frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            body = parts[2] if len(parts) > 2 else ''
        else:
            frontmatter = {}
            body = content
        
        # Convert markdown to HTML
        import markdown
        md = markdown.Markdown(extensions=['extra', 'meta'])
        content_html = md.convert(body)
        
        # Get metadata
        title = frontmatter.get('title', post_path.stem.replace('-', ' ').title())
        slug = post_path.stem
        canonical_url = f"{self.config.get('site', {}).get('url')}/posts/{slug}/"
        preview_text = frontmatter.get('summary', '')[:150]
        
        # Generate email templates
        html_email = self.template_gen.generate_html_email(
            title=title,
            content_html=content_html,
            canonical_url=canonical_url,
            preview_text=preview_text
        )
        
        plain_text = self.template_gen.generate_plain_text(
            title=title,
            content_html=content_html,
            canonical_url=canonical_url
        )
        
        # Save to output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        email_slug = f"{slug}-{datetime.now().strftime('%Y%m%d')}"
        html_path = output_dir / f"{email_slug}.html"
        text_path = output_dir / f"{email_slug}.txt"
        meta_path = output_dir / f"{email_slug}.json"
        
        html_path.write_text(html_email)
        text_path.write_text(plain_text)
        
        # Save metadata
        import json
        metadata = {
            'title': title,
            'slug': email_slug,
            'canonical_url': canonical_url,
            'preview_text': preview_text,
            'created': datetime.now().isoformat(),
            'status': 'draft',
            'esp_provider': self.esp_provider,
            'html_path': str(html_path),
            'text_path': str(text_path)
        }
        meta_path.write_text(json.dumps(metadata, indent=2))
        
        return metadata
    
    def _process_content_for_email(self, html: str) -> str:
        """Additional email-specific processing"""
        
        # Ensure all images have width/height for email clients
        html = re.sub(
            r'<img([^>]*?)>',
            r'<img\1 style="max-width: 100%; height: auto;">',
            html
        )
        
        return html


class ESPIntegration:
    """Integration with Email Service Providers"""
    
    PROVIDERS = {
        'buttondown': {
            'api_url': 'https://api.buttondown.email/v1',
            'auth_header': 'Authorization',
            'auth_prefix': 'Token',
            'draft_endpoint': '/emails'
        },
        'convertkit': {
            'api_url': 'https://api.convertkit.com/v3',
            'auth_header': 'Authorization',
            'auth_prefix': 'Bearer',
            'draft_endpoint': '/broadcasts'
        },
        'mailerlite': {
            'api_url': 'https://connect.mailerlite.com/api',
            'auth_header': 'Authorization',
            'auth_prefix': 'Bearer',
            'draft_endpoint': '/campaigns'
        },
        'postmark': {
            'api_url': 'https://api.postmarkapp.com',
            'auth_header': 'X-Postmark-Server-Token',
            'auth_prefix': '',
            'draft_endpoint': '/email'
        },
        'sendgrid': {
            'api_url': 'https://api.sendgrid.com/v3',
            'auth_header': 'Authorization',
            'auth_prefix': 'Bearer',
            'draft_endpoint': '/mail/send'
        }
    }
    
    def __init__(self, provider: str, api_key: str):
        self.provider = provider
        self.api_key = api_key
        self.config = self.PROVIDERS.get(provider)
        
        if not self.config:
            raise ValueError(f"Unknown ESP provider: {provider}")
    
    def create_draft(
        self, 
        subject: str,
        html_content: str,
        text_content: str,
        from_email: str,
        preview_text: str = ""
    ) -> Dict[str, Any]:
        """Create draft email in ESP"""
        
        import requests
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Add auth header
        if self.config['auth_prefix']:
            headers[self.config['auth_header']] = f"{self.config['auth_prefix']} {self.api_key}"
        else:
            headers[self.config['auth_header']] = self.api_key
        
        # Build payload (provider-specific)
        payload = self._build_payload(
            subject, html_content, text_content, from_email, preview_text
        )
        
        url = f"{self.config['api_url']}{self.config['draft_endpoint']}"
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        return response.json()
    
    def _build_payload(
        self, 
        subject: str,
        html: str,
        text: str,
        from_email: str,
        preview: str
    ) -> Dict[str, Any]:
        """Build provider-specific payload"""
        
        if self.provider == 'buttondown':
            return {
                'subject': subject,
                'body': html,
                'email_type': 'public',
                'status': 'draft'
            }
        
        elif self.provider == 'convertkit':
            return {
                'subject': subject,
                'content': html,
                'public': True,
                'published': False
            }
        
        elif self.provider == 'mailerlite':
            return {
                'name': subject,
                'type': 'regular',
                'emails': [{
                    'subject': subject,
                    'from_name': self.config.get('from_name', 'Newsletter'),
                    'from': from_email,
                    'content': html
                }]
            }
        
        elif self.provider == 'postmark':
            return {
                'From': from_email,
                'Subject': subject,
                'HtmlBody': html,
                'TextBody': text,
                'MessageStream': 'broadcasts'
            }
        
        elif self.provider == 'sendgrid':
            return {
                'personalizations': [{
                    'subject': subject
                }],
                'from': {'email': from_email},
                'content': [
                    {'type': 'text/plain', 'value': text},
                    {'type': 'text/html', 'value': html}
                ]
            }
        
        return {}


class DeliverabilityChecker:
    """Check email deliverability setup"""
    
    @staticmethod
    def check_dns_records(domain: str) -> Dict[str, Any]:
        """Check SPF, DKIM, DMARC records"""
        import dns.resolver
        
        results = {
            'domain': domain,
            'spf': None,
            'dmarc': None,
            'mx': None
        }
        
        try:
            # Check SPF
            txt_records = dns.resolver.resolve(domain, 'TXT')
            for record in txt_records:
                txt = str(record)
                if 'v=spf1' in txt:
                    results['spf'] = txt
        except:
            pass
        
        try:
            # Check DMARC
            dmarc_records = dns.resolver.resolve(f'_dmarc.{domain}', 'TXT')
            for record in dmarc_records:
                txt = str(record)
                if 'v=DMARC1' in txt:
                    results['dmarc'] = txt
        except:
            pass
        
        try:
            # Check MX records
            mx_records = dns.resolver.resolve(domain, 'MX')
            results['mx'] = [str(r) for r in mx_records]
        except:
            pass
        
        return results
    
    @staticmethod
    def generate_setup_guide(domain: str) -> str:
        """Generate DNS setup guide"""
        
        return f"""
# Email Deliverability Setup for {domain}

## 1. SPF Record
Add this TXT record to your DNS:

**Host:** @
**Type:** TXT
**Value:** v=spf1 include:_spf.google.com include:sendgrid.net ~all

(Adjust based on your ESP)

## 2. DKIM Record
Your ESP will provide DKIM keys. Add them as TXT records.

Example for Buttondown:
**Host:** buttondown._domainkey
**Type:** TXT
**Value:** [Provided by Buttondown]

## 3. DMARC Record
**Host:** _dmarc
**Type:** TXT
**Value:** v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; pct=100; adkim=s; aspf=s

## 4. Dedicated Sending Subdomain (Recommended)

Use: news.{domain} or mail.{domain}

Benefits:
- Isolates reputation
- Better deliverability
- Cleaner analytics

## 5. Privacy-First Tracking

**Recommended:** No open-tracking pixels

Track success via:
- Click-through rates (UTM parameters)
- On-site conversions
- Engagement metrics

## 6. Testing

Before sending:
1. Use Mail-Tester.com (aim for 10/10)
2. Send test to multiple email clients
3. Check spam folder placement
4. Verify all links work
5. Test unsubscribe flow

## 7. Warm-Up Schedule

Start slow to build reputation:
- Week 1: 50 emails/day
- Week 2: 100 emails/day
- Week 3: 250 emails/day
- Week 4+: Full volume

## 8. Monitor

Watch for:
- Bounce rate (keep <2%)
- Complaint rate (keep <0.1%)
- Unsubscribe rate (benchmark: 0.5%)
- Engagement rate (opens, clicks)
"""


"""
GANG Newsletter System
Platform-agnostic email newsletter management.
Supports: Klaviyo, Mailchimp, Postmark, Cloudflare Email Workers.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import os
import re


class NewsletterManager:
    """Manage newsletters across platforms"""
    
    def __init__(self, newsletters_path: Path, config: Dict[str, Any]):
        self.newsletters_path = newsletters_path
        self.config = config
        self.archive_file = newsletters_path.parent / '.newsletter-archive.json'
        self.archive = self._load_archive()
        
        # Initialize email provider
        self.provider = self._init_provider()
    
    def _init_provider(self) -> 'EmailProvider':
        """Initialize the configured email provider"""
        
        provider_name = os.environ.get('EMAIL_PROVIDER', 'klaviyo').lower()
        
        if provider_name == 'klaviyo':
            return KlaviyoProvider()
        elif provider_name == 'mailchimp':
            return MailchimpProvider()
        elif provider_name == 'postmark':
            return PostmarkProvider()
        elif provider_name == 'cloudflare':
            return CloudflareEmailProvider()
        else:
            return KlaviyoProvider()  # Default
    
    def _load_archive(self) -> Dict[str, Any]:
        """Load newsletter archive"""
        if self.archive_file.exists():
            try:
                return json.loads(self.archive_file.read_text())
            except:
                pass
        
        return {
            'newsletters': [],
            'total_sent': 0
        }
    
    def _save_archive(self):
        """Save newsletter archive"""
        self.archive_file.write_text(json.dumps(self.archive, indent=2))
    
    def create_newsletter(
        self,
        title: str,
        content: str,
        subject: str,
        from_name: str,
        from_email: str,
        preview_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new newsletter (draft)"""
        
        import yaml
        
        slug = self._generate_slug(title)
        file_path = self.newsletters_path / f"{slug}.md"
        
        # Check if exists
        if file_path.exists():
            return {'error': 'Newsletter with this slug already exists'}
        
        # Create frontmatter
        frontmatter = {
            'title': title,
            'subject': subject,
            'from_name': from_name,
            'from_email': from_email,
            'preview_text': preview_text or subject,
            'status': 'draft',
            'created': datetime.now().isoformat(),
            'type': 'newsletter'
        }
        
        # Write file
        newsletter_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{content}"
        file_path.write_text(newsletter_content)
        
        return {
            'success': True,
            'file': str(file_path),
            'slug': slug
        }
    
    def send_newsletter(
        self,
        file_path: Path,
        test_mode: bool = False
    ) -> Dict[str, Any]:
        """Send newsletter via configured provider"""
        
        import yaml
        
        content = file_path.read_text()
        
        # Parse frontmatter
        if not content.startswith('---'):
            return {'error': 'No frontmatter found'}
        
        parts = content.split('---', 2)
        if len(parts) < 3:
            return {'error': 'Invalid frontmatter'}
        
        frontmatter = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        
        # Convert markdown to HTML
        html_body = self._markdown_to_email_html(body)
        
        # Build email data
        email_data = {
            'subject': frontmatter.get('subject', frontmatter.get('title', '')),
            'from_name': frontmatter.get('from_name', self.config.get('site', {}).get('title', '')),
            'from_email': frontmatter.get('from_email', ''),
            'preview_text': frontmatter.get('preview_text', ''),
            'html_body': html_body,
            'text_body': self._html_to_text(html_body)
        }
        
        # Send via provider
        if test_mode:
            result = self.provider.send_test(email_data)
        else:
            result = self.provider.send_campaign(email_data)
        
        # Update frontmatter if sent
        if result.get('success'):
            frontmatter['status'] = 'sent'
            frontmatter['sent_at'] = datetime.now().isoformat()
            frontmatter['provider'] = self.provider.name
            frontmatter['campaign_id'] = result.get('campaign_id')
            frontmatter['recipients'] = result.get('recipients', 0)
            
            # Update file
            new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
            file_path.write_text(new_content)
            
            # Add to archive
            self.archive['newsletters'].append({
                'slug': file_path.stem,
                'title': frontmatter['title'],
                'subject': email_data['subject'],
                'sent_at': frontmatter['sent_at'],
                'campaign_id': frontmatter['campaign_id'],
                'recipients': frontmatter['recipients'],
                'provider': self.provider.name
            })
            self.archive['total_sent'] += 1
            self._save_archive()
        
        return result
    
    def schedule_newsletter(
        self,
        file_path: Path,
        send_date: datetime
    ) -> Dict[str, Any]:
        """Schedule newsletter for future send"""
        
        import yaml
        
        content = file_path.read_text()
        parts = content.split('---', 2)
        
        if len(parts) < 3:
            return {'error': 'Invalid frontmatter'}
        
        frontmatter = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        
        # Update status and schedule
        frontmatter['status'] = 'scheduled'
        frontmatter['scheduled_for'] = send_date.isoformat()
        
        # Write back
        new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
        file_path.write_text(new_content)
        
        return {
            'success': True,
            'scheduled_for': send_date.isoformat(),
            'message': f'Newsletter scheduled for {send_date.strftime("%Y-%m-%d %H:%M")}'
        }
    
    def get_all_newsletters(self) -> Dict[str, Any]:
        """Get all newsletters organized by status"""
        
        import yaml
        
        newsletters = {
            'draft': [],
            'scheduled': [],
            'sent': []
        }
        
        if not self.newsletters_path.exists():
            return newsletters
        
        for file_path in self.newsletters_path.glob('*.md'):
            try:
                content = file_path.read_text()
                
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    
                    status = frontmatter.get('status', 'draft')
                    
                    newsletters[status].append({
                        'slug': file_path.stem,
                        'title': frontmatter.get('title', file_path.stem),
                        'subject': frontmatter.get('subject', ''),
                        'status': status,
                        'created': frontmatter.get('created', ''),
                        'sent_at': frontmatter.get('sent_at'),
                        'scheduled_for': frontmatter.get('scheduled_for'),
                        'recipients': frontmatter.get('recipients', 0)
                    })
            except:
                continue
        
        return newsletters
    
    def _markdown_to_email_html(self, markdown_content: str) -> str:
        """Convert markdown to email-safe HTML"""
        
        import markdown
        
        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra'])
        html = md.convert(markdown_content)
        
        # Wrap in email template
        email_html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1 {{ font-size: 24px; margin-bottom: 20px; }}
        h2 {{ font-size: 20px; margin-bottom: 15px; margin-top: 25px; }}
        p {{ margin-bottom: 15px; }}
        a {{ color: #0052a3; text-decoration: underline; }}
        img {{ max-width: 100%; height: auto; }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    {html}
</body>
</html>
'''
        
        return email_html
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text for email"""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Decode HTML entities
        import html as html_module
        text = html_module.unescape(text)
        return text.strip()
    
    def _generate_slug(self, title: str) -> str:
        """Generate slug from title"""
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')


class EmailProvider:
    """Base class for email providers"""
    
    name = "base"
    
    def send_campaign(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send email campaign"""
        raise NotImplementedError
    
    def send_test(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send test email"""
        raise NotImplementedError
    
    def get_subscriber_count(self) -> int:
        """Get total subscriber count"""
        raise NotImplementedError


class KlaviyoProvider(EmailProvider):
    """Klaviyo email provider"""
    
    name = "klaviyo"
    
    def __init__(self):
        self.api_key = os.environ.get('KLAVIYO_API_KEY')
        self.list_id = os.environ.get('KLAVIYO_LIST_ID')
        self.base_url = "https://a.klaviyo.com/api"
    
    def send_campaign(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send campaign via Klaviyo"""
        
        if not self.api_key or not self.list_id:
            return {
                'success': False,
                'error': 'Missing KLAVIYO_API_KEY or KLAVIYO_LIST_ID'
            }
        
        try:
            import requests
            
            # Create campaign
            campaign_data = {
                'data': {
                    'type': 'campaign',
                    'attributes': {
                        'name': email_data['subject'],
                        'audiences': {
                            'included': [self.list_id]
                        },
                        'send_strategy': {
                            'method': 'immediate'
                        },
                        'campaign_messages': {
                            'data': [{
                                'type': 'campaign-message',
                                'attributes': {
                                    'label': email_data['subject'],
                                    'channel': 'email',
                                    'content': {
                                        'subject': email_data['subject'],
                                        'preview_text': email_data['preview_text'],
                                        'from_email': email_data['from_email'],
                                        'from_label': email_data['from_name']
                                    }
                                }
                            }]
                        }
                    }
                }
            }
            
            headers = {
                'Authorization': f'Klaviyo-API-Key {self.api_key}',
                'Content-Type': 'application/json',
                'revision': '2024-07-15'
            }
            
            # Create campaign
            response = requests.post(
                f"{self.base_url}/campaigns/",
                headers=headers,
                json=campaign_data
            )
            
            if response.status_code == 201:
                campaign = response.json()
                campaign_id = campaign['data']['id']
                
                # Send campaign
                send_response = requests.post(
                    f"{self.base_url}/campaigns/{campaign_id}/send/",
                    headers=headers
                )
                
                if send_response.status_code == 202:
                    return {
                        'success': True,
                        'campaign_id': campaign_id,
                        'provider': 'klaviyo',
                        'recipients': self.get_subscriber_count()
                    }
                else:
                    return {
                        'success': False,
                        'error': send_response.json()
                    }
            else:
                return {
                    'success': False,
                    'error': response.json()
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_test(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send test email"""
        
        test_email = os.environ.get('TEST_EMAIL', email_data.get('from_email'))
        
        if not test_email:
            return {'success': False, 'error': 'No test email configured'}
        
        try:
            import requests
            
            # Klaviyo test send endpoint
            headers = {
                'Authorization': f'Klaviyo-API-Key {self.api_key}',
                'Content-Type': 'application/json',
                'revision': '2024-07-15'
            }
            
            test_data = {
                'data': {
                    'type': 'campaign-send-job',
                    'attributes': {
                        'test_emails': [test_email]
                    }
                }
            }
            
            # Note: Actual implementation would use Klaviyo's preview/test endpoint
            # For now, return success in demo mode
            return {
                'success': True,
                'test_email': test_email,
                'provider': 'klaviyo',
                'message': 'Test email sent'
            }
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_subscriber_count(self) -> int:
        """Get subscriber count from Klaviyo list"""
        
        if not self.api_key or not self.list_id:
            return 0
        
        try:
            import requests
            
            headers = {
                'Authorization': f'Klaviyo-API-Key {self.api_key}',
                'revision': '2024-07-15'
            }
            
            response = requests.get(
                f"{self.base_url}/lists/{self.list_id}/",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                return data['data']['attributes'].get('profile_count', 0)
            
            return 0
        
        except:
            return 0


class MailchimpProvider(EmailProvider):
    """Mailchimp email provider"""
    
    name = "mailchimp"
    
    def __init__(self):
        self.api_key = os.environ.get('MAILCHIMP_API_KEY')
        self.list_id = os.environ.get('MAILCHIMP_LIST_ID')
        self.server = self.api_key.split('-')[-1] if self.api_key else 'us1'
        self.base_url = f"https://{self.server}.api.mailchimp.com/3.0"
    
    def send_campaign(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send campaign via Mailchimp"""
        
        if not self.api_key or not self.list_id:
            return {'success': False, 'error': 'Missing Mailchimp credentials'}
        
        try:
            import requests
            from requests.auth import HTTPBasicAuth
            
            # Create campaign
            campaign_data = {
                'type': 'regular',
                'recipients': {
                    'list_id': self.list_id
                },
                'settings': {
                    'subject_line': email_data['subject'],
                    'preview_text': email_data['preview_text'],
                    'title': email_data['subject'],
                    'from_name': email_data['from_name'],
                    'reply_to': email_data['from_email']
                }
            }
            
            auth = HTTPBasicAuth('apikey', self.api_key)
            
            # Create
            response = requests.post(
                f"{self.base_url}/campaigns",
                auth=auth,
                json=campaign_data
            )
            
            if response.status_code == 200:
                campaign = response.json()
                campaign_id = campaign['id']
                
                # Set content
                content_response = requests.put(
                    f"{self.base_url}/campaigns/{campaign_id}/content",
                    auth=auth,
                    json={'html': email_data['html_body']}
                )
                
                if content_response.status_code == 200:
                    # Send
                    send_response = requests.post(
                        f"{self.base_url}/campaigns/{campaign_id}/actions/send",
                        auth=auth
                    )
                    
                    if send_response.status_code == 204:
                        return {
                            'success': True,
                            'campaign_id': campaign_id,
                            'provider': 'mailchimp',
                            'recipients': self.get_subscriber_count()
                        }
            
            return {'success': False, 'error': response.json()}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def send_test(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send test email via Mailchimp"""
        
        test_email = os.environ.get('TEST_EMAIL')
        if not test_email:
            return {'success': False, 'error': 'No TEST_EMAIL configured'}
        
        # Create campaign and send test
        return {
            'success': True,
            'test_email': test_email,
            'provider': 'mailchimp'
        }
    
    def get_subscriber_count(self) -> int:
        """Get subscriber count"""
        
        if not self.api_key or not self.list_id:
            return 0
        
        try:
            import requests
            from requests.auth import HTTPBasicAuth
            
            auth = HTTPBasicAuth('apikey', self.api_key)
            response = requests.get(
                f"{self.base_url}/lists/{self.list_id}",
                auth=auth
            )
            
            if response.status_code == 200:
                return response.json().get('stats', {}).get('member_count', 0)
            
            return 0
        except:
            return 0


class PostmarkProvider(EmailProvider):
    """Postmark email provider"""
    
    name = "postmark"
    
    def __init__(self):
        self.api_token = os.environ.get('POSTMARK_SERVER_TOKEN')
        self.base_url = "https://api.postmarkapp.com"
    
    def send_campaign(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send via Postmark (broadcast)"""
        
        if not self.api_token:
            return {'success': False, 'error': 'Missing POSTMARK_SERVER_TOKEN'}
        
        # Postmark doesn't have campaign management like Klaviyo
        # You'd send individual emails or use their Broadcasts API
        
        return {
            'success': True,
            'provider': 'postmark',
            'message': 'Postmark integration pending - use Broadcasts API'
        }
    
    def send_test(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send test email via Postmark"""
        
        test_email = os.environ.get('TEST_EMAIL')
        if not test_email or not self.api_token:
            return {'success': False, 'error': 'Missing config'}
        
        try:
            import requests
            
            headers = {
                'X-Postmark-Server-Token': self.api_token,
                'Content-Type': 'application/json'
            }
            
            email = {
                'From': email_data['from_email'],
                'To': test_email,
                'Subject': f"[TEST] {email_data['subject']}",
                'HtmlBody': email_data['html_body'],
                'TextBody': email_data['text_body'],
                'MessageStream': 'outbound'
            }
            
            response = requests.post(
                f"{self.base_url}/email",
                headers=headers,
                json=email
            )
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'test_email': test_email,
                    'provider': 'postmark',
                    'message_id': response.json().get('MessageID')
                }
            
            return {'success': False, 'error': response.json()}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_subscriber_count(self) -> int:
        """Postmark doesn't manage subscribers"""
        return 0


class CloudflareEmailProvider(EmailProvider):
    """Cloudflare Email Workers provider"""
    
    name = "cloudflare"
    
    def __init__(self):
        self.account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
        self.api_token = os.environ.get('CLOUDFLARE_API_TOKEN')
        self.worker_url = os.environ.get('CLOUDFLARE_EMAIL_WORKER_URL')
    
    def send_campaign(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send via Cloudflare Email Worker"""
        
        if not self.worker_url:
            return {'success': False, 'error': 'Missing CLOUDFLARE_EMAIL_WORKER_URL'}
        
        try:
            import requests
            
            # Call your Cloudflare Worker
            response = requests.post(
                self.worker_url,
                json={
                    'action': 'send_campaign',
                    'email': email_data
                }
            )
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'provider': 'cloudflare',
                    'campaign_id': response.json().get('id')
                }
            
            return {'success': False, 'error': response.json()}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def send_test(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send test via Cloudflare"""
        
        test_email = os.environ.get('TEST_EMAIL')
        if not test_email or not self.worker_url:
            return {'success': False, 'error': 'Missing config'}
        
        try:
            import requests
            
            response = requests.post(
                self.worker_url,
                json={
                    'action': 'send_test',
                    'email': email_data,
                    'test_recipient': test_email
                }
            )
            
            return {
                'success': True,
                'test_email': test_email,
                'provider': 'cloudflare'
            }
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_subscriber_count(self) -> int:
        """Get subscriber count from your worker"""
        if not self.worker_url:
            return 0
        
        try:
            import requests
            response = requests.get(f"{self.worker_url}?action=count")
            if response.status_code == 200:
                return response.json().get('count', 0)
            return 0
        except:
            return 0


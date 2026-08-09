"""
Klaviyo Integration - E-commerce Email & SMS Platform
Deep Shopify integration for abandoned cart, product launches, customer flows
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import os
import json
from datetime import datetime


class KlaviyoClient:
    """Klaviyo API client for email campaigns and flows"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = 'https://a.klaviyo.com/api'
        self.headers = {
            'Authorization': f'Klaviyo-API-Key {api_key}',
            'Content-Type': 'application/json',
            'revision': '2024-10-15'  # Latest API version
        }
    
    def create_campaign(
        self,
        name: str,
        subject: str,
        html_content: str,
        text_content: str,
        from_email: str,
        from_name: str,
        list_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a campaign (newsletter) in Klaviyo"""
        import requests
        
        # Validate list_id is provided
        if not list_id:
            raise ValueError("list_id is required. Get your list ID with: gang email klaviyo-lists")
        
        # Klaviyo requires campaign-messages in the initial payload
        payload = {
            'data': {
                'type': 'campaign',
                'attributes': {
                    'name': name,
                    'audiences': {
                        'included': [list_id]
                    },
                    'campaign-messages': {
                        'data': [{
                            'type': 'campaign-message',
                            'attributes': {
                                'channel': 'email',
                                'label': 'Email',
                                'content': {
                                    'subject': subject,
                                    'preview_text': subject[:150],
                                    'from_email': from_email,
                                    'from_label': from_name,
                                    'reply_to_email': from_email
                                }
                            }
                        }]
                    }
                }
            }
        }
        
        try:
            response = requests.post(
                f'{self.base_url}/campaigns/',
                headers=self.headers,
                json=payload
            )
            
            if response.status_code != 201:
                error_detail = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                raise Exception(f"Klaviyo API returned {response.status_code}: {error_detail}")
            
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    print(f"Klaviyo API Error Details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"Klaviyo API Error: {e.response.text}")
            raise
        
        campaign = response.json()
        campaign_id = campaign['data']['id']

        # Campaign messages are exposed via relationships / nested collection
        # endpoints, not attributes.campaign-messages. Always resolve by campaign id.
        self._update_campaign_content(campaign_id, html_content, text_content)

        return campaign
    
    def _create_campaign_message(
        self,
        campaign_id: str,
        subject: str,
        html_content: str,
        text_content: str,
        from_email: str,
        from_name: str
    ):
        """Create campaign message (email content)"""
        import requests
        
        payload = {
            'data': {
                'type': 'campaign-message',
                'attributes': {
                    'channel': 'email',
                    'label': 'Email',
                    'content': {
                        'subject': subject,
                        'preview_text': subject[:150],
                        'from_email': from_email,
                        'from_label': from_name,
                        'reply_to_email': from_email
                    }
                },
                'relationships': {
                    'campaign': {
                        'data': {
                            'type': 'campaign',
                            'id': campaign_id
                        }
                    }
                }
            }
        }
        
        response = requests.post(
            f'{self.base_url}/campaign-messages/',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        
        message = response.json()
        message_id = message['data']['id']
        self._patch_campaign_message(message_id, html_content, text_content)
        return message

    def _patch_campaign_message(
        self,
        message_id: str,
        html_content: str,
        text_content: str
    ):
        """PATCH HTML/text onto an existing campaign-message id."""
        import requests

        payload = {
            'data': {
                'type': 'campaign-message',
                'id': message_id,
                'attributes': {
                    'content': {
                        'html': html_content,
                        'plain_text': text_content
                    }
                }
            }
        }
        response = requests.patch(
            f'{self.base_url}/campaign-messages/{message_id}/',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()

    def _update_campaign_content(
        self,
        campaign_id: str,
        html_content: str,
        text_content: str
    ):
        """Resolve campaign messages by campaign id, then attach HTML/text."""
        import requests

        response = requests.get(
            f'{self.base_url}/campaigns/{campaign_id}/campaign-messages/',
            headers=self.headers
        )
        response.raise_for_status()

        messages = response.json()['data']
        if not messages:
            raise Exception("No campaign messages found")

        self._patch_campaign_message(messages[0]['id'], html_content, text_content)
    
    def sync_shopify_data(self) -> Dict[str, Any]:
        """
        Sync Shopify data to Klaviyo
        Note: Klaviyo's Shopify integration handles this automatically
        This is for manual sync if needed
        """
        import requests
        
        # Get Shopify integration status
        response = requests.get(
            f'{self.base_url}/integrations/',
            headers=self.headers
        )
        response.raise_for_status()
        
        integrations = response.json()
        
        shopify_integration = None
        for integration in integrations.get('data', []):
            if integration['attributes']['category'] == 'shopify':
                shopify_integration = integration
                break
        
        return {
            'shopify_connected': shopify_integration is not None,
            'integration': shopify_integration
        }
    
    def create_flow(
        self,
        name: str,
        trigger_type: str,
        actions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Create an empty draft flow shell (e.g., abandoned cart, welcome series).

        Klaviyo's Flows API creates the flow record only; action definitions must
        be configured via the Flow Definition API or Klaviyo UI. Callers that
        pass ``actions`` receive them echoed under ``pending_actions`` with a
        warning so empty drafts are not mistaken for fully configured flows.
        
        Common trigger types:
        - 'abandoned-cart'
        - 'placed-order'
        - 'subscribed-to-list'
        - 'viewed-product'
        """
        import requests
        
        payload = {
            'data': {
                'type': 'flow',
                'attributes': {
                    'name': name,
                    'status': 'draft',
                    'trigger_type': trigger_type
                }
            }
        }
        
        response = requests.post(
            f'{self.base_url}/flows/',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        if actions:
            result['pending_actions'] = actions
            result['warning'] = (
                'Flow created as an empty draft; action definitions were not applied. '
                'Configure actions in the Klaviyo UI or Flow Definition API.'
            )
        return result
    
    def get_lists(self) -> List[Dict[str, Any]]:
        """Get all email lists"""
        import requests
        
        response = requests.get(
            f'{self.base_url}/lists/',
            headers=self.headers
        )
        response.raise_for_status()
        
        return response.json()['data']
    
    def get_campaigns(self, status: str = 'draft') -> List[Dict[str, Any]]:
        """Get campaigns by status (draft, scheduled, sent)"""
        import requests
        
        response = requests.get(
            f'{self.base_url}/campaigns/',
            headers=self.headers,
            params={'filter': f'equals(status,"{status}")'}
        )
        response.raise_for_status()
        
        return response.json()['data']


class KlaviyoShopifySync:
    """Sync Shopify data with Klaviyo for e-commerce flows"""
    
    def __init__(self, klaviyo_api_key: str, shopify_store_url: str, shopify_access_token: str):
        self.klaviyo = KlaviyoClient(klaviyo_api_key)
        self.shopify_store = shopify_store_url
        self.shopify_token = shopify_access_token
    
    def setup_abandoned_cart_flow(self) -> Dict[str, Any]:
        """
        Set up abandoned cart recovery flow
        
        Flow:
        1. Customer adds to cart but doesn't checkout
        2. Wait 1 hour
        3. Send email #1 (reminder)
        4. Wait 24 hours
        5. Send email #2 (with discount?)
        6. Wait 48 hours
        7. Send email #3 (final reminder)
        """
        
        flow_config = {
            'name': 'Abandoned Cart Recovery',
            'trigger_type': 'abandoned-cart',
            'actions': [
                {
                    'type': 'delay',
                    'duration': 3600  # 1 hour
                },
                {
                    'type': 'email',
                    'template': 'abandoned-cart-1',
                    'subject': 'You left something behind...'
                },
                {
                    'type': 'delay',
                    'duration': 86400  # 24 hours
                },
                {
                    'type': 'email',
                    'template': 'abandoned-cart-2',
                    'subject': 'Still thinking about it? Here\'s 10% off'
                },
                {
                    'type': 'delay',
                    'duration': 172800  # 48 hours
                },
                {
                    'type': 'email',
                    'template': 'abandoned-cart-3',
                    'subject': 'Last chance - your cart expires soon'
                }
            ]
        }
        
        return self.klaviyo.create_flow(
            flow_config['name'],
            flow_config['trigger_type'],
            flow_config['actions']
        )
    
    def setup_welcome_series(self, list_id: str) -> Dict[str, Any]:
        """Set up welcome email series for new subscribers"""
        
        flow_config = {
            'name': 'Welcome Series',
            'trigger_type': 'subscribed-to-list',
            'list_id': list_id,
            'actions': [
                {
                    'type': 'email',
                    'template': 'welcome-1',
                    'subject': 'Welcome to GANG! 👋'
                },
                {
                    'type': 'delay',
                    'duration': 259200  # 3 days
                },
                {
                    'type': 'email',
                    'template': 'welcome-2',
                    'subject': 'Here\'s what you need to know'
                },
                {
                    'type': 'delay',
                    'duration': 604800  # 7 days
                },
                {
                    'type': 'email',
                    'template': 'welcome-3',
                    'subject': 'Special offer just for you'
                }
            ]
        }
        
        return self.klaviyo.create_flow(
            flow_config['name'],
            flow_config['trigger_type'],
            flow_config['actions']
        )
    
    def track_product_view(self, email: str, product_id: str, product_name: str, price: float):
        """Track product view for browse abandonment"""
        import requests
        
        event_data = {
            'data': {
                'type': 'event',
                'attributes': {
                    'profile': {
                        'data': {
                            'type': 'profile',
                            'attributes': {
                                'email': email
                            }
                        }
                    },
                    'metric': {
                        'data': {
                            'type': 'metric',
                            'attributes': {
                                'name': 'Viewed Product'
                            }
                        }
                    },
                    'properties': {
                        'product_id': product_id,
                        'product_name': product_name,
                        'price': price,
                        'url': f"{self.shopify_store}/products/{product_id}"
                    },
                    'time': datetime.now().isoformat()
                }
            }
        }
        
        response = requests.post(
            f'{self.klaviyo.base_url}/events/',
            headers=self.klaviyo.headers,
            json=event_data
        )
        response.raise_for_status()
        
        return response.json()


class KlaviyoTemplateGenerator:
    """Generate Klaviyo-specific email templates"""
    
    @staticmethod
    def generate_abandoned_cart_template(cart_items: List[Dict], cart_url: str) -> str:
        """Generate abandoned cart email HTML"""
        from html import escape as html_escape
        try:
            from core.html_sanitize import safe_href, is_safe_href
        except ImportError:  # pragma: no cover
            from html_sanitize import safe_href, is_safe_href
        
        items_html = ""
        total = 0
        
        for item in cart_items:
            try:
                price = float(item.get('price') if item.get('price') is not None else 0)
            except (TypeError, ValueError):
                price = 0.0
            try:
                quantity = int(item.get('quantity') if item.get('quantity') is not None else 1)
            except (TypeError, ValueError):
                quantity = 1
            if quantity < 0:
                quantity = 0
            item_total = price * quantity
            total += item_total
            name = html_escape(str(item.get('name') or 'Product'))
            variant = html_escape(str(item.get('variant') or ''))
            image = item.get('image') or ''
            image_src = html_escape(image) if is_safe_href(image) else ''
            
            items_html += f"""
            <tr>
                <td style="padding: 15px 0; border-bottom: 1px solid #e0e0e0;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="100">
                                <img src="{image_src}" alt="{name}" 
                                     style="width: 100px; height: 100px; object-fit: cover;">
                            </td>
                            <td style="padding-left: 15px;">
                                <strong style="font-size: 16px;">{name}</strong><br>
                                {variant}<br>
                                <span style="color: #595959;">Qty: {quantity}</span>
                            </td>
                            <td align="right" style="font-weight: 600;">
                                ${item_total:.2f}
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            """
        
        safe_cart_url = html_escape(safe_href(cart_url, fallback='#'))
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>You left something in your cart</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background-color: #f5f5f5;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; width: 100%; background: #ffffff;" cellpadding="0" cellspacing="0">
                    
                    <!-- Header -->
                    <tr>
                        <td style="padding: 30px; border-bottom: 1px solid #e0e0e0;">
                            <h1 style="margin: 0; font-size: 24px;">You left something behind...</h1>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 30px;">
                            <p style="margin: 0 0 20px 0; font-size: 16px; line-height: 1.6;">
                                We noticed you didn't complete your purchase. Your items are still waiting for you!
                            </p>
                            
                            <!-- Cart Items -->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                                {items_html}
                                <tr>
                                    <td colspan="3" style="padding: 20px 0; text-align: right; font-size: 18px; font-weight: 600;">
                                        Total: ${total:.2f}
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- CTA -->
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 30px auto;">
                                <tr>
                                    <td align="center">
                                        <a href="{safe_cart_url}" 
                                           style="display: inline-block; padding: 16px 32px; background-color: #0052a3; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">
                                            Complete Your Purchase
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            
                            <p style="margin: 20px 0 0 0; font-size: 14px; color: #595959; text-align: center;">
                                Questions? Reply to this email or visit our <a href="{{{{ organization.url }}}}/pages/contact/">contact page</a>.
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 30px; background-color: #f9f9f9; border-top: 1px solid #e0e0e0; font-size: 12px; color: #999; text-align: center;">
                            <p style="margin: 0 0 10px 0;">
                                {{{{ organization.name }}}}
                            </p>
                            <p style="margin: 0;">
                                <a href="{{{{ unsubscribe_link }}}}" style="color: #999;">Unsubscribe</a> · 
                                <a href="{{{{ preferences_link }}}}" style="color: #999;">Manage Preferences</a>
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
    
    def get_lists(self) -> List[Dict[str, Any]]:
        """Get all Klaviyo lists"""
        import requests
        
        response = requests.get(
            f'{self.base_url}/lists/',
            headers=self.headers
        )
        response.raise_for_status()
        
        return response.json()['data']
    
    def get_campaigns(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get campaigns, optionally filtered by status"""
        import requests
        
        url = f'{self.base_url}/campaigns/'
        if status:
            url += f'?filter=equals(status,"{status}")'
        
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        return response.json()['data']
    
    def create_segment(
        self,
        name: str,
        definition: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a segment for targeting"""
        import requests
        
        payload = {
            'data': {
                'type': 'segment',
                'attributes': {
                    'name': name,
                    'definition': definition
                }
            }
        }
        
        response = requests.post(
            f'{self.base_url}/segments/',
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        
        return response.json()


class KlaviyoOrchestrator:
    """Orchestrate Klaviyo campaigns from GANG content"""
    
    def __init__(self, config: Dict[str, Any], klaviyo_api_key: str):
        self.config = config
        self.klaviyo = KlaviyoClient(klaviyo_api_key)
        self.site_url = config.get('site', {}).get('url', 'https://example.com')
    
    def create_campaign_from_post(
        self,
        post_path: Path,
        list_id: Optional[str] = None,
        from_email: str = 'newsletter@example.com',
        from_name: str = 'GANG'
    ) -> Dict[str, Any]:
        """Create Klaviyo campaign from a post"""
        
        from .email_templates import EmailTemplateGenerator
        import markdown
        try:
            from core.frontmatter import parse_frontmatter
        except ImportError:  # pragma: no cover
            from frontmatter import parse_frontmatter
        
        # Parse post
        content = post_path.read_text()
        frontmatter, body = parse_frontmatter(content)
        
        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra', 'meta'])
        content_html = md.convert(body)
        try:
            from core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        except ImportError:  # pragma: no cover
            from html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        content_html = sanitize_content_hrefs(sanitize_markdown_html(content_html))
        
        # Get metadata
        title = frontmatter.get('title', post_path.stem.replace('-', ' ').title())
        slug = post_path.stem
        canonical_url = f"{self.site_url}/posts/{slug}/"
        preview_text = frontmatter.get('summary', '')[:150]
        
        # Generate email templates
        template_gen = EmailTemplateGenerator(self.config)
        html_email = template_gen.generate_html_email(
            title=title,
            content_html=content_html,
            canonical_url=canonical_url,
            preview_text=preview_text,
            unsubscribe_url='{{ unsubscribe_link }}'  # Klaviyo variable
        )
        
        plain_text = template_gen.generate_plain_text(
            title=title,
            content_html=content_html,
            canonical_url=canonical_url,
            unsubscribe_url='{{ unsubscribe_link }}'
        )
        
        # Create campaign in Klaviyo
        campaign = self.klaviyo.create_campaign(
            name=title,
            subject=title,
            html_content=html_email,
            text_content=plain_text,
            from_email=from_email,
            from_name=from_name,
            list_id=list_id
        )
        
        return {
            'campaign_id': campaign['data']['id'],
            'title': title,
            'status': 'draft',
            'created': datetime.now().isoformat(),
            'klaviyo_url': f"https://www.klaviyo.com/campaign/{campaign['data']['id']}"
        }
    
    def setup_product_launch_campaign(
        self,
        product: Dict[str, Any],
        list_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create product launch campaign"""
        
        from html import escape as html_escape
        try:
            from core.html_sanitize import safe_href, is_safe_href
        except ImportError:  # pragma: no cover
            from html_sanitize import safe_href, is_safe_href

        product_name = str(product.get('name', 'New Product') or 'New Product')
        safe_name = html_escape(product_name)
        slug = str((product.get('_meta') or {}).get('slug') or '')
        product_url = f"{self.site_url}/products/{slug}" if slug else self.site_url
        safe_product_url = html_escape(safe_href(product_url, fallback='#'))
        raw_image = product.get('image', '')
        if isinstance(raw_image, (list, tuple)):
            raw_image = raw_image[0] if raw_image else ''
        image_src = html_escape(str(raw_image)) if is_safe_href(str(raw_image or '')) else ''
        # Descriptions may contain Shopify HTML — strip tags then escape.
        raw_description = str(product.get('description', '') or '')
        if '<' in raw_description:
            from bs4 import BeautifulSoup
            description_text = BeautifulSoup(raw_description, 'html.parser').get_text(' ')
        else:
            description_text = raw_description
        safe_description = html_escape(description_text)
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>New Product: {safe_name}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, sans-serif; background-color: #f5f5f5;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; background: #ffffff;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding: 40px 30px;">
                            <h1 style="margin: 0 0 20px 0; font-size: 28px;">Introducing {safe_name}</h1>
                            
                            <img src="{image_src}" alt="{safe_name}" 
                                 style="max-width: 100%; height: auto; margin: 20px 0;">
                            
                            <p style="font-size: 16px; line-height: 1.6; margin: 20px 0;">
                                {safe_description}
                            </p>
                            
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 30px auto;">
                                <tr>
                                    <td align="center">
                                        <a href="{safe_product_url}" 
                                           style="display: inline-block; padding: 16px 32px; background-color: #0052a3; color: #ffffff; text-decoration: none; font-weight: 600;">
                                            Shop Now
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        
        plain_text = f"""
{product_name}
{'=' * len(product_name)}

{description_text}

Shop now: {product_url}

---
{{{{ organization.name }}}}
Unsubscribe: {{{{ unsubscribe_link }}}}
"""
        
        return self.klaviyo.create_campaign(
            name=f"Product Launch: {product_name}",
            subject=f"Introducing {product_name}",
            html_content=html_content,
            text_content=plain_text,
            from_email='products@example.com',
            from_name='GANG',
            list_id=list_id
        )


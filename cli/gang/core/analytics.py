"""
GANG Analytics Integration
Server-side analytics without JavaScript.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import os


class CloudflareAnalytics:
    """
    Integrate with Cloudflare Analytics API.
    No JavaScript required - pure server-side tracking.
    """
    
    def __init__(self, account_id: str, api_token: str, zone_id: str):
        self.account_id = account_id
        self.api_token = api_token
        self.zone_id = zone_id
        self.base_url = "https://api.cloudflare.com/client/v4"
    
    def get_analytics(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Fetch analytics from Cloudflare.
        Returns page views, bandwidth, requests, etc.
        """
        
        try:
            import requests
            
            url = f"{self.base_url}/zones/{self.zone_id}/analytics/dashboard"
            headers = {
                'Authorization': f'Bearer {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'since': start_date.isoformat(),
                'until': end_date.isoformat(),
                'continuous': 'true'
            }
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            return response.json()
        
        except Exception as e:
            return {'error': str(e)}
    
    def get_top_pages(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get top pages by views"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # This would use Cloudflare GraphQL API
        # For now, return structure
        return []
    
    def generate_analytics_widget(self, days: int = 7) -> str:
        """
        Generate HTML widget showing analytics.
        Uses data attributes for progressive enhancement.
        """
        return f'''
        <div class="analytics-widget" data-analytics-days="{days}">
            <h3>Site Analytics (Last {days} days)</h3>
            <div class="analytics-stats">
                <div class="stat">
                    <span class="stat-label">Page Views</span>
                    <span class="stat-value" data-metric="pageviews">Loading...</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Visitors</span>
                    <span class="stat-value" data-metric="visitors">Loading...</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Bandwidth</span>
                    <span class="stat-value" data-metric="bandwidth">Loading...</span>
                </div>
            </div>
            <noscript>
                <p>Analytics available in Cloudflare Dashboard</p>
            </noscript>
        </div>
        '''


class ServerSideBeacon:
    """
    Server-side analytics beacon (no JS).
    Uses 1x1 pixel image for tracking.
    """
    
    @staticmethod
    def generate_beacon_html(
        page_url: str,
        site_id: str,
        endpoint: str = "https://analytics.yoursite.com/beacon"
    ) -> str:
        """
        Generate HTML for server-side tracking beacon.
        This is a 1x1 transparent pixel that tracks page views.
        """
        
        # URL-encode page info
        import urllib.parse
        params = urllib.parse.urlencode({
            'url': page_url,
            'site': site_id,
            'ref': '',  # Will be filled by server from Referer header
            't': int(datetime.now().timestamp())
        })
        
        return f'<img src="{endpoint}?{params}" alt="" width="1" height="1" style="position:absolute;left:-9999px" aria-hidden="true">'
    
    @staticmethod
    def generate_noscript_beacon(
        page_url: str,
        site_id: str,
        endpoint: str
    ) -> str:
        """
        Generate noscript beacon (works even without JS).
        """
        import urllib.parse
        params = urllib.parse.urlencode({
            'url': page_url,
            'site': site_id,
            'noscript': '1'
        })
        
        return f'<noscript><img src="{endpoint}?{params}" alt="" width="1" height="1" style="display:none" aria-hidden="true"></noscript>'


class AnalyticsConfig:
    """Analytics configuration and setup"""
    
    CLOUDFLARE_ANALYTICS_SCRIPT = '''
    <!-- Cloudflare Web Analytics -->
    <script defer src='https://static.cloudflare.com/beacon.min.js' 
            data-cf-beacon='{"token": "YOUR_TOKEN_HERE"}'></script>
    '''
    
    NO_JS_BEACON = '''
    <!-- Server-side analytics beacon (no JS required) -->
    <img src="/api/analytics/beacon?page={page_url}" 
         alt="" 
         width="1" 
         height="1" 
         style="position:absolute;left:-9999px" 
         aria-hidden="true">
    '''
    
    @staticmethod
    def get_setup_instructions() -> str:
        """Get analytics setup instructions"""
        return """
# Analytics Setup - Zero JavaScript Required!

## Option 1: Cloudflare Analytics (Built-in, FREE)

Already active on your Cloudflare account!

**How to access:**
1. Go to Cloudflare Dashboard
2. Select your site
3. Click "Analytics" in sidebar
4. View: Page views, bandwidth, requests, cache stats

**Advantages:**
- ✅ Zero configuration needed
- ✅ No JS required
- ✅ No performance impact
- ✅ Privacy-friendly
- ✅ Always accurate (CDN-level tracking)

**What you get:**
- Page views by URL
- Traffic by country
- Bandwidth usage
- Cache hit ratio
- Security events
- Performance metrics


## Option 2: Cloudflare Web Analytics (More Detailed)

Adds visitor-level tracking (still privacy-friendly).

**Setup:**
1. Cloudflare Dashboard → Analytics → Web Analytics
2. Create site
3. Copy token
4. Add to your config:

```yaml
analytics:
  cloudflare_token: your-token-here
```

GANG will auto-inject the beacon (tiny JS, ~1KB).

**What you get:**
- All of Option 1 +
- Page views by page
- Referrers
- Browsers/devices
- Visit duration
- Bounce rate


## Option 3: Server-Side Beacon (100% JS-Free)

Pure server-side tracking with 1x1 pixel.

**Setup:**
```yaml
analytics:
  mode: server_beacon
  endpoint: https://your-analytics.com/beacon
```

GANG will inject a 1px image in every page that pings your analytics endpoint.

**How it works:**
- Browser requests page
- Page includes <img src="/beacon?page=X">
- Server logs the request
- You analyze server logs


## Recommendation

**Use Cloudflare Analytics (Option 1)** - it's already working!

- Zero setup
- Zero JS
- Zero performance impact
- Free forever
- GDPR compliant

**Add Cloudflare Web Analytics (Option 2)** if you need more detail.

**Skip custom solutions** unless you have specific privacy/compliance needs.


## GANG Integration

Add to your config to show analytics in CLI:

```yaml
analytics:
  provider: cloudflare
  account_id: your-account-id
  api_token: your-api-token
  zone_id: your-zone-id
```

Then:
```bash
gang analytics --days 7    # Show last 7 days
gang analytics --top-pages # Top content
```
"""


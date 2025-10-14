"""
GANG Content Syndicator
Auto-publish to multiple platforms with canonical links.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import os
import hashlib


class ContentSyndicator:
    """Syndicate content to multiple platforms"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.canonical_url = config.get('site', {}).get('url', '')
        self.platforms = self._load_platform_configs()
    
    def _load_platform_configs(self) -> Dict[str, Any]:
        """Load API keys and configs for each platform"""
        return {
            'devto': {
                'api_key': os.environ.get('DEVTO_API_KEY'),
                'enabled': bool(os.environ.get('DEVTO_API_KEY'))
            },
            'medium': {
                'token': os.environ.get('MEDIUM_INTEGRATION_TOKEN'),
                'enabled': bool(os.environ.get('MEDIUM_INTEGRATION_TOKEN'))
            },
            'hashnode': {
                'token': os.environ.get('HASHNODE_API_KEY'),
                'publication_id': os.environ.get('HASHNODE_PUBLICATION_ID'),
                'enabled': bool(os.environ.get('HASHNODE_API_KEY'))
            },
            'linkedin': {
                'token': os.environ.get('LINKEDIN_ACCESS_TOKEN'),
                'enabled': bool(os.environ.get('LINKEDIN_ACCESS_TOKEN'))
            }
        }
    
    def syndicate_post(
        self,
        file_path: Path,
        platforms: List[str] = None
    ) -> Dict[str, Any]:
        """
        Syndicate a single post to specified platforms.
        Returns results for each platform.
        """
        
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
        
        # Check if already syndicated
        syndicated = frontmatter.get('syndicated', {})
        
        # Determine platforms
        if not platforms:
            platforms = [p for p, config in self.platforms.items() if config['enabled']]
        
        # Build canonical URL
        slug = file_path.stem
        canonical = f"{self.canonical_url}/posts/{slug}/"
        
        results = {}
        
        for platform in platforms:
            if platform in syndicated:
                results[platform] = {'status': 'already_syndicated', 'url': syndicated[platform]}
                continue
            
            if platform == 'devto':
                result = self._syndicate_to_devto(frontmatter, body, canonical)
            elif platform == 'medium':
                result = self._syndicate_to_medium(frontmatter, body, canonical)
            elif platform == 'hashnode':
                result = self._syndicate_to_hashnode(frontmatter, body, canonical)
            elif platform == 'linkedin':
                result = self._syndicate_to_linkedin(frontmatter, body, canonical)
            else:
                result = {'status': 'unsupported', 'error': f'Platform {platform} not supported'}
            
            results[platform] = result
        
        return results
    
    def _syndicate_to_devto(
        self,
        frontmatter: Dict[str, Any],
        body: str,
        canonical: str
    ) -> Dict[str, Any]:
        """Syndicate to Dev.to"""
        
        api_key = self.platforms['devto']['api_key']
        if not api_key:
            return {'status': 'disabled', 'error': 'No API key'}
        
        try:
            import requests
            
            # Prepare article
            article = {
                'article': {
                    'title': frontmatter.get('title', ''),
                    'body_markdown': body,
                    'published': frontmatter.get('status') == 'published',
                    'canonical_url': canonical,
                    'tags': frontmatter.get('tags', [])[:4],  # Dev.to max 4 tags
                    'series': frontmatter.get('series')
                }
            }
            
            # Post to Dev.to
            response = requests.post(
                'https://dev.to/api/articles',
                headers={
                    'api-key': api_key,
                    'Content-Type': 'application/json'
                },
                json=article
            )
            
            if response.status_code == 201:
                data = response.json()
                return {
                    'status': 'success',
                    'url': data.get('url'),
                    'id': data.get('id')
                }
            else:
                return {
                    'status': 'error',
                    'error': response.json()
                }
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def _syndicate_to_medium(
        self,
        frontmatter: Dict[str, Any],
        body: str,
        canonical: str
    ) -> Dict[str, Any]:
        """Syndicate to Medium"""
        
        token = self.platforms['medium']['token']
        if not token:
            return {'status': 'disabled', 'error': 'No token'}
        
        try:
            import requests
            
            # Get user ID
            me_response = requests.get(
                'https://api.medium.com/v1/me',
                headers={'Authorization': f'Bearer {token}'}
            )
            
            if me_response.status_code != 200:
                return {'status': 'error', 'error': 'Failed to get user info'}
            
            user_id = me_response.json()['data']['id']
            
            # Create post
            post = {
                'title': frontmatter.get('title', ''),
                'contentFormat': 'markdown',
                'content': body,
                'canonicalUrl': canonical,
                'tags': frontmatter.get('tags', [])[:5],
                'publishStatus': 'draft'  # Always draft first for safety
            }
            
            response = requests.post(
                f'https://api.medium.com/v1/users/{user_id}/posts',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                json=post
            )
            
            if response.status_code == 201:
                data = response.json()['data']
                return {
                    'status': 'success',
                    'url': data.get('url'),
                    'id': data.get('id'),
                    'note': 'Published as draft - review on Medium before publishing'
                }
            else:
                return {'status': 'error', 'error': response.json()}
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def _syndicate_to_hashnode(
        self,
        frontmatter: Dict[str, Any],
        body: str,
        canonical: str
    ) -> Dict[str, Any]:
        """Syndicate to Hashnode"""
        
        token = self.platforms['hashnode']['token']
        pub_id = self.platforms['hashnode']['publication_id']
        
        if not token or not pub_id:
            return {'status': 'disabled', 'error': 'Missing token or publication ID'}
        
        try:
            import requests
            
            # Hashnode uses GraphQL
            query = '''
            mutation CreateStory($input: CreateStoryInput!) {
                createStory(input: $input) {
                    code
                    success
                    message
                    post {
                        slug
                        url
                    }
                }
            }
            '''
            
            variables = {
                'input': {
                    'title': frontmatter.get('title', ''),
                    'contentMarkdown': body,
                    'tags': [{'name': tag} for tag in frontmatter.get('tags', [])],
                    'publicationId': pub_id,
                    'isRepublished': {
                        'originalArticleURL': canonical
                    }
                }
            }
            
            response = requests.post(
                'https://api.hashnode.com/',
                headers={
                    'Authorization': token,
                    'Content-Type': 'application/json'
                },
                json={'query': query, 'variables': variables}
            )
            
            data = response.json()
            
            if data.get('data', {}).get('createStory', {}).get('success'):
                post = data['data']['createStory']['post']
                return {
                    'status': 'success',
                    'url': post.get('url'),
                    'slug': post.get('slug')
                }
            else:
                return {
                    'status': 'error',
                    'error': data.get('errors', 'Unknown error')
                }
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def _syndicate_to_linkedin(
        self,
        frontmatter: Dict[str, Any],
        body: str,
        canonical: str
    ) -> Dict[str, Any]:
        """Syndicate to LinkedIn"""
        
        # LinkedIn requires article creation via their API
        # Returns link to share
        
        title = frontmatter.get('title', '')
        summary = frontmatter.get('summary', body[:200])
        
        return {
            'status': 'manual',
            'share_url': f"https://www.linkedin.com/sharing/share-offsite/?url={canonical}",
            'note': 'LinkedIn API requires OAuth - use share URL to post manually'
        }
    
    def update_frontmatter_with_syndication(
        self,
        file_path: Path,
        results: Dict[str, Any]
    ) -> bool:
        """Update file frontmatter with syndication URLs"""
        
        import yaml
        
        content = file_path.read_text()
        parts = content.split('---', 2)
        
        if len(parts) < 3:
            return False
        
        frontmatter = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        
        # Add syndication URLs
        if 'syndicated' not in frontmatter:
            frontmatter['syndicated'] = {}
        
        for platform, result in results.items():
            if result.get('status') == 'success' and result.get('url'):
                frontmatter['syndicated'][platform] = result['url']
        
        # Write back
        new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
        file_path.write_text(new_content)
        
        return True


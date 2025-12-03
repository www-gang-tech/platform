"""
Comments Management Module

Handles reading, writing, and managing comment YAML files.
Integrates with the build system to include approved comments in templates.
"""

import os
import yaml
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
import click


class CommentsManager:
    """Manages comment files and operations."""
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
        self.comments_path = content_path / "comments"
        self.posts_comments_path = self.comments_path / "posts"
        self.products_comments_path = self.comments_path / "products"
        
        # Ensure directories exist
        self.posts_comments_path.mkdir(parents=True, exist_ok=True)
        self.products_comments_path.mkdir(parents=True, exist_ok=True)
    
    def get_comments_for_page(self, page_slug: str, page_type: str) -> List[Dict[str, Any]]:
        """Get all approved comments for a specific page."""
        comments = []
        
        if page_type == "post":
            comments_dir = self.posts_comments_path / page_slug
        elif page_type == "product":
            comments_dir = self.products_comments_path / page_slug
        else:
            return comments
        
        if not comments_dir.exists():
            return comments
        
        # Read all comment YAML files
        for comment_file in comments_dir.glob("comment-*.yml"):
            try:
                with open(comment_file, 'r', encoding='utf-8') as f:
                    comment_data = yaml.safe_load(f)
                
                # Only include approved comments
                if comment_data.get('status') == 'approved':
                    # Add formatted date for templates
                    comment_data['date_formatted'] = self._format_date(comment_data.get('date'))
                    # Add gravatar URL
                    comment_data['gravatar_url'] = self._get_gravatar_url(comment_data.get('author', {}).get('email_hash'))
                    comments.append(comment_data)
            
            except Exception as e:
                click.echo(f"Warning: Could not load comment {comment_file}: {e}", err=True)
                continue
        
        # Sort by date (oldest first)
        comments.sort(key=lambda x: x.get('date', ''))
        
        return comments
    
    def create_comment(self, page_slug: str, page_type: str, comment_data: Dict[str, Any]) -> str:
        """Create a new comment file."""
        # Generate comment ID
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        comment_id = f"comment-{timestamp}"
        
        # Hash email for privacy
        email = comment_data.get('author_email', '')
        email_hash = hashlib.md5(email.lower().encode()).hexdigest()
        
        # Prepare comment data
        comment = {
            'id': comment_id,
            'author': {
                'name': comment_data.get('author_name', ''),
                'email_hash': email_hash,
                'website': comment_data.get('author_website', '')
            },
            'date': datetime.now().isoformat() + 'Z',
            'content': comment_data.get('comment_content', ''),
            'status': 'pending',
            'parent_id': None
        }
        
        # Determine target directory
        if page_type == "post":
            target_dir = self.posts_comments_path / page_slug
        elif page_type == "product":
            target_dir = self.products_comments_path / page_slug
        else:
            raise ValueError(f"Unsupported page type: {page_type}")
        
        # Create directory if it doesn't exist
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Write comment file
        comment_file = target_dir / f"{comment_id}.yml"
        with open(comment_file, 'w', encoding='utf-8') as f:
            yaml.dump(comment, f, default_flow_style=False, allow_unicode=True)
        
        return comment_id
    
    def update_comment_status(self, comment_id: str, status: str) -> bool:
        """Update the status of a comment."""
        # Find the comment file
        for comments_dir in [self.posts_comments_path, self.products_comments_path]:
            for page_dir in comments_dir.iterdir():
                if page_dir.is_dir():
                    comment_file = page_dir / f"{comment_id}.yml"
                    if comment_file.exists():
                        try:
                            with open(comment_file, 'r', encoding='utf-8') as f:
                                comment_data = yaml.safe_load(f)
                            
                            comment_data['status'] = status
                            
                            with open(comment_file, 'w', encoding='utf-8') as f:
                                yaml.dump(comment_data, f, default_flow_style=False, allow_unicode=True)
                            
                            return True
                        except Exception as e:
                            click.echo(f"Error updating comment {comment_id}: {e}", err=True)
                            return False
        
        return False
    
    def delete_comment(self, comment_id: str) -> bool:
        """Delete a comment file."""
        # Find and delete the comment file
        for comments_dir in [self.posts_comments_path, self.products_comments_path]:
            for page_dir in comments_dir.iterdir():
                if page_dir.is_dir():
                    comment_file = page_dir / f"{comment_id}.yml"
                    if comment_file.exists():
                        try:
                            comment_file.unlink()
                            return True
                        except Exception as e:
                            click.echo(f"Error deleting comment {comment_id}: {e}", err=True)
                            return False
        
        return False
    
    def list_comments(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all comments, optionally filtered by status."""
        comments = []
        
        for comments_dir in [self.posts_comments_path, self.products_comments_path]:
            for page_dir in comments_dir.iterdir():
                if page_dir.is_dir():
                    for comment_file in page_dir.glob("comment-*.yml"):
                        try:
                            with open(comment_file, 'r', encoding='utf-8') as f:
                                comment_data = yaml.safe_load(f)
                            
                            # Apply status filter
                            if status_filter and comment_data.get('status') != status_filter:
                                continue
                            
                            # Add file path and page info
                            comment_data['file_path'] = str(comment_file)
                            comment_data['page_slug'] = page_dir.name
                            comment_data['page_type'] = 'post' if 'posts' in str(comments_dir) else 'product'
                            
                            comments.append(comment_data)
                        
                        except Exception as e:
                            click.echo(f"Warning: Could not load comment {comment_file}: {e}", err=True)
                            continue
        
        # Sort by date (newest first)
        comments.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        return comments
    
    def get_comment_stats(self) -> Dict[str, int]:
        """Get statistics about comments."""
        stats = {
            'total': 0,
            'approved': 0,
            'pending': 0,
            'spam': 0,
            'rejected': 0
        }
        
        for comment in self.list_comments():
            stats['total'] += 1
            status = comment.get('status', 'unknown')
            if status in stats:
                stats[status] += 1
        
        return stats
    
    def _format_date(self, date_str: str) -> str:
        """Format date string for display."""
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%B %d, %Y at %I:%M %p')
        except:
            return date_str
    
    def _get_gravatar_url(self, email_hash: str, size: int = 40) -> str:
        """Generate Gravatar URL from email hash."""
        if not email_hash:
            return ""
        return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon"
    
    def validate_comment_data(self, comment_data: Dict[str, Any]) -> List[str]:
        """Validate comment data and return list of errors."""
        errors = []
        
        # Required fields
        if not comment_data.get('author_name'):
            errors.append("Author name is required")
        
        if not comment_data.get('author_email'):
            errors.append("Author email is required")
        elif not self._is_valid_email(comment_data['author_email']):
            errors.append("Invalid email format")
        
        if not comment_data.get('comment_content'):
            errors.append("Comment content is required")
        elif len(comment_data['comment_content']) > 2000:
            errors.append("Comment content is too long (max 2000 characters)")
        
        # Optional website validation
        website = comment_data.get('author_website')
        if website and not self._is_valid_url(website):
            errors.append("Invalid website URL")
        
        return errors
    
    def _is_valid_email(self, email: str) -> bool:
        """Check if email format is valid."""
        import re
        pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return re.match(pattern, email) is not None
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL format is valid."""
        try:
            from urllib.parse import urlparse
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False


def get_comments_for_build(content_path: Path, page_slug: str, page_type: str) -> List[Dict[str, Any]]:
    """Get comments for a specific page during build process."""
    manager = CommentsManager(content_path)
    return manager.get_comments_for_page(page_slug, page_type)




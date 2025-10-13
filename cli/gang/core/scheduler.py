"""
GANG Content Scheduler
Handle scheduled publishing of content based on publish_date.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import yaml


class ContentScheduler:
    """Manage scheduled content publishing"""
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
    
    def get_publishable_content(self, content_files: List[Path]) -> Dict[str, Any]:
        """
        Filter content based on publish dates and status.
        Returns dict with publishable and scheduled content.
        """
        now = datetime.now(timezone.utc)
        
        publishable = []
        scheduled_future = []
        draft = []
        
        for file_path in content_files:
            content = file_path.read_text()
            
            # Parse frontmatter
            if not content.startswith('---'):
                # No frontmatter, include by default
                publishable.append({
                    'path': file_path,
                    'status': 'published',
                    'publish_date': None
                })
                continue
            
            parts = content.split('---', 2)
            if len(parts) < 3:
                publishable.append({
                    'path': file_path,
                    'status': 'published',
                    'publish_date': None
                })
                continue
            
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except:
                # Invalid YAML, include anyway
                publishable.append({
                    'path': file_path,
                    'status': 'published',
                    'publish_date': None
                })
                continue
            
            # Get status
            status = frontmatter.get('status', 'published')
            
            # If status is draft, skip
            if status == 'draft':
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue
            
            # Check publish_date
            publish_date_str = frontmatter.get('publish_date')
            
            if not publish_date_str:
                # No publish date, publish immediately
                publishable.append({
                    'path': file_path,
                    'status': status,
                    'publish_date': None
                })
                continue
            
            # Parse publish date
            try:
                if isinstance(publish_date_str, datetime):
                    publish_date = publish_date_str
                else:
                    # Try to parse ISO format
                    publish_date = datetime.fromisoformat(str(publish_date_str).replace('Z', '+00:00'))
                
                # Ensure timezone aware
                if publish_date.tzinfo is None:
                    publish_date = publish_date.replace(tzinfo=timezone.utc)
                
                # Check if publish date has passed
                if publish_date <= now:
                    publishable.append({
                        'path': file_path,
                        'status': 'published',
                        'publish_date': publish_date,
                        'title': frontmatter.get('title', file_path.stem)
                    })
                else:
                    scheduled_future.append({
                        'path': file_path,
                        'status': 'scheduled',
                        'publish_date': publish_date,
                        'title': frontmatter.get('title', file_path.stem)
                    })
            
            except (ValueError, TypeError) as e:
                # Invalid date format, include anyway
                publishable.append({
                    'path': file_path,
                    'status': status,
                    'publish_date': None,
                    'error': f'Invalid date format: {e}'
                })
        
        return {
            'publishable': publishable,
            'scheduled': scheduled_future,
            'draft': draft,
            'now': now
        }
    
    def get_scheduled_summary(self) -> Dict[str, Any]:
        """Get summary of all scheduled content"""
        all_files = list(self.content_path.rglob('*.md'))
        result = self.get_publishable_content(all_files)
        
        return {
            'total_files': len(all_files),
            'publishable': len(result['publishable']),
            'scheduled': len(result['scheduled']),
            'draft': len(result['draft']),
            'scheduled_items': result['scheduled'],
            'draft_items': result['draft']
        }
    
    def format_schedule_report(self, summary: Dict[str, Any]) -> str:
        """Format a human-readable schedule report"""
        lines = []
        lines.append("📅 Content Schedule Report")
        lines.append("=" * 60)
        lines.append(f"Total content files: {summary['total_files']}")
        lines.append(f"✅ Published/Publishable: {summary['publishable']}")
        lines.append(f"🕐 Scheduled (future): {summary['scheduled']}")
        lines.append(f"📝 Draft: {summary['draft']}")
        
        if summary['scheduled_items']:
            lines.append("\n📋 Upcoming Scheduled Posts:")
            lines.append("-" * 60)
            
            # Sort by publish date
            sorted_items = sorted(
                summary['scheduled_items'],
                key=lambda x: x['publish_date']
            )
            
            for item in sorted_items:
                pub_date = item['publish_date']
                title = item['title']
                path = item['path']
                
                # Format relative time
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                delta = pub_date - now
                
                if delta.days > 0:
                    time_str = f"in {delta.days} day(s)"
                elif delta.seconds > 3600:
                    hours = delta.seconds // 3600
                    time_str = f"in {hours} hour(s)"
                else:
                    minutes = delta.seconds // 60
                    time_str = f"in {minutes} minute(s)"
                
                lines.append(f"  📅 {pub_date.strftime('%Y-%m-%d %H:%M')} ({time_str})")
                lines.append(f"     {title}")
                lines.append(f"     {path.relative_to(self.content_path)}")
                lines.append("")
        
        if summary['draft_items']:
            lines.append("\n📝 Draft Posts:")
            lines.append("-" * 60)
            for item in summary['draft_items']:
                lines.append(f"  • {item['title']}")
                lines.append(f"    {item['path'].relative_to(self.content_path)}")
        
        return '\n'.join(lines)
    
    def set_publish_date(
        self, 
        file_path: Path, 
        publish_date: Optional[datetime] = None,
        status: str = 'scheduled'
    ) -> bool:
        """
        Set or update publish_date in a content file's frontmatter.
        If publish_date is None, removes it.
        """
        if not file_path.exists():
            return False
        
        content = file_path.read_text()
        
        # Parse frontmatter
        if not content.startswith('---'):
            # No frontmatter, create one
            frontmatter = {
                'status': status
            }
            if publish_date:
                frontmatter['publish_date'] = publish_date.isoformat()
            
            new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{content}"
            file_path.write_text(new_content)
            return True
        
        parts = content.split('---', 2)
        if len(parts) < 3:
            return False
        
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except:
            return False
        
        # Update frontmatter
        if publish_date:
            frontmatter['publish_date'] = publish_date.isoformat()
            frontmatter['status'] = status
        else:
            # Remove publish_date if exists
            frontmatter.pop('publish_date', None)
            if frontmatter.get('status') == 'scheduled':
                frontmatter['status'] = 'published'
        
        # Write back
        body = parts[2]
        new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
        file_path.write_text(new_content)
        
        return True


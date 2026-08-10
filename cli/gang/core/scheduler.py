"""
GANG Content Scheduler
Handle scheduled publishing of content based on publish_date.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import yaml
from core.frontmatter import dump_frontmatter, parse_frontmatter


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
            
            frontmatter, _body = parse_frontmatter(content)
            if not frontmatter and not content.startswith('---'):
                publishable.append({
                    'path': file_path,
                    'status': 'published',
                    'publish_date': None
                })
                continue
            
            # Get status
            status = frontmatter.get('status', 'published')
            status_norm = str(status or 'published').strip().lower()
            blocked_statuses = {
                'draft', 'private', 'archived', 'unlisted', 'hidden', 'deleted'
            }

            # Non-public statuses never publish, even with a past publish_date.
            if status_norm in blocked_statuses:
                draft.append({
                    'path': file_path,
                    'status': status_norm,
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue
            
            # Check publish_date
            publish_date_str = frontmatter.get('publish_date')

            # Explicitly scheduled content without a date stays unpublished.
            if status_norm == 'scheduled' and not publish_date_str:
                scheduled_future.append({
                    'path': file_path,
                    'status': 'scheduled',
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue
            
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
                # Invalid date must not publish scheduled/private-intent content.
                draft.append({
                    'path': file_path,
                    'status': status or 'draft',
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
            
            # Sort by publish date; undated scheduled items sort last.
            from datetime import datetime, timezone
            max_dt = datetime.max.replace(tzinfo=timezone.utc)

            def _schedule_sort_key(item):
                pub_date = item.get('publish_date')
                if isinstance(pub_date, datetime):
                    if pub_date.tzinfo is None:
                        return pub_date.replace(tzinfo=timezone.utc)
                    return pub_date
                return max_dt

            sorted_items = sorted(
                summary['scheduled_items'],
                key=_schedule_sort_key,
            )
            
            for item in sorted_items:
                pub_date = item['publish_date']
                title = item['title']
                path = item['path']

                if not isinstance(pub_date, datetime):
                    lines.append("  📅 (no publish_date)")
                    lines.append(f"     {title}")
                    lines.append(f"     {path.relative_to(self.content_path)}")
                    lines.append("")
                    continue
                
                # Format relative time
                now = datetime.now(timezone.utc)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
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
            
            new_content = dump_frontmatter(frontmatter, content)
            file_path.write_text(new_content)
            return True
        
        frontmatter, body = parse_frontmatter(content)
        if not content.startswith('---'):
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
        new_content = dump_frontmatter(frontmatter, body)
        file_path.write_text(new_content)
        
        return True


"""
GANG Content Scheduler
Handle scheduled publishing of content based on publish_date.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import yaml


def _absent_schedule_date(value: Any) -> bool:
    """True when publish_date/scheduled_for should be treated as missing."""
    if value is None or value is False:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return True
    return False


def parse_schedule_datetime(value: Any) -> datetime:
    """Parse ISO/YAML dates; accept Z/z UTC suffixes and naive values as UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith(('Z', 'z')):
            text = text[:-1] + '+00:00'
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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
            
            # Parse frontmatter. Missing or truncated YAML must not go live.
            if not content.startswith('---'):
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': file_path.stem,
                    '_yaml_error': True,
                    'error': 'missing frontmatter',
                })
                continue
            
            parts = content.split('---', 2)
            if len(parts) < 3:
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': file_path.stem,
                    '_yaml_error': True,
                    'error': 'malformed frontmatter delimiters',
                })
                continue
            
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except Exception:
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': file_path.stem,
                    '_yaml_error': True,
                })
                continue

            if not isinstance(frontmatter, dict):
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': file_path.stem,
                    '_yaml_error': True,
                })
                continue
            
            # Get status (YAML `no`/`false` and list wrappers must not publish).
            # Missing key defaults to published; explicit null/empty fails closed.
            if 'status' not in frontmatter:
                raw_status = 'published'
            else:
                raw_status = frontmatter.get('status')
            if isinstance(raw_status, list) and raw_status:
                raw_status = raw_status[0]
            if raw_status is False:
                status = 'draft'
            elif raw_status is True or isinstance(raw_status, (int, float)):
                # Bool/numeric YAML must not silently publish
                status = 'draft'
            elif raw_status is None or (isinstance(raw_status, str) and not raw_status.strip()):
                status = 'draft'
            else:
                status = str(raw_status).strip().lower()
            
            # Allowlist only: unknown/archived/pending/true/yes fail closed as draft.
            # `sent` keeps already-emailed newsletters on the static site.
            if status not in ('published', 'scheduled', 'live', 'public', 'sent'):
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue
            
            # Check publish_date (scheduled_for is the newsletter alias).
            # Whitespace, false, and empty collections must not block the alias.
            publish_date_str = frontmatter.get('publish_date')
            if _absent_schedule_date(publish_date_str):
                publish_date_str = frontmatter.get('scheduled_for')
            if isinstance(publish_date_str, str):
                publish_date_str = publish_date_str.strip() or None
            if _absent_schedule_date(publish_date_str):
                publish_date_str = None
            
            if _absent_schedule_date(publish_date_str):
                # Scheduled without a date is invalid — fail closed so it cannot go live.
                if status == 'scheduled':
                    draft.append({
                        'path': file_path,
                        'status': 'draft',
                        'publish_date': None,
                        'title': frontmatter.get('title', file_path.stem),
                        'error': 'status=scheduled requires publish_date',
                    })
                    continue
                publishable.append({
                    'path': file_path,
                    'status': status,
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue
            
            # Parse publish date
            try:
                publish_date = parse_schedule_datetime(publish_date_str)
                
                # Already-sent newsletters stay live even if publish_date is still future.
                if status == 'sent' or publish_date <= now:
                    publishable.append({
                        'path': file_path,
                        'status': 'sent' if status == 'sent' else 'published',
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
                # Invalid date format — fail closed so a typo cannot publish early
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem),
                    '_date_error': True,
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
        # Match the build collector: top-level category dirs, not products/*.md
        category_dirs = ('posts', 'articles', 'pages', 'projects', 'newsletters', 'people')
        all_files = []
        for category in category_dirs:
            directory = self.content_path / category
            if directory.is_dir():
                all_files.extend(sorted(directory.glob('*.md')))
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
        except Exception:
            return False
        if not isinstance(frontmatter, dict):
            return False
        
        # Update frontmatter
        if publish_date:
            iso = publish_date.isoformat()
            frontmatter['publish_date'] = iso
            if 'scheduled_for' in frontmatter:
                frontmatter['scheduled_for'] = iso
            frontmatter['status'] = status
        else:
            # Remove both date keys so --now cannot leave a future scheduled_for.
            frontmatter.pop('publish_date', None)
            frontmatter.pop('scheduled_for', None)
            allowed = ('draft', 'scheduled', 'published', 'live', 'public', 'sent')
            frontmatter['status'] = status if status in allowed else 'published'
        
        # Write back
        body = parts[2]
        new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
        file_path.write_text(new_content)
        
        return True


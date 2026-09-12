"""
GANG Content Scheduler
Handle scheduled publishing of content based on publish_date.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import re
import yaml

_PLACEHOLDER_CAMPAIGN_IDS = {
    '0', 'false', 'true', 'none', 'null', 'pending', 'tbd', 'n/a', 'na',
}


def strip_frontmatter_prefix(content: str) -> str:
    """Drop UTF-8 BOM and leading whitespace so ``---`` frontmatter is still found."""
    if not content:
        return content
    if content.startswith('\ufeff'):
        content = content[1:]
    return content.lstrip('\ufeff \t\r\n')


def _unwrap_schedule_value(value: Any) -> Any:
    """CMS/ESP exports sometimes wrap a single date or status in a list."""
    seen = 0
    # Deep single-element wraps from CMS/ESP dumps; 64 is a cycle/DoS cap.
    while isinstance(value, (list, tuple)) and len(value) == 1 and seen < 64:
        value = value[0]
        seen += 1
    return value


def _absent_schedule_date(value: Any) -> bool:
    """True when publish_date/scheduled_for should be treated as missing."""
    value = _unwrap_schedule_value(value)
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
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Match the CLI fallback so frontmatter "2025-12-25 9:00" parses.
            padded = re.sub(r'(?<=[\sT])(\d):', r'0\1:', text, count=1)
            parsed = None
            for candidate in (text, padded):
                for fmt in (
                    '%Y-%m-%d',
                    '%Y-%m-%d %H:%M',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%dT%H:%M',
                    '%Y-%m-%dT%H:%M:%S',
                ):
                    try:
                        parsed = datetime.strptime(candidate, fmt)
                        break
                    except ValueError:
                        continue
                if parsed is not None:
                    break
            if parsed is None:
                raise ValueError(f'Invalid datetime: {value!r}')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def frontmatter_values(frontmatter: Dict[str, Any], *names: str) -> List[Any]:
    """Collect values for schedule keys regardless of YAML key case."""
    if not isinstance(frontmatter, dict) or not names:
        return []
    wanted = {name.lower() for name in names}
    return [
        value
        for key, value in frontmatter.items()
        if isinstance(key, str) and key.lower() in wanted
    ]


def drop_frontmatter_aliases(frontmatter: Dict[str, Any], *names: str) -> None:
    """Remove non-canonical case variants so writes do not leave Status: sent."""
    if not isinstance(frontmatter, dict) or not names:
        return
    wanted = {name.lower() for name in names}
    for key in list(frontmatter):
        if isinstance(key, str) and key.lower() in wanted and key not in names:
            frontmatter.pop(key, None)


def resolve_schedule_status(frontmatter: Dict[str, Any], *, newsletter: bool) -> str:
    """Read status case-insensitively; conflicting keys fail closed as draft."""
    values = frontmatter_values(frontmatter, 'status')
    if not values:
        return _normalize_schedule_status(None, newsletter=newsletter, missing=True)
    norms = [
        _normalize_schedule_status(value, newsletter=newsletter, missing=False)
        for value in values
    ]
    unique = set(norms)
    # Mixed lists that include sent are not a send receipt.
    if 'sent' in unique and len(unique) != 1:
        return 'draft'
    if unique == {'sent'}:
        return 'sent'
    if len(unique) != 1:
        return 'draft'
    return norms[0]


def _is_newsletter_receipt_value(name: str, value: Any) -> bool:
    """True when one receipt field looks like a real ESP send record."""
    value = _unwrap_schedule_value(value)
    if _absent_schedule_date(value):
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return False
    if name in ('sent_at', 'sent_date'):
        if isinstance(value, bool):
            return False
        try:
            parse_schedule_datetime(value)
            return True
        except (ValueError, TypeError):
            return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        token = value.strip()
        if not token or token.lower() in _PLACEHOLDER_CAMPAIGN_IDS:
            return False
        return True
    return False


def newsletter_send_receipt(frontmatter: Dict[str, Any]) -> bool:
    """True when frontmatter has evidence of a real campaign send."""
    if not isinstance(frontmatter, dict):
        return False
    for name in ('sent_at', 'sent_date', 'campaign_id'):
        for value in frontmatter_values(frontmatter, name):
            if _is_newsletter_receipt_value(name, value):
                return True
    return False


def drop_newsletter_receipts(frontmatter: Dict[str, Any]) -> None:
    """Remove send-receipt keys so drafts cannot inherit a spoofed archive."""
    if not isinstance(frontmatter, dict):
        return
    drop_frontmatter_aliases(frontmatter, 'sent_at', 'sent_date', 'campaign_id')
    for key in ('sent_at', 'sent_date', 'campaign_id'):
        frontmatter.pop(key, None)


def has_unparseable_schedule_date(*values: Any) -> bool:
    """True when a date field is present but cannot be parsed."""
    for value in values:
        value = _unwrap_schedule_value(value)
        if _absent_schedule_date(value):
            continue
        if isinstance(value, (list, tuple, dict, set)):
            return True
        try:
            parse_schedule_datetime(value)
        except (ValueError, TypeError):
            return True
    return False


def _parse_first_schedule_date(*values: Any) -> Optional[datetime]:
    """Parse present, well-formed schedule dates and return the latest instant.

    A stale past ``publish_date`` must not beat a later ``scheduled_for``
    (or the reverse) when gating publish or send.
    """
    parsed_dates = []
    for value in values:
        value = _unwrap_schedule_value(value)
        if _absent_schedule_date(value):
            continue
        # Multi-value leftovers are present-but-unparseable, not a date.
        if isinstance(value, (list, tuple, dict, set)):
            continue
        try:
            parsed_dates.append(parse_schedule_datetime(value))
        except (ValueError, TypeError):
            continue
    if not parsed_dates:
        return None
    return max(parsed_dates)


def _normalize_schedule_status(raw_status: Any, *, newsletter: bool, missing: bool) -> str:
    """Normalize YAML status; unknown/empty/bool values fail closed as draft."""
    if missing:
        return 'draft' if newsletter else 'published'
    raw_status = _unwrap_schedule_value(raw_status)
    if isinstance(raw_status, (list, tuple)):
        if not raw_status:
            return 'draft'
        norms = []
        for item in raw_status:
            item = _unwrap_schedule_value(item)
            if isinstance(item, (list, tuple, dict, set)):
                return 'draft'
            norms.append(_normalize_schedule_status(item, newsletter=newsletter, missing=False))
        # Mixed lists that include sent are not a send receipt.
        unique = set(norms)
        if 'sent' in unique and len(unique) != 1:
            return 'draft'
        if unique == {'sent'}:
            return 'sent'
        if len(unique) != 1:
            return 'draft'
        return norms[0]
    if raw_status is False:
        return 'draft'
    if raw_status is True or isinstance(raw_status, (int, float)):
        return 'draft'
    if raw_status is None or (isinstance(raw_status, str) and not raw_status.strip()):
        return 'draft'
    return str(raw_status).strip().lower()


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
            try:
                content = file_path.read_text()
            except (OSError, UnicodeDecodeError):
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': file_path.stem,
                    '_yaml_error': True,
                    'error': 'unreadable file',
                })
                continue
            
            # Parse frontmatter. Missing or truncated YAML must not go live.
            content = strip_frontmatter_prefix(content)
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
            # Missing key defaults to published, except newsletters (draft until sent).
            # Explicit null/empty fails closed. CMS exports often use `Status`.
            is_newsletter = file_path.parent.name == 'newsletters'
            implicit_status = not frontmatter_values(frontmatter, 'status')
            status = resolve_schedule_status(frontmatter, newsletter=is_newsletter)
            
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

            # Spoofed `status: sent` without a send receipt must not go live.
            if is_newsletter and status == 'sent' and not newsletter_send_receipt(frontmatter):
                draft.append({
                    'path': file_path,
                    'status': 'draft',
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem),
                    'error': 'status=sent requires sent_at, sent_date, or campaign_id',
                })
                continue
            
            # Check publish_date. scheduled_for is a newsletter/ESP alias only.
            # Authored `date` is the common static-site fallback used by templates.
            # Unparseable publish_date must not hide a later valid field.
            # CMS/ESP dumps may capitalize Publish_date / Scheduled_for / Date.
            raw_publish_values = frontmatter_values(frontmatter, 'publish_date')
            raw_alias_values = (
                frontmatter_values(frontmatter, 'scheduled_for') if is_newsletter else []
            )
            raw_date_values = frontmatter_values(frontmatter, 'date')
            # Scheduled items must not fall through to authored `date` when
            # publish_date is present but unparseable (typo would go live).
            if status == 'scheduled':
                publish_date = _parse_first_schedule_date(
                    *raw_publish_values, *raw_alias_values
                )
                # Garbage scheduled_for must not be ignored when publish_date parses.
                if has_unparseable_schedule_date(*raw_publish_values, *raw_alias_values):
                    draft.append({
                        'path': file_path,
                        'status': 'draft',
                        'publish_date': None,
                        'title': frontmatter.get('title', file_path.stem),
                        '_date_error': True,
                        'error': 'invalid publish_date',
                    })
                    continue
            else:
                publish_date = _parse_first_schedule_date(
                    *raw_publish_values, *raw_alias_values, *raw_date_values
                )
            date_present = any(
                not _absent_schedule_date(value)
                for value in (
                    raw_publish_values
                    + raw_alias_values
                    + (raw_date_values if status != 'scheduled' else [])
                )
            )

            if publish_date is None:
                # Already-sent newsletters stay live even when the date is garbage.
                if status == 'sent':
                    publishable.append({
                        'path': file_path,
                        'status': 'sent',
                        'publish_date': None,
                        'title': frontmatter.get('title', file_path.stem)
                    })
                    continue
                # Scheduled without a usable date fails closed. Garbage dates on
                # already-published content are ignored so leftover ESP metadata
                # cannot hide a live page. Missing status + unparseable date is
                # not "already published" — fail closed like scheduled.
                if status == 'scheduled' or (implicit_status and date_present):
                    draft.append({
                        'path': file_path,
                        'status': 'draft',
                        'publish_date': None,
                        'title': frontmatter.get('title', file_path.stem),
                        # Missing and unparseable dates both fail CI (`gang schedule`).
                        '_date_error': True,
                        'error': (
                            'invalid publish_date'
                            if date_present
                            else 'status=scheduled requires publish_date'
                        ),
                    })
                    continue
                # Newsletters stay off the static site until send writes a receipt.
                if is_newsletter:
                    draft.append({
                        'path': file_path,
                        'status': 'draft',
                        'publish_date': None,
                        'title': frontmatter.get('title', file_path.stem),
                    })
                    continue
                publishable.append({
                    'path': file_path,
                    'status': status,
                    'publish_date': None,
                    'title': frontmatter.get('title', file_path.stem)
                })
                continue

            # Newsletters stay off the static site until they are sent.
            # An overdue `scheduled` issue must not leak before send flips status.
            # `published`/`live`/`public` are ready-to-send, not a send receipt.
            if is_newsletter and status != 'sent':
                if status == 'scheduled':
                    scheduled_future.append({
                        'path': file_path,
                        'status': 'scheduled',
                        'publish_date': publish_date,
                        'title': frontmatter.get('title', file_path.stem)
                    })
                else:
                    draft.append({
                        'path': file_path,
                        'status': 'draft',
                        'publish_date': publish_date,
                        'title': frontmatter.get('title', file_path.stem),
                    })
                continue

            # Explicit live statuses stay live even if leftover ESP dates are
            # still future. Missing status is not an explicit publish — a
            # future date must embargo the page like `scheduled`.
            already_live = status in ('sent', 'published', 'live', 'public') and not implicit_status
            if already_live or publish_date <= now:
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
                
                if delta.total_seconds() <= 0:
                    time_str = "overdue"
                elif delta.days > 0:
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
                error = item.get('error')
                if error:
                    lines.append(f"    error: {error}")
        
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

        allowed = ('draft', 'scheduled', 'published', 'live', 'public', 'sent')
        if status not in allowed:
            return False
        if status == 'scheduled' and not publish_date:
            return False

        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return False
        
        is_newsletter = file_path.parent.name == 'newsletters'
        content = strip_frontmatter_prefix(content)

        # Parse frontmatter
        if not content.startswith('---'):
            if status == 'sent':
                return False
            # No frontmatter, create one
            frontmatter = {
                'status': status
            }
            if publish_date:
                iso = publish_date.isoformat()
                frontmatter['publish_date'] = iso
                if is_newsletter:
                    frontmatter['scheduled_for'] = iso
            if is_newsletter and status != 'sent':
                drop_newsletter_receipts(frontmatter)
            
            new_content = (
                f"---\n{yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)}---\n{content}"
            )
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

        existing = resolve_schedule_status(frontmatter, newsletter=is_newsletter)
        has_receipt = newsletter_send_receipt(frontmatter)
        # Sent archives with a real receipt cannot be rescheduled. Spoofed
        # `status: sent` without a valid receipt may be moved back to draft.
        if existing == 'sent' and status != 'sent':
            if not (is_newsletter and not has_receipt):
                return False
        # Do not mark content sent without going through the send provider.
        if status == 'sent' and not (existing == 'sent' and has_receipt):
            return False
        
        # Update frontmatter. Drop authored `date` so a leftover future Date:
        # cannot republish after --now or conflict with publish_date.
        drop_frontmatter_aliases(frontmatter, 'status', 'publish_date', 'scheduled_for', 'date')
        # Canonical `date` is not an alias — drop it so leftover authored dates
        # cannot become a second send/publish clock after scheduling.
        frontmatter.pop('date', None)
        if is_newsletter and status != 'sent':
            drop_newsletter_receipts(frontmatter)
        if publish_date:
            iso = publish_date.isoformat()
            frontmatter['publish_date'] = iso
            if is_newsletter or 'scheduled_for' in frontmatter:
                frontmatter['scheduled_for'] = iso
            frontmatter['status'] = status
        else:
            # Remove both date keys so --now cannot leave a future scheduled_for.
            frontmatter.pop('publish_date', None)
            frontmatter.pop('scheduled_for', None)
            frontmatter.pop('date', None)
            frontmatter['status'] = status
        
        # Write back
        body = parts[2]
        new_content = (
            f"---\n{yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)}---\n{body}"
        )
        file_path.write_text(new_content)
        
        return True


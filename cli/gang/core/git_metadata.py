"""
GANG Git Metadata
Extract contributor and update information from git history.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime
import subprocess
import re


def get_git_root(file_path: Path) -> Optional[Path]:
    """Find the git repository root"""
    current = file_path.resolve()
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return None


def get_file_contributors(file_path: Path, limit: int = 10) -> List[str]:
    """
    Get unique contributors (authors) for a file from git history.
    Returns a list of contributor names.
    """
    repo_root = get_git_root(file_path)
    if not repo_root:
        return []
    
    try:
        # Get relative path from repo root
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        return []
    
    try:
        # Use git log to get all authors who modified the file
        result = subprocess.run(
            ['git', 'log', '--follow', '--pretty=format:%an', '--', str(rel_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return []
        
        # Get unique contributors (preserve order, first seen first)
        contributors = []
        seen = set()
        for name in result.stdout.strip().split('\n'):
            if name and name not in seen:
                seen.add(name)
                contributors.append(name)
                if len(contributors) >= limit:
                    break
        
        return contributors
    
    except (subprocess.TimeoutExpired, Exception):
        return []


def get_file_last_updated(file_path: Path) -> Optional[Dict[str, str]]:
    """
    Get the last update date and time for a file from git.
    Returns dict with 'date', 'date_iso', 'date_formatted', and 'author'.
    """
    repo_root = get_git_root(file_path)
    if not repo_root:
        return None
    
    try:
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        return None
    
    try:
        # Get the most recent commit for this file
        result = subprocess.run(
            ['git', 'log', '-1', '--follow', '--pretty=format:%at|%an', '--', str(rel_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0 or not result.stdout.strip():
            return None
        
        parts = result.stdout.strip().split('|')
        if len(parts) < 2:
            return None
        
        timestamp = int(parts[0])
        author = parts[1]
        
        # Convert timestamp to datetime
        dt = datetime.fromtimestamp(timestamp)
        
        return {
            'date': dt.isoformat(),
            'date_iso': dt.isoformat(),
            'date_formatted': dt.strftime('%B %d, %Y at %I:%M %p'),
            'author': author
        }
    
    except (subprocess.TimeoutExpired, Exception):
        return None


def get_cms_contributors(file_path: Path) -> List[str]:
    """
    Get contributors from CMS studio metadata if available.
    This would check for a metadata file or frontmatter field.
    For now, returns empty list - can be extended later.
    """
    # TODO: Check for CMS metadata file or frontmatter contributors field
    # For now, return empty list
    return []


def get_page_metadata(file_path: Path) -> Dict:
    """
    Get complete metadata for a page including contributors and last updated.
    Combines git history and CMS data.
    """
    # Get git contributors
    git_contributors = get_file_contributors(file_path)
    
    # Get CMS contributors (if any)
    cms_contributors = get_cms_contributors(file_path)
    
    # Combine and deduplicate contributors
    all_contributors = []
    seen = set()
    for contributor in git_contributors + cms_contributors:
        if contributor and contributor.lower() not in seen:
            seen.add(contributor.lower())
            all_contributors.append(contributor)
    
    # Get last updated date
    last_updated = get_file_last_updated(file_path)
    
    return {
        'contributors': all_contributors,
        'last_updated': last_updated
    }



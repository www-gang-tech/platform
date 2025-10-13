"""
GANG Content Versioning
Git-based content history and version management.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import subprocess
import json


class ContentVersioning:
    """Manage content versions using git"""
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
        self.repo_root = self._find_git_root()
    
    def _find_git_root(self) -> Optional[Path]:
        """Find the git repository root"""
        current = self.content_path.resolve()
        while current != current.parent:
            if (current / '.git').exists():
                return current
            current = current.parent
        return None
    
    def _run_git(self, args: List[str]) -> str:
        """Run a git command and return output"""
        if not self.repo_root:
            raise Exception("Not in a git repository")
        
        result = subprocess.run(
            ['git'] + args,
            cwd=self.repo_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"Git command failed: {result.stderr}")
        
        return result.stdout.strip()
    
    def get_file_history(self, file_path: Path, limit: int = 50) -> List[Dict[str, Any]]:
        """Get commit history for a specific file"""
        if not file_path.exists():
            return []
        
        try:
            rel_path = file_path.relative_to(self.repo_root)
        except:
            return []
        
        try:
            # Get log with follow (tracks renames)
            log_output = self._run_git([
                'log',
                '--follow',
                f'--max-count={limit}',
                '--pretty=format:%H|%an|%ae|%at|%s',
                '--',
                str(rel_path)
            ])
            
            if not log_output:
                return []
            
            history = []
            for line in log_output.split('\n'):
                if not line:
                    continue
                
                parts = line.split('|', 4)
                if len(parts) < 5:
                    continue
                
                commit_hash, author_name, author_email, timestamp, message = parts
                
                history.append({
                    'commit': commit_hash,
                    'short_commit': commit_hash[:7],
                    'author': {
                        'name': author_name,
                        'email': author_email
                    },
                    'date': datetime.fromtimestamp(int(timestamp)).isoformat(),
                    'timestamp': int(timestamp),
                    'message': message
                })
            
            return history
        
        except Exception as e:
            return []
    
    def get_file_content_at_commit(self, file_path: Path, commit: str) -> Optional[str]:
        """Get file content at a specific commit"""
        try:
            rel_path = file_path.relative_to(self.repo_root)
        except:
            return None
        
        try:
            content = self._run_git([
                'show',
                f'{commit}:{rel_path}'
            ])
            return content
        except:
            return None
    
    def get_file_diff(self, file_path: Path, commit1: str, commit2: str = 'HEAD') -> Optional[str]:
        """Get diff between two commits"""
        try:
            rel_path = file_path.relative_to(self.repo_root)
        except:
            return None
        
        try:
            diff = self._run_git([
                'diff',
                commit1,
                commit2,
                '--',
                str(rel_path)
            ])
            return diff
        except:
            return None
    
    def restore_file_version(self, file_path: Path, commit: str) -> bool:
        """Restore file to a specific commit version"""
        try:
            rel_path = file_path.relative_to(self.repo_root)
        except:
            return False
        
        try:
            # Get content at commit
            content = self.get_file_content_at_commit(file_path, commit)
            if content is None:
                return False
            
            # Write content
            file_path.write_text(content)
            return True
        except:
            return False
    
    def get_recent_changes(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get all content changes in the last N days"""
        try:
            # Get commits in the last N days
            since = f'{days}.days.ago'
            log_output = self._run_git([
                'log',
                f'--since={since}',
                '--pretty=format:%H|%an|%at|%s',
                '--name-status',
                '--',
                str(self.content_path.relative_to(self.repo_root))
            ])
            
            if not log_output:
                return []
            
            commits = []
            current_commit = None
            
            for line in log_output.split('\n'):
                if not line:
                    continue
                
                if '|' in line:
                    # Commit line
                    parts = line.split('|', 3)
                    if len(parts) < 4:
                        continue
                    
                    commit_hash, author, timestamp, message = parts
                    current_commit = {
                        'commit': commit_hash,
                        'short_commit': commit_hash[:7],
                        'author': author,
                        'date': datetime.fromtimestamp(int(timestamp)).isoformat(),
                        'message': message,
                        'files': []
                    }
                    commits.append(current_commit)
                else:
                    # File change line
                    if current_commit and line.strip():
                        parts = line.split('\t', 1)
                        if len(parts) == 2:
                            status, file_path = parts
                            current_commit['files'].append({
                                'status': status,
                                'path': file_path
                            })
            
            return commits
        
        except Exception as e:
            return []
    
    def format_history_report(self, history: List[Dict[str, Any]], file_path: Path) -> str:
        """Format file history as a human-readable report"""
        lines = []
        lines.append(f"📜 Version History: {file_path.name}")
        lines.append("=" * 60)
        
        if not history:
            lines.append("No version history found")
            return '\n'.join(lines)
        
        lines.append(f"Total commits: {len(history)}")
        lines.append("")
        
        for i, commit in enumerate(history):
            # Format date
            date = datetime.fromisoformat(commit['date'])
            date_str = date.strftime('%Y-%m-%d %H:%M')
            
            lines.append(f"[{i+1}] {commit['short_commit']} - {date_str}")
            lines.append(f"    Author: {commit['author']['name']}")
            lines.append(f"    {commit['message']}")
            lines.append("")
        
        return '\n'.join(lines)


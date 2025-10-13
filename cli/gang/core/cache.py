"""
Build Cache - Speed up repeated builds by caching unchanged files
"""

from pathlib import Path
import hashlib
import json
from typing import Dict, Optional


class BuildCache:
    """Simple file-based build cache using content hashing"""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_file = self.cache_dir / '.build_cache.json'
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict[str, str]:
        """Load cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_cache(self):
        """Save cache to disk"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)
    
    def get_file_hash(self, file_path: Path) -> str:
        """Get MD5 hash of file content"""
        try:
            content = file_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except:
            return ""
    
    def is_cached(self, file_path: Path) -> bool:
        """Check if file content hasn't changed since last build"""
        file_str = str(file_path)
        current_hash = self.get_file_hash(file_path)
        
        if file_str in self.cache and self.cache[file_str] == current_hash:
            return True
        
        # Update cache with current hash
        self.cache[file_str] = current_hash
        return False
    
    def invalidate(self, file_path: Path):
        """Remove file from cache"""
        file_str = str(file_path)
        if file_str in self.cache:
            del self.cache[file_str]
    
    def clear(self):
        """Clear entire cache"""
        self.cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()


"""
GANG R2 Storage Client
Upload and manage media in Cloudflare R2.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import hashlib


class R2Storage:
    """Cloudflare R2 storage client (S3-compatible)"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bucket_name = config.get('hosting', {}).get('r2_bucket', 'gang-media')
        self.account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
        self.access_key = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID')
        self.secret_key = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
        self.custom_domain = config.get('hosting', {}).get('r2_custom_domain')
        
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize boto3 S3 client for R2"""
        if not all([self.account_id, self.access_key, self.secret_key]):
            return None
        
        try:
            import boto3
            
            self.client = boto3.client(
                's3',
                endpoint_url=f'https://{self.account_id}.r2.cloudflarestorage.com',
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name='auto'  # R2 uses 'auto' region
            )
            
            return self.client
        except ImportError:
            return None
        except Exception as e:
            print(f"Warning: Could not initialize R2 client: {e}")
            return None
    
    def is_configured(self) -> bool:
        """Check if R2 is properly configured"""
        return self.client is not None
    
    def get_missing_config(self) -> List[str]:
        """Get list of missing configuration items"""
        missing = []
        if not self.account_id:
            missing.append('CLOUDFLARE_ACCOUNT_ID')
        if not self.access_key:
            missing.append('CLOUDFLARE_R2_ACCESS_KEY_ID')
        if not self.secret_key:
            missing.append('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
        return missing
    
    def upload_file(self, local_path: Path, remote_path: str, content_type: Optional[str] = None) -> Dict[str, Any]:
        """Upload a file to R2"""
        if not self.client:
            return {'error': 'R2 not configured'}
        
        try:
            # Detect content type if not provided
            if not content_type:
                content_type = self._guess_content_type(local_path)
            
            # Calculate file hash for integrity
            file_hash = self._calculate_hash(local_path)
            
            # Upload with metadata
            extra_args = {
                'ContentType': content_type,
                'Metadata': {
                    'original-filename': local_path.name,
                    'sha256': file_hash
                }
            }
            
            self.client.upload_file(
                str(local_path),
                self.bucket_name,
                remote_path,
                ExtraArgs=extra_args
            )
            
            # Generate public URL
            if self.custom_domain:
                public_url = f"https://{self.custom_domain}/{remote_path}"
            else:
                # Use R2.dev subdomain (needs to be enabled in Cloudflare)
                public_url = f"https://pub-{self.account_id[:8]}.r2.dev/{remote_path}"
            
            return {
                'success': True,
                'bucket': self.bucket_name,
                'remote_path': remote_path,
                'public_url': public_url,
                'size': local_path.stat().st_size,
                'hash': file_hash
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def upload_directory(self, local_dir: Path, remote_prefix: str = '', recursive: bool = True) -> Dict[str, Any]:
        """Upload entire directory to R2"""
        if not self.client:
            return {'error': 'R2 not configured'}
        
        results = {
            'uploaded': [],
            'failed': [],
            'total_size': 0
        }
        
        # Find all files
        if recursive:
            files = list(local_dir.rglob('*'))
        else:
            files = list(local_dir.glob('*'))
        
        files = [f for f in files if f.is_file()]
        
        for file_path in files:
            rel_path = file_path.relative_to(local_dir)
            remote_path = f"{remote_prefix}/{rel_path}".lstrip('/')
            
            result = self.upload_file(file_path, remote_path)
            
            if 'error' in result:
                results['failed'].append({
                    'file': str(rel_path),
                    'error': result['error']
                })
            else:
                results['uploaded'].append({
                    'file': str(rel_path),
                    'url': result['public_url'],
                    'size': result['size']
                })
                results['total_size'] += result['size']
        
        return results
    
    def list_files(self, prefix: str = '', max_keys: int = 1000) -> List[Dict[str, Any]]:
        """List files in R2 bucket"""
        if not self.client:
            return []
        
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            
            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'url': self._get_public_url(obj['Key'])
                })
            
            return files
        
        except Exception as e:
            print(f"Error listing files: {e}")
            return []
    
    def delete_file(self, remote_path: str) -> Dict[str, Any]:
        """Delete a file from R2"""
        if not self.client:
            return {'error': 'R2 not configured'}
        
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            return {'success': True, 'deleted': remote_path}
        except Exception as e:
            return {'error': str(e)}
    
    def download_file(self, remote_path: str, local_path: Path) -> Dict[str, Any]:
        """Download a file from R2"""
        if not self.client:
            return {'error': 'R2 not configured'}
        
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            self.client.download_file(
                self.bucket_name,
                remote_path,
                str(local_path)
            )
            
            return {
                'success': True,
                'local_path': str(local_path),
                'size': local_path.stat().st_size
            }
        except Exception as e:
            return {'error': str(e)}
    
    def sync_directory(self, local_dir: Path, remote_prefix: str = '', delete: bool = False) -> Dict[str, Any]:
        """Sync local directory to R2 (like aws s3 sync)"""
        if not self.client:
            return {'error': 'R2 not configured'}
        
        results = {
            'uploaded': 0,
            'skipped': 0,
            'deleted': 0,
            'errors': []
        }
        
        # Get list of remote files
        remote_files = {f['key']: f for f in self.list_files(remote_prefix)}
        
        # Upload local files
        local_files = {}
        for file_path in local_dir.rglob('*'):
            if file_path.is_file():
                rel_path = file_path.relative_to(local_dir)
                remote_path = f"{remote_prefix}/{rel_path}".lstrip('/')
                local_files[remote_path] = file_path
                
                # Check if file exists and has same hash
                if remote_path in remote_files:
                    # For now, re-upload (future: check hash)
                    pass
                
                result = self.upload_file(file_path, remote_path)
                if 'error' in result:
                    results['errors'].append(result['error'])
                else:
                    results['uploaded'] += 1
        
        # Delete remote files not in local (if requested)
        if delete:
            for remote_path in remote_files:
                if remote_path not in local_files:
                    self.delete_file(remote_path)
                    results['deleted'] += 1
        
        return results
    
    def _get_public_url(self, key: str) -> str:
        """Get public URL for an R2 object"""
        if self.custom_domain:
            return f"https://{self.custom_domain}/{key}"
        else:
            # Use R2.dev subdomain (needs to be enabled)
            return f"https://pub-{self.account_id[:8]}.r2.dev/{key}"
    
    def _guess_content_type(self, file_path: Path) -> str:
        """Guess MIME type from file extension"""
        extension_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.avif': 'image/avif',
            '.svg': 'image/svg+xml',
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.pdf': 'application/pdf',
        }
        
        ext = file_path.suffix.lower()
        return extension_map.get(ext, 'application/octet-stream')
    
    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()


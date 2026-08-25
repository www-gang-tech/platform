#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GANG Studio Backend API
Provides endpoints for in-place content editing
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path
from urllib.parse import urlparse
import subprocess
import yaml
import re
import os

app = Flask(__name__)
CORS(app, origins=[
    'http://127.0.0.1:3000',
    'http://localhost:3000',
    'http://127.0.0.1:5001',
    'http://localhost:5001',
])

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONTENT_DIR = PROJECT_ROOT / 'content'
PUBLISHABLE_CATEGORIES = {
    'posts', 'articles', 'pages', 'projects', 'newsletters', 'people', 'products'
}
SAFE_SLUG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
MAX_CONTENT_BYTES = 2 * 1024 * 1024


def _parse_frontmatter(text: str):
    if not text.startswith('---'):
        return {}, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return {}, text
    try:
        raw = yaml.safe_load(parts[1])
    except Exception:
        raw = None
    return (raw if isinstance(raw, dict) else {}), parts[2]


def _merge_editor_frontmatter(original: str, incoming: str) -> str:
    orig_fm, _ = _parse_frontmatter(original)
    in_fm, in_body = _parse_frontmatter(incoming)
    if orig_fm and not in_fm:
        dumped = yaml.dump(orig_fm, default_flow_style=False, allow_unicode=True).strip()
        body = in_body if incoming.lstrip().startswith('---') else incoming
        return f"---\n{dumped}\n---\n{body}"
    return incoming


def _safe_content_file(file_path: str) -> Path:
    if not file_path or file_path.startswith('/') or '\0' in file_path:
        raise ValueError('Invalid file path')
    relative = file_path if file_path.endswith('.md') else file_path + '.md'
    parts = Path(relative).parts
    if len(parts) != 2 or parts[0] not in PUBLISHABLE_CATEGORIES:
        raise ValueError('Invalid file path')
    filename = parts[1]
    if not filename.endswith('.md') or not SAFE_SLUG_RE.match(filename[:-3]) or '..' in filename:
        raise ValueError('Invalid file path')
    base = CONTENT_DIR.resolve()
    candidate = (base / relative).resolve()
    candidate.relative_to(base)
    return candidate


def _is_direct_loopback():
    """True only for a direct TCP peer on loopback, not a reverse-proxied client."""
    addr = request.remote_addr or ''
    if addr not in ('127.0.0.1', '::1'):
        return False
    if request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP'):
        return False
    return True


def _is_loopback_origin():
    """Reject cross-origin CSRF against tokenless loopback Studio."""
    origin = (request.headers.get('Origin') or request.headers.get('Referer') or '').strip()
    if not origin:
        return request.method in ('GET', 'HEAD', 'OPTIONS')
    parsed = urlparse(origin)
    host = (parsed.hostname or '').lower()
    return host in {'127.0.0.1', 'localhost', '::1'}


def _require_auth():
    token = os.environ.get('STUDIO_AUTH_TOKEN', '').strip()
    if not token:
        if _is_direct_loopback() and _is_loopback_origin():
            return None
        return jsonify({'error': 'Unauthorized'}), 401
    header = request.headers.get('Authorization', '')
    if header != f'Bearer {token}':
        return jsonify({'error': 'Unauthorized'}), 401
    return None


@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'gang-studio'})


@app.route('/api/auth/status')
def auth_status():
    """Report whether the current request satisfies Studio auth."""
    auth_error = _require_auth()
    authenticated = auth_error is None
    return jsonify({
        'authenticated': authenticated,
        'user': {'email': 'local@dev'} if authenticated else None
    })


@app.route('/api/content/<path:file_path>')
def get_content(file_path):
    """Get markdown content for editing"""
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    try:
        full_path = _safe_content_file(file_path)
    except ValueError:
        return jsonify({'error': 'Invalid file path'}), 400
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        content = full_path.read_text(encoding='utf-8')
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/content/<path:file_path>', methods=['PUT'])
def save_content(file_path):
    """Save edited markdown content"""
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    try:
        full_path = _safe_content_file(file_path)
    except ValueError:
        return jsonify({'error': 'Invalid file path'}), 400
    
    if request.content_length and request.content_length > MAX_CONTENT_BYTES:
        return jsonify({'error': 'Request body too large'}), 413

    # Get content from request body
    content = request.get_data(as_text=True)
    
    if not content:
        return jsonify({'error': 'No content provided'}), 400
    if len(content.encode('utf-8')) > MAX_CONTENT_BYTES:
        return jsonify({'error': 'Request body too large'}), 413
    if full_path.exists():
        content = _merge_editor_frontmatter(full_path.read_text(encoding='utf-8'), content)
    
    # Ensure parent directory exists (still inside content root)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Save the file
        full_path.write_text(content, encoding='utf-8')
        
        return jsonify({
            'status': 'saved',
            'file': str(file_path),
            'message': 'Content saved successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/validate-headings', methods=['POST'])
def validate_headings():
    """Validate heading structure for WCAG compliance"""
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    data = request.get_json()
    
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400
    
    content = data['content']
    category = str(data.get('category') or data.get('page_type') or '')
    template_owns_h1 = category in {
        'posts', 'articles', 'projects', 'newsletters', 'people', 'products'
    }
    
    # Extract headings from markdown
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    headings = heading_pattern.findall(content)
    
    if not headings:
        return jsonify({
            'valid': True,
            'message': 'No headings found (optional for some content types)'
        })
    
    errors = []
    suggestions = []
    
    # Convert to heading levels
    heading_levels = [len(h[0]) for h in headings]
    
    # Rule 1: First heading should be H1 unless the template owns the page H1
    if heading_levels[0] != 1 and not template_owns_h1:
        errors.append('First heading is H' + str(heading_levels[0]) + ', should be H1')
        suggestions.append('Start with a single # for the main title')
    
    # Rule 2: Only one H1
    h1_count = heading_levels.count(1)
    if h1_count > 1:
        errors.append('Multiple H1 headings found (' + str(h1_count) + '), should have exactly one')
        suggestions.append('Use only one # (H1) for the page title')
    
    # Rule 3: No skipped levels
    for i in range(1, len(heading_levels)):
        prev_level = heading_levels[i-1]
        curr_level = heading_levels[i]
        
        if curr_level > prev_level + 1:
            errors.append('Heading level skipped: H' + str(prev_level) + ' to H' + str(curr_level))
            suggestions.append('Increment heading levels by one (use H' + str(prev_level + 1) + ' instead of H' + str(curr_level) + ')')
    
    return jsonify({
        'valid': len(errors) == 0,
        'errors': errors,
        'suggestions': suggestions if errors else [],
        'headings': [{'level': len(h[0]), 'text': h[1]} for h in headings]
    })


@app.route('/api/build', methods=['POST'])
def trigger_build():
    """Trigger git commit and build deployment"""
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    try:
        # Change to project root
        os.chdir(PROJECT_ROOT)
        
        # Check if there are changes to commit
        status = subprocess.run(
            ['git', 'status', '--porcelain', 'content/'],
            capture_output=True,
            text=True,
            check=True
        )
        
        if not status.stdout.strip():
            return jsonify({
                'status': 'no_changes',
                'message': 'No changes to commit'
            })
        
        # Add content changes
        subprocess.run(
            ['git', 'add', 'content/'],
            check=True
        )
        
        # Commit changes
        try:
            json_data = request.get_json()
            commit_message = json_data.get('message', 'Content update via in-place editor') if json_data else 'Content update via in-place editor'
            if not isinstance(commit_message, str):
                commit_message = str(commit_message)
            commit_message = ' '.join(commit_message.split())[:200] or 'Content update via in-place editor'
        except Exception:
            commit_message = 'Content update via in-place editor'
        subprocess.run(
            ['git', 'commit', '-m', commit_message],
            check=True
        )
        
        # Rebuild the site (never bake the in-place editor into published HTML)
        print("🔄 Rebuilding site...")
        env = os.environ.copy()
        env.pop('EDITOR_MODE', None)
        build_result = subprocess.run(
            ['gang', 'build'],
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
        print("✅ Site rebuilt successfully")
        
        # Optional: Auto-push (can be disabled for safety)
        auto_push = os.environ.get('AUTO_PUSH', 'false').lower() == 'true'
        
        if auto_push:
            subprocess.run(
                ['git', 'push', 'origin', 'main'],
                check=True
            )
            return jsonify({
                'status': 'building',
                'deploying': True,
                'message': 'Changes committed and pushed. GitHub Actions will deploy.'
            })
        else:
            return jsonify({
                'status': 'committed',
                'deploying': False,
                'message': 'Changes committed. Run "git push" to deploy.'
            })
        
    except subprocess.CalledProcessError as e:
        return jsonify({
            'status': 'error',
            'message': 'Git operation failed: ' + str(e)
        }), 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/content/list')
def list_content():
    """List all editable content files"""
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    content_files = []
    
    for content_type in ['pages', 'posts', 'articles', 'projects', 'newsletters', 'products', 'people']:
        type_dir = CONTENT_DIR / content_type
        if type_dir.exists():
            for md_file in type_dir.glob('*.md'):
                if not SAFE_SLUG_RE.match(md_file.stem) or '..' in md_file.stem:
                    continue
                # Parse frontmatter to get title
                try:
                    content = md_file.read_text(encoding='utf-8')
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
                        if not isinstance(frontmatter, dict):
                            frontmatter = {}
                        title = frontmatter.get('title', md_file.stem.replace('-', ' ').title())
                    else:
                        title = md_file.stem.replace('-', ' ').title()
                    
                    public_type = 'posts' if content_type == 'articles' else content_type
                    content_files.append({
                        'type': content_type,
                        'slug': md_file.stem,
                        'title': title,
                        'path': content_type + "/" + md_file.stem,
                        'url': "/" + public_type + "/" + md_file.stem + "/"
                    })
                except Exception as e:
                    print("Error reading " + str(md_file) + ": " + str(e))
    
    return jsonify(content_files)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    host = os.environ.get('STUDIO_HOST', '127.0.0.1')
    
    print("🚀 GANG Studio Backend starting...")
    print("📁 Content directory: " + str(CONTENT_DIR))
    print("🔧 Project root: " + str(PROJECT_ROOT))
    print("")
    print("Available endpoints:")
    print("  GET  http://" + host + ":" + str(port) + "/api/health")
    print("  GET  http://" + host + ":" + str(port) + "/api/auth/status")
    print("  GET  http://" + host + ":" + str(port) + "/api/content/<path>")
    print("  PUT  http://" + host + ":" + str(port) + "/api/content/<path>")
    print("  POST http://" + host + ":" + str(port) + "/api/validate-headings")
    print("  POST http://" + host + ":" + str(port) + "/api/build")
    print("  GET  http://" + host + ":" + str(port) + "/api/content/list")
    print("")
    
    app.run(host=host, port=port, debug=False)


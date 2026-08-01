#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GANG Studio Backend API
Provides endpoints for in-place content editing
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path
import subprocess
import yaml
import re
import os
import secrets

app = Flask(__name__)
CORS(app, origins=[
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost:5001',
    'http://127.0.0.1:5001',
])

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONTENT_DIR = PROJECT_ROOT / 'content'


def resolve_content_file(file_path):
    """Resolve an extensionless editor path beneath the content root."""
    if file_path.startswith('/') or Path(file_path).suffix:
        raise ValueError('Invalid file path')

    content_root = CONTENT_DIR.resolve()
    full_path = (content_root / (file_path + '.md')).resolve()
    try:
        full_path.relative_to(content_root)
    except ValueError as exc:
        raise ValueError('Invalid file path') from exc
    return full_path


def _is_loopback_request():
    """Allow unauthenticated local Studio use only from loopback clients."""
    remote = (request.remote_addr or '').strip()
    return remote in {'127.0.0.1', '::1', 'localhost'}


def request_is_authenticated():
    """Authenticate editor requests when a Studio token is configured."""
    if os.environ.get('EDITOR_MODE', '').lower() == 'true' and _is_loopback_request():
        return True
    expected_token = os.environ.get('STUDIO_AUTH_TOKEN', '')
    if not expected_token:
        return False
    auth_header = request.headers.get('Authorization', '')
    scheme, _, provided_token = auth_header.partition(' ')
    return (
        scheme.lower() == 'bearer'
        and bool(provided_token)
        and secrets.compare_digest(provided_token, expected_token)
    )


@app.before_request
def protect_mutations():
    """Require auth for mutations unless this is a loopback local Studio session."""
    if request.method not in {'POST', 'PUT', 'DELETE'}:
        return None
    if request_is_authenticated():
        return None
    # Local Studio without a configured token remains usable on loopback only.
    if not os.environ.get('STUDIO_AUTH_TOKEN') and _is_loopback_request():
        return None
    return jsonify({'error': 'Unauthorized'}), 401


@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'gang-studio'})


@app.route('/api/auth/status')
def auth_status():
    """Report whether the request has valid local or bearer authentication."""
    authenticated = request_is_authenticated()
    
    return jsonify({
        'authenticated': authenticated,
        'user': {'email': 'local@dev'} if authenticated else None
    })


@app.route('/api/content/<path:file_path>')
def get_content(file_path):
    """Get markdown content for editing"""
    try:
        full_path = resolve_content_file(file_path)
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
    try:
        full_path = resolve_content_file(file_path)
    except ValueError:
        return jsonify({'error': 'Invalid file path'}), 400
    
    # Get content from request body
    content = request.get_data(as_text=True)
    
    if not content:
        return jsonify({'error': 'No content provided'}), 400
    
    # Ensure parent directory exists
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
    data = request.get_json()
    
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400
    
    content = data['content']
    
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
    
    # Rule 1: First heading should be H1
    if heading_levels[0] != 1:
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
    try:
        # Check if there are changes to commit
        status = subprocess.run(
            ['git', 'status', '--porcelain', 'content/'],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT
        )
        
        if not status.stdout.strip():
            return jsonify({
                'status': 'no_changes',
                'message': 'No changes to commit'
            })
        
        # Add content changes
        subprocess.run(
            ['git', 'add', 'content/'],
            check=True,
            cwd=PROJECT_ROOT
        )
        
        # Commit changes
        try:
            json_data = request.get_json()
            commit_message = json_data.get('message', 'Content update via in-place editor') if json_data else 'Content update via in-place editor'
        except:
            commit_message = 'Content update via in-place editor'
        subprocess.run(
            ['git', 'commit', '-m', commit_message],
            check=True,
            cwd=PROJECT_ROOT
        )
        
        # Rebuild the site
        print("🔄 Rebuilding site...")
        env = os.environ.copy()
        env['EDITOR_MODE'] = 'true'
        build_result = subprocess.run(
            ['gang', 'build'],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=PROJECT_ROOT
        )
        print("✅ Site rebuilt successfully")
        
        # Optional: Auto-push (can be disabled for safety)
        auto_push = os.environ.get('AUTO_PUSH', 'false').lower() == 'true'
        
        if auto_push:
            branch = subprocess.run(
                ['git', 'branch', '--show-current'],
                capture_output=True,
                text=True,
                check=True,
                cwd=PROJECT_ROOT
            ).stdout.strip()
            subprocess.run(
                ['git', 'push', 'origin', branch],
                check=True,
                cwd=PROJECT_ROOT
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


@app.route('/api/content')
@app.route('/api/content/list')
def list_content():
    """List all editable content files"""
    content_files = []
    
    for content_type in ['pages', 'posts', 'articles', 'projects', 'newsletters', 'products', 'people']:
        type_dir = CONTENT_DIR / content_type
        if type_dir.exists():
            for md_file in type_dir.glob('*.md'):
                # Parse frontmatter to get title
                try:
                    content = md_file.read_text(encoding='utf-8')
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
                        title = frontmatter.get('title', md_file.stem.replace('-', ' ').title())
                    else:
                        title = md_file.stem.replace('-', ' ').title()
                    
                    output_type = 'posts' if content_type == 'articles' else content_type
                    content_files.append({
                        'type': content_type,
                        'slug': md_file.stem,
                        'title': title,
                        'path': content_type + "/" + md_file.stem,
                        'url': "/" + output_type + "/" + md_file.stem + "/"
                    })
                except Exception as e:
                    print("Error reading " + str(md_file) + ": " + str(e))
    
    return jsonify(content_files)


def _resolve_slug_file(category, slug):
    """Resolve category/slug markdown under the content root."""
    if not category or not slug:
        raise ValueError('category and slug are required')
    if '/' in category or '\\' in category or '/' in slug or '\\' in slug:
        raise ValueError('Invalid category or slug')
    if Path(slug).suffix:
        raise ValueError('Slug must not include a file extension')
    content_root = CONTENT_DIR.resolve()
    full_path = (content_root / category / f'{slug}.md').resolve()
    try:
        full_path.relative_to(content_root)
    except ValueError as exc:
        raise ValueError('Invalid category or slug') from exc
    return full_path


@app.route('/api/rename-slug', methods=['POST'])
def rename_slug():
    """Rename a content slug and optionally create a 301 redirect."""
    data = request.get_json(silent=True) or {}
    old_slug = data.get('old_slug')
    new_slug = data.get('new_slug')
    category = data.get('category')
    create_redirect = data.get('create_redirect', True)

    try:
        old_file = _resolve_slug_file(category, old_slug)
        new_file = _resolve_slug_file(category, new_slug)
    except ValueError as exc:
        return jsonify({'error': 'Invalid rename request', 'message': str(exc)}), 400

    if not old_file.exists():
        return jsonify({'error': 'File not found', 'message': f'File {old_file} does not exist'}), 404
    if new_file.exists():
        return jsonify({'error': 'Slug already exists', 'message': f'A file with slug "{new_slug}" already exists'}), 400

    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / 'cli' / 'gang'))
        from core.redirects import RedirectManager

        old_file.rename(new_file)
        redirect_info = None
        if create_redirect:
            output_category = 'posts' if category == 'articles' else category
            old_url = f'/{output_category}/{old_slug}/'
            new_url = f'/{output_category}/{new_slug}/'
            manager = RedirectManager(CONTENT_DIR, PROJECT_ROOT / 'dist')
            redirect_info = manager.add_redirect(old_url, new_url, reason='slug_rename_cms').get('redirect')

        return jsonify({
            'success': True,
            'old_path': str(old_file.relative_to(CONTENT_DIR)),
            'new_path': str(new_file.relative_to(CONTENT_DIR)),
            'redirect': redirect_info,
        })
    except Exception as exc:
        return jsonify({'error': 'Internal server error', 'message': str(exc)}), 500


@app.route('/api/redirects')
def list_redirects():
    """List tracked redirects."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / 'cli' / 'gang'))
        from core.redirects import RedirectManager

        manager = RedirectManager(CONTENT_DIR, PROJECT_ROOT / 'dist')
        return jsonify(manager.list_all_redirects())
    except Exception as exc:
        return jsonify({'error': 'Internal server error', 'message': str(exc)}), 500


@app.route('/api/redirects/<path:from_path>', methods=['DELETE'])
def delete_redirect(from_path):
    """Remove a tracked redirect by source path."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / 'cli' / 'gang'))
        from core.redirects import RedirectManager

        manager = RedirectManager(CONTENT_DIR, PROJECT_ROOT / 'dist')
        redirect_from = '/' + from_path if not from_path.startswith('/') else from_path
        if manager.remove_redirect(redirect_from):
            return jsonify({'success': True, 'message': 'Redirect removed'})
        return jsonify({'error': 'Redirect not found'}), 404
    except Exception as exc:
        return jsonify({'error': 'Internal server error', 'message': str(exc)}), 500


@app.route('/api/products/sync', methods=['POST'])
def sync_products():
    """Sync normalized products from configured commerce sources."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / 'cli' / 'gang'))
        from core.products import ProductAggregator

        config_path = PROJECT_ROOT / 'gang.config.yml'
        with open(config_path) as f:
            config = yaml.safe_load(f)
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='all')
        return jsonify({
            'success': True,
            'total': len(products),
            'products': products,
        })
    except Exception as exc:
        return jsonify({'error': 'Internal server error', 'message': str(exc)}), 500


if __name__ == '__main__':
    # Use port 5001 to avoid conflict with macOS AirPlay Receiver
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 GANG Studio Backend starting...")
    print("📁 Content directory: " + str(CONTENT_DIR))
    print("🔧 Project root: " + str(PROJECT_ROOT))
    print("")
    print("Available endpoints:")
    print("  GET  http://localhost:" + str(port) + "/api/health")
    print("  GET  http://localhost:" + str(port) + "/api/auth/status")
    print("  GET  http://localhost:" + str(port) + "/api/content/<path>")
    print("  PUT  http://localhost:" + str(port) + "/api/content/<path>")
    print("  POST http://localhost:" + str(port) + "/api/validate-headings")
    print("  POST http://localhost:" + str(port) + "/api/build")
    print("  GET  http://localhost:" + str(port) + "/api/content/list")
    print("  POST http://localhost:" + str(port) + "/api/rename-slug")
    print("  GET  http://localhost:" + str(port) + "/api/redirects")
    print("  DELETE http://localhost:" + str(port) + "/api/redirects/<path>")
    print("  POST http://localhost:" + str(port) + "/api/products/sync")
    print("")
    print("📝 TIP: If using Python 3.9.6, make sure Flask is installed")
    print("🔧 To change port: PORT=8080 python app.py")
    print("")
    
    # Run on configurable port (default 5001 to avoid macOS AirPlay)
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', '').lower() == 'true'
    app.run(host=host, port=port, debug=debug)


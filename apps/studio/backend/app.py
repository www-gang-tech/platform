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

app = Flask(__name__)
CORS(app)  # Enable CORS for local development

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONTENT_DIR = PROJECT_ROOT / 'content'


@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'gang-studio'})


@app.route('/api/auth/status')
def auth_status():
    """Check authentication status (simplified for MVP)"""
    # For MVP, we'll just check if a simple auth token is present
    # In production, use Cloudflare Access or proper OAuth
    auth_header = request.headers.get('Authorization', '')
    
    # Simple check: if any auth header is present, consider authenticated
    # TODO: Implement proper authentication in production
    authenticated = bool(auth_header) or os.environ.get('EDITOR_MODE') == 'true'
    
    return jsonify({
        'authenticated': authenticated,
        'user': {'email': 'local@dev'} if authenticated else None
    })


@app.route('/api/content/<path:file_path>')
def get_content(file_path):
    """Get markdown content for editing"""
    # Ensure file_path is safe (no directory traversal)
    if '..' in file_path or file_path.startswith('/'):
        return jsonify({'error': 'Invalid file path'}), 400
    
    # Construct full path
    full_path = CONTENT_DIR / (file_path + '.md')
    
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
    # Ensure file_path is safe
    if '..' in file_path or file_path.startswith('/'):
        return jsonify({'error': 'Invalid file path'}), 400
    
    # Get content from request body
    content = request.get_data(as_text=True)
    
    if not content:
        return jsonify({'error': 'No content provided'}), 400
    
    # Construct full path
    full_path = CONTENT_DIR / (file_path + '.md')
    
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
        except:
            commit_message = 'Content update via in-place editor'
        subprocess.run(
            ['git', 'commit', '-m', commit_message],
            check=True
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
    content_files = []
    
    for content_type in ['pages', 'posts', 'projects', 'newsletters', 'products']:
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
                    
                    content_files.append({
                        'type': content_type,
                        'slug': md_file.stem,
                        'title': title,
                        'path': content_type + "/" + md_file.stem,
                        'url': "/" + content_type + "/" + md_file.stem + "/"
                    })
                except Exception as e:
                    print("Error reading " + str(md_file) + ": " + str(e))
    
    return jsonify(content_files)


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
    print("")
    print("📝 TIP: If using Python 3.9.6, make sure Flask is installed")
    print("🔧 To change port: PORT=8080 python app.py")
    print("")
    
    # Run on configurable port (default 5001 to avoid macOS AirPlay)
    app.run(host='0.0.0.0', port=port, debug=True)


#!/usr/bin/env python3
"""
GANG CLI - Single binary for all build operations
"""

import click
import yaml
import hashlib
import json
import shutil
import markdown
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

@click.group()
@click.pass_context
def cli(ctx):
    """GANG - AI-first static publishing platform"""
    config_path = Path('gang.config.yml')
    if not config_path.exists():
        click.echo("Error: gang.config.yml not found", err=True)
        ctx.abort()
    
    with open(config_path) as f:
        ctx.obj = yaml.safe_load(f)

@cli.command()
@click.option('--force', is_flag=True, help='Force re-optimization of all files')
@click.pass_context
def optimize(ctx, force):
    """Fill missing SEO/alt/JSON-LD fields using AI"""
    click.echo("🤖 AI Optimization coming soon!")
    click.echo("This will use Claude to fill missing metadata.")

@cli.command()
@click.pass_context
def build(ctx):
    """Build static site with semantic HTML"""
    click.echo("🔨 Building site...")
    config = ctx.obj
    
    # Create dist directory
    dist_path = Path(config['build']['output'])
    if dist_path.exists():
        shutil.rmtree(dist_path)
    dist_path.mkdir(parents=True, exist_ok=True)
    
    # Copy public assets
    public_path = Path(config['build']['public'])
    if public_path.exists():
        click.echo("📦 Copying public assets...")
        shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
    
    # Build content
    content_path = Path(config['build']['content'])
    pages = []
    posts = []
    projects = []
    
    # Parse markdown files
    click.echo("📝 Processing content...")
    for md_file in content_path.rglob('*.md'):
        content_type = md_file.parent.name
        html = process_markdown(md_file, content_type, config)
        
        # Determine output path
        rel_path = md_file.relative_to(content_path)
        output_file = dist_path / rel_path.parent.name / md_file.stem / 'index.html'
        
        if md_file.stem == 'index':
            output_file = dist_path / rel_path.parent.name / 'index.html'
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html)
        click.echo(f"  ✓ {rel_path}")
        
        # Collect for index
        if content_type == 'posts':
            posts.append((md_file.stem, html))
        elif content_type == 'projects':
            projects.append((md_file.stem, html))
        elif content_type == 'pages':
            pages.append((md_file.stem, html))
    
    # Create index page
    click.echo("🏠 Creating index page...")
    index_html = create_index(config, posts, projects)
    (dist_path / 'index.html').write_text(index_html)
    
    # Create list pages
    if posts:
        posts_html = create_list_page(config, posts, 'Posts')
        (dist_path / 'posts' / 'index.html').write_text(posts_html)
    
    if projects:
        projects_html = create_list_page(config, projects, 'Projects')
        (dist_path / 'projects' / 'index.html').write_text(projects_html)
    
    click.echo(f"✅ Build complete! Output in {dist_path}")


def process_markdown(md_file: Path, content_type: str, config: Dict) -> str:
    """Process a markdown file into HTML"""
    content = md_file.read_text()
    
    # Parse frontmatter
    if content.startswith('---'):
        parts = content.split('---', 2)
        frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
        body = parts[2] if len(parts) > 2 else ''
    else:
        frontmatter = {}
        body = content
    
    # Convert markdown to HTML
    md = markdown.Markdown(extensions=['extra', 'meta'])
    body_html = md.convert(body)
    
    title = frontmatter.get('title', md_file.stem.replace('-', ' ').title())
    description = frontmatter.get('summary', config['site']['description'])
    
    # Build HTML page
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {config['site']['title']}</title>
    <meta name="description" content="{description}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0066cc;
            text-decoration: none;
        }}
        nav a:hover {{
            text-decoration: underline;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 1rem;
        }}
        h2 {{
            font-size: 1.5rem;
            margin-top: 2rem;
            margin-bottom: 1rem;
        }}
        h3 {{
            font-size: 1.25rem;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}
        p, ul, ol {{
            margin-bottom: 1rem;
        }}
        ul, ol {{
            margin-left: 1.5rem;
        }}
        code {{
            background: #f5f5f5;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        pre {{
            background: #f5f5f5;
            padding: 1rem;
            border-radius: 5px;
            overflow-x: auto;
            margin-bottom: 1rem;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #666;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <header>
        <a href="/" style="text-decoration: none; color: inherit;">
            <strong>{config['site']['title']}</strong>
        </a>
        <nav>
            <a href="/">Home</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/pages/about/">About</a>
        </nav>
    </header>
    <main>
        <article>
            {body_html}
        </article>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""
    
    return html


def create_index(config: Dict, posts: List, projects: List) -> str:
    """Create the homepage"""
    posts_links = '\n'.join([f'<li><a href="/posts/{slug}/">{slug.replace("-", " ").title()}</a></li>' 
                              for slug, _ in posts[:5]])
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0066cc;
            text-decoration: none;
        }}
        nav a:hover {{
            text-decoration: underline;
        }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        h2 {{
            font-size: 1.5rem;
            margin-top: 2rem;
            margin-bottom: 1rem;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            margin-bottom: 0.5rem;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #666;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <header>
        <strong>{config['site']['title']}</strong>
        <nav>
            <a href="/">Home</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/pages/about/">About</a>
        </nav>
    </header>
    <main>
        <h1>Welcome to {config['site']['title']}</h1>
        <p>{config['site']['description']}</p>
        
        <h2>Latest Posts</h2>
        <ul>
            {posts_links}
        </ul>
        <p><a href="/posts/">View all posts →</a></p>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""
    
    return html


def create_list_page(config: Dict, items: List, title: str) -> str:
    """Create a list page for posts or projects"""
    items_links = '\n'.join([f'<li><a href="/{title.lower()}/{slug}/">{slug.replace("-", " ").title()}</a></li>' 
                              for slug, _ in items])
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0066cc;
            text-decoration: none;
        }}
        nav a:hover {{
            text-decoration: underline;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 1.5rem;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            margin-bottom: 0.75rem;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #666;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <header>
        <a href="/" style="text-decoration: none; color: inherit;">
            <strong>{config['site']['title']}</strong>
        </a>
        <nav>
            <a href="/">Home</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/pages/about/">About</a>
        </nav>
    </header>
    <main>
        <h1>{title}</h1>
        <ul>
            {items_links}
        </ul>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""
    
    return html

@cli.command()
@click.pass_context
def check(ctx):
    """Validate Template Contracts and WCAG compliance"""
    click.echo("✅ Checking contracts...")
    click.echo("✓ Validation system coming soon!")

@cli.command()
@click.pass_context
def audit(ctx):
    """Run Lighthouse + axe audits"""
    click.echo("📊 Running audits...")
    click.echo("✓ Audit system coming soon!")

@cli.command()
@click.option('--port', default=3000, help='Port for Studio')
def studio(port):
    """Start Studio CMS"""
    click.echo(f"🎨 Starting Studio on port {port}...")
    click.echo("✓ Studio coming soon!")

if __name__ == '__main__':
    cli()

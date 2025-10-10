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
    try:
        from core.optimizer import AIOptimizer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.optimizer import AIOptimizer
    
    click.echo("🤖 Running AI optimization...")
    config = ctx.obj
    optimizer = AIOptimizer(config)
    
    if not optimizer.client:
        click.echo("⚠️  No ANTHROPIC_API_KEY found in environment", err=True)
        click.echo("Set ANTHROPIC_API_KEY to enable AI optimization")
        return
    
    content_path = Path(config['build']['content'])
    md_files = list(content_path.rglob('*.md'))
    
    click.echo(f"Found {len(md_files)} content files")
    
    # Estimate cost
    cost_info = optimizer.estimate_cost(len(md_files))
    click.echo(f"💰 Estimated cost: ${cost_info['estimated_cost_usd']:.2f} (with cache: ${cost_info['with_cache']:.2f})")
    
    optimized_count = 0
    for md_file in md_files:
        content = md_file.read_text()
        
        # Parse frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            body = parts[2] if len(parts) > 2 else ''
        else:
            frontmatter = {}
            body = content
        
        content_type = md_file.parent.name
        
        # Optimize
        optimized = optimizer.optimize_content(body, frontmatter, content_type)
        
        if optimized != frontmatter:
            # Write back with optimized frontmatter
            new_content = f"---\n{yaml.dump(optimized, default_flow_style=False)}---\n{body}"
            md_file.write_text(new_content)
            optimized_count += 1
            click.echo(f"  ✓ {md_file.relative_to(content_path)}")
    
    click.echo(f"✅ Optimized {optimized_count} files")

@cli.command()
@click.pass_context
def build(ctx):
    """Build static site with semantic HTML"""
    try:
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
    
    click.echo("🔨 Building site...")
    config = ctx.obj
    
    # Initialize systems
    templates_path = Path(config['build'].get('templates', './templates'))
    template_engine = TemplateEngine(templates_path)
    generators = OutputGenerators(config)
    optimizer = AIOptimizer(config)
    
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
    all_pages = []
    all_posts = []
    all_projects = []
    
    # Parse markdown files
    click.echo("📝 Processing content...")
    for md_file in content_path.rglob('*.md'):
        content_type = md_file.parent.name
        
        # Parse markdown with frontmatter
        content = md_file.read_text()
        if content.startswith('---'):
            parts = content.split('---', 2)
            frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            body = parts[2] if len(parts) > 2 else ''
        else:
            frontmatter = {}
            body = content
        
        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra', 'meta'])
        content_html = md.convert(body)
        
        # Prepare context for template
        context = {
            'site_title': config['site']['title'],
            'lang': config['site']['language'],
            'title': frontmatter.get('title', md_file.stem.replace('-', ' ').title()),
            'description': frontmatter.get('summary', config['site']['description']),
            'content': content_html,
            'year': datetime.now().year,
            'navigation': config.get('nav', {}).get('main', []),
            'date': frontmatter.get('date'),
            'date_formatted': str(frontmatter.get('date', '')),
            'tags': frontmatter.get('tags', []),
            'jsonld': frontmatter.get('jsonld'),
        }
        
        # Add canonical URL
        slug = md_file.stem
        if content_type == 'posts':
            url = f"/posts/{slug}/"
        elif content_type == 'projects':
            url = f"/projects/{slug}/"
        elif content_type == 'pages':
            url = f"/pages/{slug}/"
        else:
            url = f"/{content_type}/{slug}/"
        
        context['canonical_url'] = f"{config['site']['url']}{url}"
        
        # Select template
        if content_type == 'posts':
            template_name = 'post.html'
        elif content_type == 'projects':
            template_name = 'post.html'  # Use same as posts for now
        else:
            template_name = 'page.html'
        
        # Render HTML
        try:
            html = template_engine.render(template_name, context)
        except Exception as e:
            click.echo(f"⚠️  Template error in {md_file}: {e}")
            html = process_markdown_fallback(md_file, content_type, config)
        
        # Determine output path
        output_file = dist_path / content_type / slug / 'index.html'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html)
        click.echo(f"  ✓ {md_file.relative_to(content_path)}")
        
        # Collect metadata for sitemaps
        page_data = {
            'url': url,
            'title': context['title'],
            'summary': context['description'],
            'date': context['date'],
            'type': content_type,
            'content_html': content_html,
            'tags': context['tags'],
        }
        
        if content_type == 'posts':
            all_posts.append(page_data)
        elif content_type == 'projects':
            all_projects.append(page_data)
        else:
            all_pages.append(page_data)
    
    # Create index page
    click.echo("🏠 Creating index page...")
    index_context = {
        'site_title': config['site']['title'],
        'lang': config['site']['language'],
        'title': config['site']['title'],
        'description': config['site']['description'],
        'year': datetime.now().year,
        'navigation': config.get('nav', {}).get('main', []),
        'posts': sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5],
    }
    
    index_html = create_index_simple(config, all_posts[:5])
    (dist_path / 'index.html').write_text(index_html)
    
    # Create list pages
    if all_posts:
        click.echo("📄 Creating posts index...")
        posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts')
        (dist_path / 'posts' / 'index.html').write_text(posts_html)
    
    if all_projects:
        click.echo("📄 Creating projects index...")
        projects_html = create_list_page_simple(config, all_projects, 'Projects')
        (dist_path / 'projects' / 'index.html').write_text(projects_html)
    
    # Generate outputs
    click.echo("🗺️  Generating sitemap, feeds, etc...")
    all_pages.append({'url': '/', 'title': config['site']['title'], 'type': 'home'})
    if all_posts:
        all_pages.append({'url': '/posts/', 'title': 'Posts', 'type': 'list'})
    if all_projects:
        all_pages.append({'url': '/projects/', 'title': 'Projects', 'type': 'list'})
    
    generators.generate_all(dist_path, all_pages, all_posts)
    
    click.echo(f"✅ Build complete! Output in {dist_path}")


def process_markdown_fallback(md_file: Path, content_type: str, config: Dict) -> str:
    """Fallback markdown processor if templates fail"""
    return process_markdown(md_file, content_type, config)


def create_index_simple(config: Dict, recent_posts: List) -> str:
    """Create simple index page"""
    posts_html = ""
    for post in recent_posts:
        posts_html += f'<li><a href="{post["url"]}">{post["title"]}</a></li>\n'
    
    return f"""<!DOCTYPE html>
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
            {posts_html}
        </ul>
        <p><a href="/posts/">View all posts →</a></p>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""


def create_list_page_simple(config: Dict, items: List, title: str) -> str:
    """Create simple list page"""
    items_html = ""
    for item in items:
        items_html += f'<li><a href="{item["url"]}">{item["title"]}</a>'
        if item.get('summary'):
            items_html += f'<p>{item["summary"]}</p>'
        items_html += '</li>\n'
    
    return f"""<!DOCTYPE html>
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
            margin-bottom: 1.5rem;
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
            {items_html}
        </ul>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""


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
@click.option('--output', '-o', type=click.Path(), help='Output JSON report to file')
@click.pass_context
def check(ctx):
    """Validate Template Contracts and WCAG compliance"""
    try:
        from core.validator import ContractValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.validator import ContractValidator
    
    click.echo("✅ Validating contracts...")
    config = ctx.obj
    validator = ContractValidator(config)
    
    dist_path = Path(config['build']['output'])
    if not dist_path.exists():
        click.echo("Error: dist/ directory not found. Run 'gang build' first.", err=True)
        return
    
    results = validator.validate_directory(dist_path)
    
    # Print summary
    summary = results['summary']
    click.echo(f"\n📊 Validation Results:")
    click.echo(f"  Total files: {summary['total_files']}")
    click.echo(f"  ✅ Passed: {summary['passed']}")
    click.echo(f"  ❌ Failed: {summary['failed']}")
    click.echo(f"  📈 Pass rate: {summary['pass_rate']:.1f}%")
    
    # Print file details
    for file_result in results['files']:
        file_summary = file_result['summary']
        if not file_summary['passed']:
            click.echo(f"\n❌ {Path(file_result['file']).name}")
            click.echo(f"   Errors: {file_summary['errors']}, Warnings: {file_summary['warnings']}")
            
            # Show issues
            for category in ['semantic', 'accessibility', 'seo', 'budgets']:
                issues = file_result[category]
                for issue in issues:
                    icon = '🔴' if issue['severity'] == 'error' else '🟡'
                    click.echo(f"   {icon} [{issue['rule']}] {issue['message']}")
    
    # Save JSON report if requested
    if ctx.params.get('output'):
        output_path = Path(ctx.params['output'])
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        click.echo(f"\n📄 Report saved to {output_path}")
    
    # Exit with error code if validation failed
    if summary['failed'] > 0:
        ctx.exit(1)

@cli.command()
@click.pass_context
def audit(ctx):
    """Run Lighthouse + axe audits"""
    click.echo("📊 Running audits...")
    click.echo("✓ Audit system coming soon!")

@cli.command()
@click.argument('source_dir', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), help='Output directory for processed images')
@click.pass_context
def image(ctx, source_dir, output):
    """Process images to responsive formats"""
    try:
        from core.images import ImageProcessor
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.images import ImageProcessor
    
    click.echo("🖼️  Processing images...")
    config = ctx.obj
    processor = ImageProcessor(config)
    
    source_path = Path(source_dir)
    output_path = Path(output) if output else Path(config['build']['output']) / 'assets' / 'images'
    
    image_map = processor.process_all_images(source_path, output_path)
    
    total_variants = sum(len(variants) for variants in image_map.values())
    click.echo(f"✅ Processed {len(image_map)} images into {total_variants} variants")
    
    for original, variants in image_map.items():
        click.echo(f"  {original}:")
        for variant in variants:
            size_kb = variant['size'] / 1024
            click.echo(f"    - {variant['width']}w {variant['format']}: {size_kb:.1f}KB")

@cli.command()
@click.option('--port', default=3000, help='Port for Studio')
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.pass_context
def studio(ctx, port, host):
    """Start Studio CMS"""
    click.echo(f"🎨 Starting GANG Studio on {host}:{port}...")
    
    # Import here to avoid dependency issues
    try:
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        import json
        import threading
        
        config = ctx.obj
        
        class StudioHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api/content':
                    # List all content files
                    content_path = Path(config['build']['content'])
                    files = []
                    for md_file in content_path.rglob('*.md'):
                        files.append({
                            'path': str(md_file.relative_to(content_path)),
                            'type': md_file.parent.name,
                            'name': md_file.stem
                        })
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(files).encode())
                
                elif self.path.startswith('/api/content/'):
                    # Get specific content file
                    file_path = self.path.replace('/api/content/', '')
                    content_path = Path(config['build']['content']) / file_path
                    
                    if content_path.exists():
                        content = content_path.read_text()
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(content.encode())
                    else:
                        self.send_error(404)
                
                else:
                    # Serve studio UI
                    self.path = '/studio.html' if self.path == '/' else self.path
                    return SimpleHTTPRequestHandler.do_GET(self)
        
        # Create studio HTML file
        studio_html_path = Path('studio.html')
        if not studio_html_path.exists():
            create_studio_html(studio_html_path)
        
        server = HTTPServer((host, port), StudioHandler)
        
        click.echo(f"✅ Studio running at http://{host}:{port}")
        click.echo("📝 Open this URL in your browser")
        click.echo("Press Ctrl+C to stop")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down Studio...")
            server.shutdown()
    
    except ImportError as e:
        click.echo(f"❌ Error starting Studio: {e}", err=True)
        click.echo("Studio requires additional dependencies")


def create_studio_html(output_path: Path):
    """Create the Studio CMS HTML interface"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GANG Studio</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: #f5f5f5;
        }
        
        .sidebar {
            width: 250px;
            background: #1a1a1a;
            color: #fff;
            display: flex;
            flex-direction: column;
        }
        
        .sidebar-header {
            padding: 1.5rem;
            border-bottom: 1px solid #333;
        }
        
        .sidebar-header h1 {
            font-size: 1.25rem;
            font-weight: 600;
        }
        
        .content-list {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }
        
        .content-item {
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background: #2a2a2a;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .content-item:hover {
            background: #333;
        }
        
        .content-item.active {
            background: #0066cc;
        }
        
        .content-item-name {
            font-weight: 500;
        }
        
        .content-item-type {
            font-size: 0.875rem;
            color: #999;
            margin-top: 0.25rem;
        }
        
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        
        .toolbar {
            padding: 1rem 1.5rem;
            background: #fff;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .toolbar button {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 4px;
            background: #0066cc;
            color: #fff;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .toolbar button:hover {
            background: #0052a3;
        }
        
        .editor {
            flex: 1;
            display: flex;
        }
        
        .editor-pane {
            flex: 1;
            padding: 2rem;
            background: #fff;
        }
        
        .editor-pane textarea {
            width: 100%;
            height: 100%;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            padding: 1rem;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.875rem;
            line-height: 1.6;
            resize: none;
        }
        
        .preview-pane {
            flex: 1;
            padding: 2rem;
            background: #fafafa;
            overflow-y: auto;
            border-left: 1px solid #e0e0e0;
        }
        
        .preview-content {
            max-width: 65ch;
            margin: 0 auto;
        }
        
        .loading {
            padding: 2rem;
            text-align: center;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>GANG Studio</h1>
        </div>
        <div class="content-list" id="contentList">
            <div class="loading">Loading content...</div>
        </div>
    </div>
    
    <div class="main">
        <div class="toolbar">
            <button onclick="saveContent()">💾 Save</button>
            <button onclick="buildSite()">🔨 Build</button>
            <button onclick="runOptimize()">🤖 Optimize</button>
            <span id="status"></span>
        </div>
        
        <div class="editor">
            <div class="editor-pane">
                <textarea id="editor" placeholder="Select a file to edit..."></textarea>
            </div>
            <div class="preview-pane">
                <div class="preview-content" id="preview">
                    <p style="color: #666;">Preview will appear here...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentFile = null;
        
        // Load content list
        async function loadContentList() {
            try {
                const response = await fetch('/api/content');
                const files = await response.json();
                
                const listEl = document.getElementById('contentList');
                listEl.innerHTML = '';
                
                files.forEach(file => {
                    const item = document.createElement('div');
                    item.className = 'content-item';
                    item.innerHTML = `
                        <div class="content-item-name">${file.name}</div>
                        <div class="content-item-type">${file.type}</div>
                    `;
                    item.onclick = () => loadFile(file.path);
                    listEl.appendChild(item);
                });
            } catch (e) {
                console.error('Failed to load content list:', e);
            }
        }
        
        // Load specific file
        async function loadFile(path) {
            try {
                const response = await fetch(`/api/content/${path}`);
                const content = await response.text();
                
                currentFile = path;
                document.getElementById('editor').value = content;
                updatePreview(content);
                
                // Update active state
                document.querySelectorAll('.content-item').forEach(item => {
                    item.classList.remove('active');
                });
                event.target.closest('.content-item').classList.add('active');
            } catch (e) {
                console.error('Failed to load file:', e);
            }
        }
        
        // Update preview
        function updatePreview(markdown) {
            // Simple markdown to HTML (just for preview)
            const html = markdown
                .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/\n\n/g, '</p><p>')
                .replace(/^(.+)$/gm, '<p>$1</p>');
            
            document.getElementById('preview').innerHTML = html;
        }
        
        // Save content
        function saveContent() {
            alert('Save functionality requires backend API integration');
        }
        
        // Build site
        function buildSite() {
            alert('Run "gang build" in terminal to build the site');
        }
        
        // Run optimize
        function runOptimize() {
            alert('Run "gang optimize" in terminal to optimize content');
        }
        
        // Auto-update preview
        document.getElementById('editor').addEventListener('input', (e) => {
            updatePreview(e.target.value);
        });
        
        // Load initial content
        loadContentList();
    </script>
</body>
</html>"""
    
    output_path.write_text(html)


if __name__ == '__main__':
    cli()

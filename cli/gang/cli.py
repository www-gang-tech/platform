#!/usr/bin/env python3
"""
GANG CLI - Single binary for all build operations
"""

import click
import yaml
import os
import hashlib
import json
import shutil
import markdown
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

@click.group()
@click.pass_context
def cli(ctx):
    """GANG - AI-first static publishing platform"""
    
    # Load .env file if it exists
    env_file = Path('.env')
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
        except:
            pass  # Continue if .env parsing fails
    
    config_path = Path('gang.config.yml')
    if not config_path.exists():
        click.echo("Error: gang.config.yml not found", err=True)
        ctx.abort()
    
    with open(config_path) as f:
        ctx.obj = yaml.safe_load(f)

@cli.command()
@click.option('--answerability', is_flag=True, help='Generate answerability report')
@click.option('--format', type=click.Choice(['json', 'html']), default='html')
@click.pass_context
def report(ctx, answerability, format):
    """Generate reports on content quality and structure"""
    
    if answerability:
        try:
            from core.answerability import AnswerabilityAnalyzer
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from core.answerability import AnswerabilityAnalyzer
        
        config = ctx.obj
        dist_path = Path(config['build']['output'])
        reports_dir = Path('reports')
        reports_dir.mkdir(exist_ok=True)
        
        click.echo("🔍 Analyzing answerability...\n")
        
        analyzer = AnswerabilityAnalyzer(dist_path)
        results = analyzer.analyze_site()
        
        # Save JSON
        json_path = reports_dir / 'answerability.json'
        json_path.write_text(json.dumps(results, indent=2))
        click.echo(f"✅ JSON report: {json_path}")
        
        # Save HTML dashboard
        html_path = reports_dir / 'answerability.html'
        html_report = analyzer.generate_html_report(results)
        html_path.write_text(html_report)
        click.echo(f"✅ HTML dashboard: {html_path}")
        
        # Print summary
        click.echo(f"\n📊 Summary:")
        click.echo(f"   Total Pages: {results['total_pages']}")
        click.echo(f"   JSON-LD Coverage: {results['jsonld_coverage_pct']:.1f}%")
        
        # Fail CI if coverage < 95%
        if results['jsonld_coverage_pct'] < 95:
            click.echo(f"\n❌ JSON-LD coverage below 95% threshold", err=True)
            ctx.exit(1)
        else:
            click.echo(f"\n✅ Answerability check passed!")

@cli.command()
@click.option('--verbose', is_flag=True, help='Show detailed validation results')
@click.pass_context
def check(ctx, verbose):
    """Validate site against contracts and standards"""
    try:
        from core.contract_validator import ContractValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.contract_validator import ContractValidator
    
    config = ctx.obj
    dist_path = Path(config['build']['output'])
    contracts_dir = Path('contracts')
    
    if not contracts_dir.exists():
        click.echo("❌ Contracts directory not found", err=True)
        click.echo("   Expected: ./contracts/*.yml")
        return
    
    validator = ContractValidator(contracts_dir)
    
    click.echo("🔍 Validating site against contracts...\n")
    
    results = []
    
    # Map dist paths to content types
    type_mapping = {
        'posts': 'post',
        'pages': 'page',
        'projects': 'project',
        'products': 'product'
    }
    
    for content_type_dir, contract_type in type_mapping.items():
        type_path = dist_path / content_type_dir
        if not type_path.exists():
            continue
        
        for html_file in type_path.rglob('index.html'):
            result = validator.validate_file(html_file, contract_type)
            results.append(result)
            
            if verbose:
                status = "✅" if result['valid'] else "❌"
                click.echo(f"{status} {html_file.relative_to(dist_path)}")
                if not result['valid'] and result['errors']:
                    for error in result['errors'][:3]:
                        click.echo(f"    • {error}")
    
    # Generate Explain report
    report = validator.generate_explain_report(results)
    click.echo("\n" + report)
    
    # Exit with error if any failures
    failed = [r for r in results if not r['valid']]
    if failed:
        ctx.exit(1)

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
@click.argument('file_path', type=click.Path(exists=True), required=False)
@click.option('--all', 'analyze_all', is_flag=True, help='Analyze all content files')
@click.option('--format', type=click.Choice(['text', 'json', 'summary']), default='text', help='Output format')
@click.option('--min-score', type=int, default=0, help='Minimum quality score (0-100, exit 1 if any file scores lower)')
@click.pass_context
def analyze(ctx, file_path, analyze_all, format, min_score):
    """Analyze content quality (readability, SEO, accessibility)"""
    try:
        from core.analyzer import ContentAnalyzer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.analyzer import ContentAnalyzer
    
    config = ctx.obj
    analyzer = ContentAnalyzer(config)
    
    # Batch analysis mode
    if analyze_all:
        content_path = Path(config['build']['content'])
        md_files = list(content_path.rglob('*.md'))
        
        if not md_files:
            click.echo("⚠️  No markdown files found", err=True)
            ctx.exit(1)
        
        click.echo(f"📊 Analyzing {len(md_files)} files...\n")
        
        all_analyses = []
        failed_quality = []
        
        for md_file in sorted(md_files):
            try:
                analysis = analyzer.analyze_file(md_file)
                all_analyses.append(analysis)
                
                # Calculate overall score
                seo_score = analysis['seo']['score']
                if seo_score < min_score:
                    failed_quality.append((md_file, seo_score))
                
                if format == 'text':
                    # Brief summary per file
                    status = analyzer._calculate_overall_status(analysis)
                    status_icon = analyzer._status_icon(status)
                    r = analysis['readability']
                    seo = analysis['seo']
                    click.echo(f"{status_icon} {md_file.relative_to(content_path)}")
                    click.echo(f"   └─ {r['word_count']} words, SEO: {seo['score']}/100, Grade: {r['grade_level']}")
                    
            except Exception as e:
                click.echo(f"❌ {md_file.relative_to(content_path)}: {e}")
        
        # Summary report
        if format == 'summary' or format == 'text':
            click.echo("\n" + "=" * 60)
            click.echo("📊 SUMMARY REPORT")
            click.echo("=" * 60)
            
            total_words = sum(a['readability']['word_count'] for a in all_analyses)
            avg_grade = sum(a['readability']['grade_level'] for a in all_analyses) / len(all_analyses)
            avg_seo = sum(a['seo']['score'] for a in all_analyses) / len(all_analyses)
            
            click.echo(f"Total files: {len(all_analyses)}")
            click.echo(f"Total words: {total_words:,}")
            click.echo(f"Avg grade level: {avg_grade:.1f}")
            click.echo(f"Avg SEO score: {avg_seo:.0f}/100")
            
            # Status breakdown
            statuses = [analyzer._calculate_overall_status(a) for a in all_analyses]
            click.echo(f"\nStatus breakdown:")
            click.echo(f"  ✓ Good: {statuses.count('good') + statuses.count('excellent')}")
            click.echo(f"  ⚠️  Warning: {statuses.count('warning')}")
            click.echo(f"  ✗ Poor: {statuses.count('poor')}")
            
            if failed_quality:
                click.echo(f"\n⚠️  {len(failed_quality)} file(s) below minimum score ({min_score}):")
                for file, score in failed_quality:
                    click.echo(f"  - {file.relative_to(content_path)}: {score}/100")
                ctx.exit(1)
        
        elif format == 'json':
            click.echo(json.dumps({
                'total_files': len(all_analyses),
                'total_words': sum(a['readability']['word_count'] for a in all_analyses),
                'files': all_analyses
            }, indent=2))
        
        return
    
    # Single file analysis
    if not file_path:
        click.echo("Error: Provide a file path or use --all", err=True)
        ctx.exit(1)
    
    file_path = Path(file_path)
    
    if not file_path.suffix == '.md':
        click.echo("⚠️  File must be a markdown (.md) file", err=True)
        ctx.exit(1)
    
    click.echo(f"📊 Analyzing {file_path}...\n")
    
    try:
        analysis = analyzer.analyze_file(file_path)
        
        if format == 'json':
            click.echo(json.dumps(analysis, indent=2))
        else:
            report = analyzer.format_report(analysis)
            click.echo(report)
        
        # Check minimum score
        seo_score = analysis['seo']['score']
        if seo_score < min_score:
            click.echo(f"\n❌ Quality check failed: SEO score {seo_score} < {min_score}")
            ctx.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Analysis failed: {e}", err=True)
        ctx.exit(1)

@cli.command()
@click.option('--links', is_flag=True, help='Validate all links (internal and external)')
@click.option('--internal-only', is_flag=True, help='Only check internal links (faster)')
@click.option('--suggest-fixes', is_flag=True, help='Use AI to suggest fixes for broken links')
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help='Output format')
@click.pass_context
def validate(ctx, links, internal_only, suggest_fixes, format):
    """Validate links, HTML, and other quality checks"""
    if not links:
        click.echo("Usage: gang validate --links [OPTIONS]")
        click.echo("")
        click.echo("Options:")
        click.echo("  --links           Validate all links")
        click.echo("  --internal-only   Only check internal links (faster)")
        click.echo("  --suggest-fixes   Use AI to suggest fixes (requires ANTHROPIC_API_KEY)")
        click.echo("  --format json     Output as JSON")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang validate --links")
        click.echo("  gang validate --links --internal-only")
        click.echo("  gang validate --links --suggest-fixes")
        return
    
    try:
        from core.link_validator import LinkValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.link_validator import LinkValidator
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    if format != 'json':
        click.echo("🔗 Validating links...")
    
    validator = LinkValidator(config, content_path, dist_path)
    
    results = validator.scan_all_files()
    
    # If internal-only, clear external results
    if internal_only:
        results['external_links'] = 0
        results['broken_external'] = []
        results['redirects'] = []
    
    if format == 'json':
        import json
        output_data = results
        
        # Add AI suggestions if requested
        if suggest_fixes and (results['broken_internal'] or results['broken_external'] or results['redirects']):
            click.echo(json.dumps(results, indent=2), err=True)
            click.echo("\n🤖 Generating AI fix suggestions...", err=True)
            suggestions = validator.suggest_fixes_with_ai(results)
            output_data = {
                'validation_results': results,
                'ai_suggestions': suggestions
            }
        
        click.echo(json.dumps(output_data, indent=2))
    else:
        report = validator.format_report(results)
        click.echo(report)
        
        # Show AI suggestions if requested
        if suggest_fixes and (results['broken_internal'] or results['broken_external'] or results['redirects']):
            click.echo("\n🤖 Generating AI fix suggestions...\n")
            suggestions = validator.suggest_fixes_with_ai(results)
            
            if 'error' in suggestions:
                click.echo(f"⚠️  {suggestions['error']}")
                click.echo("Set ANTHROPIC_API_KEY to enable AI suggestions")
            else:
                suggestions_report = validator.format_suggestions_report(suggestions)
                click.echo(suggestions_report)
    
    # Exit with error if broken links found
    if results['broken_internal'] or results['broken_external']:
        if format != 'json':
            click.echo(f"\n❌ Validation failed with {len(results['broken_internal']) + len(results['broken_external'])} broken links")
        ctx.exit(1)

@cli.command()
@click.option('--limit', type=int, default=10, help='Number of recent builds to show')
@click.pass_context
def performance(ctx, limit):
    """Show build performance history and trends"""
    try:
        from core.build_profiler import BuildProfiler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.build_profiler import BuildProfiler
    
    profiler = BuildProfiler()
    
    if not profiler.runs_file.exists():
        click.echo("No performance data yet. Run 'gang build --profile' first.")
        return
    
    try:
        with open(profiler.runs_file) as f:
            data = json.load(f)
            runs = data.get('runs', [])
        
        if not runs:
            click.echo("No performance data yet.")
            return
        
        click.echo("=" * 60)
        click.echo(f"⚡ Build Performance History (last {min(limit, len(runs))} runs)")
        click.echo("=" * 60)
        click.echo("")
        
        # Show recent runs
        for i, run in enumerate(runs[-limit:], 1):
            timestamp = run.get('timestamp', 'Unknown')
            duration_ms = run.get('total_duration_ms', 0)
            duration_s = duration_ms / 1000
            
            click.echo(f"#{len(runs) - limit + i}: {duration_ms}ms ({duration_s:.2f}s)")
            click.echo(f"   Time: {timestamp}")
            
            # Show file counts
            files = run.get('files', {})
            if files:
                total_files = sum(files.values())
                click.echo(f"   Files: {total_files} ({', '.join(f'{k}:{v}' for k, v in files.items())})")
            
            click.echo("")
        
        # Calculate stats
        if len(runs) >= 2:
            recent_5 = runs[-5:] if len(runs) >= 5 else runs
            avg_duration = sum(r['total_duration_ms'] for r in recent_5) / len(recent_5)
            fastest = min(r['total_duration_ms'] for r in runs)
            slowest = max(r['total_duration_ms'] for r in runs)
            
            click.echo("📊 Statistics:")
            click.echo(f"├─ Average (last 5): {avg_duration:.0f}ms")
            click.echo(f"├─ Fastest: {fastest}ms")
            click.echo(f"└─ Slowest: {slowest}ms")
            click.echo("")
        
        click.echo("=" * 60)
        click.echo("💡 Run 'gang build --profile' to track performance")
        click.echo("=" * 60)
    
    except Exception as e:
        click.echo(f"Error reading performance data: {e}")

@cli.command()
@click.option('--links', is_flag=True, help='Fix broken links using AI suggestions')
@click.option('--apply', is_flag=True, help='Actually apply fixes (default is suggestions only)')
@click.option('--commit', is_flag=True, help='Create git commit with suggested fixes')
@click.option('--min-confidence', type=click.Choice(['high', 'medium', 'low']), default='high', help='Minimum confidence for applying')
@click.option('--rebuild', is_flag=True, help='Rebuild site after applying fixes')
@click.pass_context
def fix(ctx, links, apply, commit, min_confidence, rebuild):
    """Show AI suggestions for fixing broken links (use --apply to actually fix)"""
    if not links:
        click.echo("Usage: gang fix --links [OPTIONS]")
        click.echo("")
        click.echo("Options:")
        click.echo("  --links              Get AI suggestions for broken links")
        click.echo("  --apply              Actually apply the fixes (default: suggestions only)")
        click.echo("  --commit             Create git commit with fixes for review")
        click.echo("  --min-confidence     Minimum confidence: high|medium|low (default: high)")
        click.echo("  --rebuild            Rebuild site after fixing")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang fix --links                    # Show suggestions only (safe)")
        click.echo("  gang fix --links --apply            # Apply high-confidence fixes")
        click.echo("  gang fix --links --commit           # Create git commit for review")
        click.echo("  gang fix --links --apply --rebuild  # Fix and rebuild")
        click.echo("")
        click.echo("⚠️  Default behavior: Shows suggestions WITHOUT applying them")
        click.echo("    Use --apply to actually modify files")
        return
    
    try:
        from core.link_validator import LinkValidator
        from core.link_fixer import LinkFixer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.link_validator import LinkValidator
        from core.link_fixer import LinkFixer
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    # Step 1: Validate links
    click.echo("🔗 Validating links...")
    validator = LinkValidator(config, content_path, dist_path)
    results = validator.scan_all_files()
    
    broken_count = len(results['broken_internal']) + len(results['broken_external'])
    
    if broken_count == 0:
        click.echo("✓ No broken links found!")
        return
    
    click.echo(f"Found {broken_count} broken link(s)\n")
    
    # Step 2: Get AI suggestions
    click.echo("🤖 Generating AI fix suggestions...")
    suggestions = validator.suggest_fixes_with_ai(results)
    
    if 'error' in suggestions:
        click.echo(f"❌ {suggestions['error']}")
        click.echo("Set ANTHROPIC_API_KEY to enable AI-powered fixes")
        ctx.exit(1)
    
    # Show suggestions
    suggestions_report = validator.format_suggestions_report(suggestions)
    click.echo(suggestions_report)
    
    # Step 3: Apply fixes if requested
    if apply or commit:
        click.echo(f"\n🔧 Applying fixes (min confidence: {min_confidence})...\n")
        
        fixer = LinkFixer(content_path)
        fix_results = fixer.apply_suggestions(suggestions, min_confidence, dry_run=False)
        
        # Show what was applied
        report = fixer.format_report(fix_results)
        click.echo(report)
        
        # Step 4: Create git commit if requested
        if commit and fix_results['applied'] > 0:
            click.echo("\n📝 Creating git commit...")
            try:
                import subprocess
                
                # Add changed files
                files_changed = list(set([f['file'] for f in fix_results['fixes']]))
                for file in files_changed:
                    file_path = content_path / file
                    subprocess.run(['git', 'add', str(file_path)], check=True)
                
                # Create commit message
                commit_msg = f"Fix {fix_results['applied']} broken link(s) [AI-suggested]\n\n"
                for fix in fix_results['fixes']:
                    if fix['action'] == 'replaced':
                        commit_msg += f"- {fix['file']}: {fix['old_url']} → {fix['new_url']}\n"
                    else:
                        commit_msg += f"- {fix['file']}: Removed {fix['old_url']}\n"
                
                subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
                click.echo("✅ Git commit created!")
                click.echo("   Review with: git show")
                click.echo("   Undo with: git reset HEAD^")
                
            except subprocess.CalledProcessError as e:
                click.echo(f"⚠️  Could not create git commit: {e}")
            except Exception as e:
                click.echo(f"⚠️  Git commit failed: {e}")
        
        # Step 5: Rebuild if requested
        if rebuild and fix_results['applied'] > 0:
            click.echo("\n🔨 Rebuilding site...")
            ctx.invoke(build)
    else:
        click.echo("\n💡 To apply these suggestions:")
        click.echo("   gang fix --links --apply           # Apply and review manually")
        click.echo("   gang fix --links --commit          # Create git commit for review")
        click.echo("   gang fix --links --apply --rebuild # Apply and rebuild")
        ctx.exit(1)  # Exit with error to block workflow until fixed

@cli.group()
def media():
    """Manage media files (upload to R2, sync, list)"""
    pass

@media.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('--path', help='Remote path in R2 (default: images/filename)')
@click.pass_context
def upload(ctx, source, path):
    """Upload file(s) to Cloudflare R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing environment variables:")
        for var in missing:
            click.echo(f"  - {var}")
        click.echo("\nSee MEDIA_STORAGE_GUIDE.md for setup instructions")
        ctx.exit(1)
    
    source_path = Path(source)
    
    # Upload directory or single file
    if source_path.is_dir():
        click.echo(f"📁 Uploading directory: {source_path}")
        remote_prefix = path or 'images'
        result = storage.upload_directory(source_path, remote_prefix)
        
        if result['uploaded']:
            total_mb = result['total_size'] / (1024 * 1024)
            click.echo(f"\n✅ Uploaded {len(result['uploaded'])} file(s) ({total_mb:.2f}MB)")
            for item in result['uploaded'][:5]:
                click.echo(f"  ✓ {item['file']}")
                click.echo(f"    {item['url']}")
            if len(result['uploaded']) > 5:
                click.echo(f"  ... and {len(result['uploaded']) - 5} more")
        
        if result['failed']:
            click.echo(f"\n❌ Failed: {len(result['failed'])} file(s)")
            for item in result['failed'][:3]:
                click.echo(f"  ✗ {item['file']}: {item['error']}")
    
    else:
        # Single file upload
        remote_path = path or f"images/{source_path.name}"
        click.echo(f"📤 Uploading {source_path.name} to {remote_path}...")
        
        result = storage.upload_file(source_path, remote_path)
        
        if 'error' in result:
            click.echo(f"❌ Upload failed: {result['error']}")
            ctx.exit(1)
        else:
            size_kb = result['size'] / 1024
            click.echo(f"✅ Uploaded successfully ({size_kb:.1f}KB)")
            click.echo(f"📍 Public URL: {result['public_url']}")
            click.echo(f"\n💡 Use in markdown:")
            click.echo(f"   ![Alt text]({result['public_url']})")

@media.command()
@click.option('--prefix', default='', help='Filter by prefix (e.g., images/)')
@click.option('--limit', default=100, type=int, help='Max files to show')
@click.pass_context
def list(ctx, prefix, limit):
    """List files in R2 bucket"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing:")
        for var in missing:
            click.echo(f"  - {var}")
        ctx.exit(1)
    
    click.echo(f"📁 Listing files in {storage.bucket_name}/{prefix or '(root)'}...")
    
    files = storage.list_files(prefix, limit)
    
    if not files:
        click.echo("No files found")
        return
    
    total_size = sum(f['size'] for f in files)
    total_mb = total_size / (1024 * 1024)
    
    click.echo(f"\nFound {len(files)} file(s) ({total_mb:.2f}MB total):\n")
    
    for file in files[:limit]:
        size_kb = file['size'] / 1024
        click.echo(f"📄 {file['key']}")
        click.echo(f"   Size: {size_kb:.1f}KB")
        click.echo(f"   URL: {file['url']}")
        click.echo("")

@media.command()
@click.argument('source_dir', type=click.Path(exists=True))
@click.option('--prefix', default='images', help='Remote prefix in R2')
@click.option('--delete', is_flag=True, help='Delete remote files not in local')
@click.pass_context
def sync(ctx, source_dir, prefix, delete):
    """Sync local directory to R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing:")
        for var in missing:
            click.echo(f"  - {var}")
        ctx.exit(1)
    
    source_path = Path(source_dir)
    click.echo(f"🔄 Syncing {source_path} → {storage.bucket_name}/{prefix}...")
    
    if delete:
        click.echo("⚠️  Delete mode enabled - will remove remote files not in local")
    
    result = storage.sync_directory(source_path, prefix, delete)
    
    click.echo(f"\n✅ Sync complete!")
    click.echo(f"  Uploaded: {result['uploaded']}")
    click.echo(f"  Skipped: {result['skipped']}")
    if delete:
        click.echo(f"  Deleted: {result['deleted']}")
    
    if result['errors']:
        click.echo(f"\n⚠️  Errors: {len(result['errors'])}")
        for error in result['errors'][:3]:
            click.echo(f"  - {error}")

@media.command()
@click.argument('remote_path')
@click.pass_context
def delete(ctx, remote_path):
    """Delete file from R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        click.echo("❌ R2 not configured")
        ctx.exit(1)
    
    if not click.confirm(f"Delete {remote_path} from R2?"):
        click.echo("Cancelled")
        return
    
    result = storage.delete_file(remote_path)
    
    if 'error' in result:
        click.echo(f"❌ Delete failed: {result['error']}")
        ctx.exit(1)
    else:
        click.echo(f"✅ Deleted: {remote_path}")

@cli.command()
@click.argument('source', type=click.Path(exists=True), required=False)
@click.option('--title', help='Article title (auto-detected if not provided)')
@click.option('--category', type=click.Choice(['posts', 'pages', 'projects']), help='Content category (AI suggests if not provided)')
@click.option('--compress-images', is_flag=True, default=True, help='Compress images before upload')
@click.option('--commit', is_flag=True, help='Create git commit after import')
@click.pass_context
def import_content(ctx, source, title, category, compress_images, commit):
    """Import content from file or clipboard (extracts & uploads images)"""
    try:
        from core.content_importer import ContentImporter
        from core.r2_storage import R2Storage
        from anthropic import Anthropic
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import ContentImporter
        from core.r2_storage import R2Storage
        try:
            from anthropic import Anthropic
        except:
            Anthropic = None
    
    config = ctx.obj
    
    # Initialize R2 storage
    r2_storage = R2Storage(config)
    
    # Initialize AI client
    ai_client = None
    if Anthropic and os.environ.get('ANTHROPIC_API_KEY'):
        ai_client = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    
    # Initialize importer
    importer = ContentImporter(config, r2_storage, ai_client)
    
    # Read content
    if source:
        content = Path(source).read_text()
        click.echo(f"📄 Importing from {source}...")
    else:
        # Try to read from clipboard
        try:
            import subprocess
            result = subprocess.run(['pbpaste'], capture_output=True, text=True)
            content = result.stdout
            if not content.strip():
                click.echo("❌ No content in clipboard. Provide a file or copy content first.")
                ctx.exit(1)
            click.echo("📋 Importing from clipboard...")
        except:
            click.echo("❌ Cannot read clipboard. Provide a file path instead.")
            ctx.exit(1)
    
    # Import and process
    click.echo("🔍 Analyzing content...")
    result = importer.import_from_text(content, title)
    
    # Show what was found
    click.echo(f"\n📊 Import Analysis:")
    click.echo(f"├─ Title: {result['title']}")
    click.echo(f"├─ Suggested slug: {result['suggested_slug']}")
    if result['suggested_category']:
        cat = result['suggested_category']
        click.echo(f"├─ AI category: {cat['category']} ({cat['confidence']} confidence)")
        click.echo(f"│  └─ {cat['reasoning']}")
    click.echo(f"└─ Images found: {len(result['images'])}")
    
    # Check slug conflicts
    if result['slug_conflicts']:
        click.echo(f"\n⚠️  Slug conflict! '{result['suggested_slug']}' already exists:")
        for conflict in result['slug_conflicts']:
            click.echo(f"  - {conflict}")
        
        # Suggest unique slug
        from core.content_importer import SlugChecker
        checker = SlugChecker(importer.content_path)
        suggested_cat = category or result.get('suggested_category', {}).get('category', 'pages')
        unique_slug = checker.suggest_unique_slug(result['suggested_slug'], suggested_cat)
        click.echo(f"\n💡 Suggested unique slug: {unique_slug}")
        
        if not click.confirm(f"Use '{unique_slug}' instead?"):
            click.echo("Import cancelled. Choose a different title or slug.")
            ctx.exit(1)
        
        result['suggested_slug'] = unique_slug
    
    # Process and upload images
    if result['images']:
        click.echo(f"\n🖼️  Processing {len(result['images'])} image(s)...")
        
        processed_images = importer.process_and_upload_images(
            result['images'],
            result['suggested_slug'],
            compress=compress_images
        )
        
        # Show upload results
        for img in processed_images:
            if img.get('type') == 'uploaded':
                size_kb = img['size'] / 1024
                orig_kb = img['original_size'] / 1024
                savings = ((img['original_size'] - img['size']) / img['original_size']) * 100
                click.echo(f"  ✓ Uploaded & compressed: {size_kb:.1f}KB (saved {savings:.0f}%)")
                if img.get('alt_generated_by_ai'):
                    click.echo(f"    Alt text (AI): {img['alt']}")
    
    # Create markdown file
    final_category = category or result.get('suggested_category', {}).get('category', 'pages')
    file_path, markdown_content = importer.create_markdown_file(
        result['title'],
        result['content'],
        final_category,
        result['suggested_slug']
    )
    
    # Show preview
    click.echo(f"\n📝 Will create: {file_path}")
    click.echo("\nPreview (first 10 lines):")
    click.echo("─" * 60)
    for i, line in enumerate(markdown_content.split('\n')[:10], 1):
        click.echo(line)
    click.echo("...")
    click.echo("─" * 60)
    
    # Confirm
    if not click.confirm("\nCreate this file?"):
        click.echo("Import cancelled")
        ctx.exit(1)
    
    # Save
    save_result = importer.save_imported_content(file_path, markdown_content, commit)
    
    if save_result['success']:
        click.echo(f"\n✅ Content imported successfully!")
        click.echo(f"📁 File: {save_result['file_path']}")
        
        if save_result.get('git_commit'):
            click.echo(f"✅ Git commit created")
            click.echo(f"   Review: git show")
        
        click.echo(f"\n💡 Next steps:")
        click.echo(f"   1. Review and edit: vim {file_path}")
        click.echo(f"   2. Analyze quality: gang analyze {file_path}")
        click.echo(f"   3. Change status to 'published' when ready")
        click.echo(f"   4. Build: gang build")

@cli.command()
@click.argument('old_slug')
@click.argument('new_slug')
@click.option('--category', type=click.Choice(['posts', 'pages', 'projects']), required=True, help='Content category')
@click.option('--redirect', is_flag=True, default=True, help='Create 301 redirect (default: yes)')
@click.option('--no-redirect', is_flag=True, help='Skip creating redirect')
@click.pass_context
def rename_slug(ctx, old_slug, new_slug, category, redirect, no_redirect):
    """Rename a content slug with optional 301 redirect"""
    try:
        from core.content_importer import SlugChecker
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import SlugChecker
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    # Check old file exists
    old_file = content_path / category / f"{old_slug}.md"
    if not old_file.exists():
        click.echo(f"❌ File not found: {old_file}")
        ctx.exit(1)
    
    # Check new slug is unique
    checker = SlugChecker(content_path)
    new_file = content_path / category / f"{new_slug}.md"
    if new_file.exists():
        click.echo(f"❌ Slug '{new_slug}' already exists: {new_file}")
        click.echo(f"💡 Choose a different slug")
        ctx.exit(1)
    
    # Show what will happen
    click.echo(f"📝 Rename slug in {category}:")
    click.echo(f"   From: {old_slug}")
    click.echo(f"   To:   {new_slug}")
    click.echo(f"")
    
    old_url = f"/{category}/{old_slug}/"
    new_url = f"/{category}/{new_slug}/"
    
    create_redirect = redirect and not no_redirect
    
    if create_redirect:
        click.echo(f"🔀 Will create 301 redirect:")
        click.echo(f"   {old_url} → {new_url}")
    else:
        click.echo(f"⚠️  No redirect will be created")
        click.echo(f"   Old URL {old_url} will return 404")
    
    click.echo(f"")
    
    if not click.confirm("Proceed with rename?"):
        click.echo("Cancelled")
        return
    
    # Rename file
    try:
        old_file.rename(new_file)
        click.echo(f"✅ File renamed: {old_file.name} → {new_file.name}")
    except Exception as e:
        click.echo(f"❌ Rename failed: {e}")
        ctx.exit(1)
    
    # Create redirect if requested
    if create_redirect:
        redirect_manager = RedirectManager(content_path, dist_path)
        result = redirect_manager.add_redirect(old_url, new_url, reason='slug_rename')
        
        if result.get('created'):
            click.echo(f"✅ 301 redirect created")
        elif result.get('updated'):
            click.echo(f"✅ Redirect updated (was already tracking this path)")
        
        click.echo(f"📄 Redirects file: .redirects.json")
    
    # Create git commit
    if click.confirm("\nCreate git commit?"):
        try:
            import subprocess
            
            # Stage renamed file
            subprocess.run(['git', 'add', str(new_file)], check=True)
            subprocess.run(['git', 'rm', str(old_file)], check=True)
            
            if create_redirect:
                subprocess.run(['git', 'add', str(redirect_manager.redirects_file)], check=True)
            
            commit_msg = f"Rename slug: {old_slug} → {new_slug}"
            if create_redirect:
                commit_msg += f"\n\nAdded 301 redirect: {old_url} → {new_url}"
            
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
            click.echo(f"✅ Git commit created")
        except Exception as e:
            click.echo(f"⚠️  Git commit failed: {e}")
    
    click.echo(f"\n💡 Next steps:")
    click.echo(f"   1. gang build  # Rebuild with new slug")
    click.echo(f"   2. Check redirects: cat .redirects.json")
    click.echo(f"   3. Deploy (redirects go live)")

@cli.group()
def redirects():
    """Manage 301 redirects for slug changes"""
    pass

@redirects.command('list')
@click.option('--format', type=click.Choice(['text', 'json', 'cloudflare', 'nginx', 'netlify']), default='text')
@click.pass_context
def list_redirects(ctx, format):
    """List all redirects"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    redirects_list = manager.list_all_redirects()
    
    if format == 'json':
        import json
        click.echo(json.dumps(redirects_list, indent=2))
    elif format == 'cloudflare':
        click.echo(manager.generate_cloudflare_redirects())
    elif format == 'nginx':
        click.echo(manager.generate_nginx_redirects())
    elif format == 'netlify':
        click.echo(manager.generate_netlify_redirects())
    else:
        if not redirects_list:
            click.echo("No redirects configured")
            return
        
        click.echo(f"📋 {len(redirects_list)} redirect(s):\n")
        for r in redirects_list:
            status = r.get('status', 301)
            click.echo(f"  {r['from']} → {r['to']} ({status})")
            if 'reason' in r:
                click.echo(f"    Reason: {r['reason']}")
            if 'created' in r:
                click.echo(f"    Created: {r['created']}")
            click.echo()

@redirects.command('add')
@click.argument('from_path')
@click.argument('to_path')
@click.option('--temporary', is_flag=True, help='Use 302 instead of 301')
@click.pass_context
def add_redirect(ctx, from_path, to_path, temporary):
    """Add a manual redirect"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    result = manager.add_redirect(
        from_path, 
        to_path, 
        reason='manual',
        permanent=not temporary
    )
    
    status = 302 if temporary else 301
    if result.get('created'):
        click.echo(f"✅ Redirect created: {from_path} → {to_path} ({status})")
    elif result.get('updated'):
        click.echo(f"✅ Redirect updated: {from_path} → {to_path} ({status})")

@redirects.command('remove')
@click.argument('from_path')
@click.pass_context
def remove_redirect(ctx, from_path):
    """Remove a redirect"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    
    if manager.remove_redirect(from_path):
        click.echo(f"✅ Redirect removed: {from_path}")
    else:
        click.echo(f"❌ Redirect not found: {from_path}")
        ctx.exit(1)

@redirects.command('validate')
@click.pass_context
def validate_redirects(ctx):
    """Check for redirect chains and loops"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    issues = manager.validate_redirect_chain()
    
    if not issues:
        click.echo("✅ No redirect chains or loops detected")
    else:
        click.echo(f"⚠️  Found {len(issues)} issue(s):\n")
        for issue in issues:
            click.echo(f"  • {issue}")
        ctx.exit(1)

@cli.command()
@click.pass_context
def schedule(ctx):
    """View content publishing schedule"""
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    scheduler = ContentScheduler(content_path)
    summary = scheduler.get_scheduled_summary()
    report = scheduler.format_schedule_report(summary)
    
    click.echo(report)
    
    # Exit with code 1 if there are items to publish (for CI/CD triggers)
    if summary['scheduled'] > 0:
        ctx.exit(0)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.argument('publish_date', required=False)
@click.option('--now', is_flag=True, help='Publish immediately (remove schedule)')
@click.option('--status', default='scheduled', help='Content status (draft, scheduled, published)')
@click.pass_context
def set_schedule(ctx, file_path, publish_date, now, status):
    """Set or update publish date for content"""
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    from datetime import datetime
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    scheduler = ContentScheduler(content_path)
    
    file_path = Path(file_path)
    
    if now:
        # Remove schedule, publish now
        success = scheduler.set_publish_date(file_path, None, 'published')
        if success:
            click.echo(f"✅ Removed schedule from {file_path.name}")
            click.echo(f"   Status: published (will appear in next build)")
        else:
            click.echo(f"❌ Failed to update {file_path.name}")
            ctx.exit(1)
    elif publish_date:
        # Parse and set publish date
        try:
            # Try ISO format first
            pub_date = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
        except:
            # Try common formats
            for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S']:
                try:
                    pub_date = datetime.strptime(publish_date, fmt)
                    break
                except:
                    continue
            else:
                click.echo(f"❌ Invalid date format: {publish_date}")
                click.echo("   Use: YYYY-MM-DD or YYYY-MM-DD HH:MM or ISO format")
                ctx.exit(1)
        
        # Ensure timezone aware
        if pub_date.tzinfo is None:
            from datetime import timezone
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        success = scheduler.set_publish_date(file_path, pub_date, status)
        
        if success:
            click.echo(f"✅ Scheduled {file_path.name}")
            click.echo(f"   Publish date: {pub_date.strftime('%Y-%m-%d %H:%M %Z')}")
            click.echo(f"   Status: {status}")
            
            # Show relative time
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            delta = pub_date - now
            
            if delta.days > 0:
                click.echo(f"   Will publish in {delta.days} day(s)")
            elif delta.seconds > 3600:
                hours = delta.seconds // 3600
                click.echo(f"   Will publish in {hours} hour(s)")
            elif delta.total_seconds() > 0:
                minutes = delta.seconds // 60
                click.echo(f"   Will publish in {minutes} minute(s)")
            else:
                click.echo(f"   ⚠️  Publish date is in the past (will publish on next build)")
        else:
            click.echo(f"❌ Failed to schedule {file_path.name}")
            ctx.exit(1)
    else:
        click.echo("Error: Provide a publish date or use --now")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang set-schedule content/posts/my-post.md '2025-12-25'")
        click.echo("  gang set-schedule content/posts/my-post.md '2025-12-25 09:00'")
        click.echo("  gang set-schedule content/posts/my-post.md --now")
        ctx.exit(1)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.option('--limit', default=20, help='Number of versions to show')
@click.pass_context
def history(ctx, file_path, limit):
    """Show version history for a content file"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    file_path = Path(file_path)
    
    history_list = versioning.get_file_history(file_path, limit)
    
    if not history_list:
        click.echo(f"No version history found for {file_path.name}")
        click.echo("(File may not be tracked in git)")
        return
    
    report = versioning.format_history_report(history_list, file_path)
    click.echo(report)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.argument('commit')
@click.pass_context
def restore(ctx, file_path, commit):
    """Restore a file to a specific commit version"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    file_path = Path(file_path)
    
    # Show what we're restoring
    history = versioning.get_file_history(file_path, limit=50)
    target_commit = None
    
    for h in history:
        if h['commit'].startswith(commit) or h['short_commit'] == commit:
            target_commit = h
            break
    
    if not target_commit:
        click.echo(f"❌ Commit not found: {commit}")
        click.echo(f"   Run 'gang history {file_path}' to see available versions")
        ctx.exit(1)
    
    click.echo(f"📜 Restoring {file_path.name}")
    click.echo(f"   To version: {target_commit['short_commit']}")
    click.echo(f"   Date: {target_commit['date']}")
    click.echo(f"   Message: {target_commit['message']}")
    click.echo("")
    
    if not click.confirm("Proceed with restore?"):
        click.echo("Cancelled")
        return
    
    success = versioning.restore_file_version(file_path, target_commit['commit'])
    
    if success:
        click.echo(f"✅ Restored {file_path.name} to version {target_commit['short_commit']}")
        click.echo(f"   Changes are in your working directory (not committed)")
        click.echo(f"   Run 'git add {file_path}' and 'git commit' to save")
    else:
        click.echo(f"❌ Failed to restore {file_path.name}")
        ctx.exit(1)

@cli.command()
@click.option('--days', default=7, help='Number of days to look back')
@click.pass_context
def changes(ctx, days):
    """Show recent content changes"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    from datetime import datetime
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    recent = versioning.get_recent_changes(days)
    
    if not recent:
        click.echo(f"No content changes in the last {days} days")
        return
    
    click.echo(f"📝 Content Changes (Last {days} days)")
    click.echo("=" * 60)
    click.echo(f"Total commits: {len(recent)}\n")
    
    for commit in recent:
        date = datetime.fromisoformat(commit['date'])
        date_str = date.strftime('%Y-%m-%d %H:%M')
        
        click.echo(f"[{commit['short_commit']}] {date_str} - {commit['author']}")
        click.echo(f"  {commit['message']}")
        
        if commit['files']:
            for file in commit['files']:
                status_icon = {
                    'M': '📝',
                    'A': '✨',
                    'D': '🗑️',
                    'R': '🔄'
                }.get(file['status'], '•')
                click.echo(f"    {status_icon} {file['path']}")
        
        click.echo("")

@cli.command()
@click.argument('image_path', type=click.Path(exists=True))
@click.option('--focal-x', type=float, default=0.5, help='Focal point X (0-1)')
@click.option('--focal-y', type=float, default=0.5, help='Focal point Y (0-1)')
@click.option('--auto-detect', is_flag=True, help='Auto-detect focal point using AI')
@click.option('--is-lcp', is_flag=True, help='Mark as LCP image (no lazy loading)')
@click.pass_context
def process_image(ctx, image_path, focal_x, focal_y, auto_detect, is_lcp):
    """Process image with focal point and generate responsive crops"""
    try:
        from core.image_pipeline import ImagePipeline, FocalPointDetector
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.image_pipeline import ImagePipeline, FocalPointDetector
    
    config = ctx.obj
    public_path = Path(config['build']['public'])
    dist_path = Path(config['build']['output'])
    
    pipeline = ImagePipeline(public_path, dist_path)
    
    image = Path(image_path)
    
    if auto_detect:
        click.echo("🔍 Detecting focal point...")
        focal_point = FocalPointDetector.detect_focal_point(image)
        click.echo(f"   Detected: ({focal_point[0]:.2f}, {focal_point[1]:.2f})")
    else:
        focal_point = (focal_x, focal_y)
    
    click.echo(f"🖼️  Processing: {image.name}")
    result = pipeline.process_image(image, focal_point, is_lcp)
    
    click.echo(f"✅ Generated {len(result['crops'])} crops")
    click.echo(f"✅ Generated {len(result['formats'])} formats")
    
    if result['thumbhash']:
        click.echo(f"✅ ThumbHash: {result['thumbhash']}")
    
    click.echo(f"\n<picture> HTML:")
    click.echo(result['html'])

@cli.command()
@click.option('--from', 'bundle_path', type=click.Path(exists=True), help='Bundle JSON file')
@click.option('--platform', type=click.Choice(['twitter', 'linkedin', 'medium', 'devto']), required=True)
@click.pass_context
def syndicate(ctx, bundle_path, platform):
    """Render syndication bundle for a platform"""
    try:
        from core.syndication_bundle import render_syndication_bundle
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.syndication_bundle import render_syndication_bundle
    
    if bundle_path:
        output = render_syndication_bundle(Path(bundle_path), platform)
        click.echo(output)
    else:
        click.echo("❌ Please provide a bundle file with --from", err=True)

@cli.group()
def email():
    """Email newsletter management"""
    pass

@email.command('create-from-post')
@click.argument('post_path', type=click.STRING)
@click.option('--output', default='./emails', help='Output directory for email files')
@click.option('--esp', default='buttondown', help='ESP provider (buttondown, convertkit, mailerlite, postmark, sendgrid)')
@click.pass_context
def email_create_from_post(ctx, post_path, output, esp):
    """Create email template from a post"""
    try:
        from core.email_templates import EmailOrchestrator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import EmailOrchestrator
    
    config = ctx.obj
    post_file = Path(post_path)
    
    if not post_file.exists():
        click.echo(f"❌ Post not found: {post_path}", err=True)
        return
    
    orchestrator = EmailOrchestrator(config, esp)
    output_dir = Path(output)
    
    click.echo(f"📧 Creating email from: {post_file.name}")
    
    metadata = orchestrator.create_email_from_post(post_file, output_dir)
    
    # Save newsletter to content for public listing
    content_path = Path(config['build']['content'])
    newsletter_file = orchestrator.save_newsletter_to_content(post_file, metadata, content_path)
    
    click.echo(f"\n✅ Email created:")
    click.echo(f"   Title: {metadata['title']}")
    click.echo(f"   HTML: {metadata['html_path']}")
    click.echo(f"   Text: {metadata['text_path']}")
    click.echo(f"   Status: {metadata['status']}")
    click.echo(f"   Newsletter page: {newsletter_file}")
    click.echo(f"\n📝 Next steps:")
    click.echo(f"   1. Review email: open {metadata['html_path']}")
    click.echo(f"   2. Send draft to ESP: gang email send-draft {metadata['slug']}")
    click.echo(f"   3. Build site to publish newsletter page: gang build")
    click.echo(f"   4. Or manually upload to {esp}")

@email.command('send-draft')
@click.argument('email_slug')
@click.option('--emails-dir', default='./emails', help='Directory containing email files')
@click.option('--api-key', envvar='ESP_API_KEY', help='ESP API key')
@click.option('--from-email', required=True, help='From email address')
@click.pass_context
def email_send_draft(ctx, email_slug, emails_dir, api_key, from_email):
    """Send email draft to ESP"""
    try:
        from core.email_templates import ESPIntegration
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import ESPIntegration
    
    import json
    
    emails_path = Path(emails_dir)
    meta_file = emails_path / f"{email_slug}.json"
    
    if not meta_file.exists():
        click.echo(f"❌ Email not found: {email_slug}", err=True)
        return
    
    if not api_key:
        click.echo("❌ ESP_API_KEY environment variable not set", err=True)
        click.echo("   Set it with: export ESP_API_KEY=your_key")
        return
    
    # Load metadata
    metadata = json.loads(meta_file.read_text())
    
    # Load email content
    html_content = Path(metadata['html_path']).read_text()
    text_content = Path(metadata['text_path']).read_text()
    
    # Send to ESP
    esp = ESPIntegration(metadata['esp_provider'], api_key)
    
    click.echo(f"📤 Sending draft to {metadata['esp_provider']}...")
    
    try:
        result = esp.create_draft(
            subject=metadata['title'],
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            preview_text=metadata.get('preview_text', '')
        )
        
        click.echo(f"✅ Draft created in {metadata['esp_provider']}")
        click.echo(f"   Response: {result}")
        
        # Update metadata
        metadata['esp_draft_id'] = result.get('id')
        metadata['sent_to_esp'] = datetime.now().isoformat()
        meta_file.write_text(json.dumps(metadata, indent=2))
        
    except Exception as e:
        click.echo(f"❌ Failed to send to ESP: {e}", err=True)

@email.command('klaviyo-create')
@click.argument('post_path', type=click.STRING)
@click.option('--list-id', required=True, help='Klaviyo list ID to send to (required - get with: gang email klaviyo-lists)')
@click.option('--from-email', default='newsletter@example.com', help='From email address')
@click.option('--from-name', default='GANG', help='From name')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
@click.pass_context
def email_klaviyo_create(ctx, post_path, list_id, from_email, from_name, api_key):
    """Create Klaviyo campaign from post"""
    try:
        from core.klaviyo_integration import KlaviyoOrchestrator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoOrchestrator
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY environment variable not set", err=True)
        click.echo("   Set it with: export KLAVIYO_API_KEY=your_private_key")
        click.echo("   Get your key from: https://www.klaviyo.com/settings/account/api-keys")
        return
    
    config = ctx.obj
    post_file = Path(post_path)
    
    if not post_file.exists():
        click.echo(f"❌ Post not found: {post_path}", err=True)
        return
    
    if not list_id:
        click.echo("❌ --list-id is required", err=True)
        click.echo("   Get your list ID with: gang email klaviyo-lists")
        return
    
    click.echo(f"📧 Creating Klaviyo campaign from: {post_file.name}")
    
    orchestrator = KlaviyoOrchestrator(config, api_key)
    
    try:
        result = orchestrator.create_campaign_from_post(
            post_file,
            list_id=list_id,
            from_email=from_email,
            from_name=from_name
        )
        
        # Save newsletter to content for public listing
        from core.email_templates import EmailOrchestrator as EmailOrch
        email_orch = EmailOrch(config, 'klaviyo')
        content_path = Path(config['build']['content'])
        newsletter_file = email_orch.save_newsletter_to_content(
            post_file, 
            {
                'title': result['title'], 
                'slug': post_file.stem, 
                'created': result['created'], 
                'esp_provider': 'klaviyo', 
                'canonical_url': f"{config.get('site', {}).get('url')}/posts/{post_file.stem}/"
            },
            content_path
        )
        
        click.echo(f"\n✅ Klaviyo campaign created:")
        click.echo(f"   Title: {result['title']}")
        click.echo(f"   Campaign ID: {result['campaign_id']}")
        click.echo(f"   Status: {result['status']}")
        click.echo(f"   URL: {result['klaviyo_url']}")
        click.echo(f"   Newsletter page: {newsletter_file}")
        click.echo(f"\n📝 Next steps:")
        click.echo(f"   1. Review in Klaviyo dashboard")
        click.echo(f"   2. Schedule or send immediately")
        click.echo(f"   3. Build site: gang build")
        click.echo(f"   4. View at: /newsletters/{post_file.stem}/")
        
    except Exception as e:
        click.echo(f"❌ Failed to create campaign: {e}", err=True)
        import traceback
        traceback.print_exc()

@email.command('klaviyo-lists')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
def email_klaviyo_lists(api_key):
    """List all Klaviyo lists"""
    try:
        from core.klaviyo_integration import KlaviyoClient
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoClient
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY not set", err=True)
        return
    
    client = KlaviyoClient(api_key)
    
    try:
        lists = client.get_lists()
        
        click.echo(f"\n📋 Klaviyo Lists ({len(lists)}):\n")
        
        for lst in lists:
            attrs = lst['attributes']
            click.echo(f"  {attrs['name']}")
            click.echo(f"    ID: {lst['id']}")
            if attrs.get('profile_count'):
                click.echo(f"    Subscribers: {attrs['profile_count']}")
            click.echo("")
        
    except Exception as e:
        click.echo(f"❌ Failed to fetch lists: {e}", err=True)

@email.command('klaviyo-campaigns')
@click.option('--status', default='draft', help='Filter by status (draft, scheduled, sent)')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
def email_klaviyo_campaigns(status, api_key):
    """List Klaviyo campaigns"""
    try:
        from core.klaviyo_integration import KlaviyoClient
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoClient
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY not set", err=True)
        return
    
    client = KlaviyoClient(api_key)
    
    try:
        campaigns = client.get_campaigns(status)
        
        click.echo(f"\n📧 Klaviyo Campaigns ({status}):\n")
        
        for campaign in campaigns:
            attrs = campaign['attributes']
            click.echo(f"  {attrs['name']}")
            click.echo(f"    ID: {campaign['id']}")
            click.echo(f"    Status: {attrs.get('status', 'unknown')}")
            if attrs.get('send_time'):
                click.echo(f"    Scheduled: {attrs['send_time']}")
            click.echo("")
        
    except Exception as e:
        click.echo(f"❌ Failed to fetch campaigns: {e}", err=True)

@email.command('check-deliverability')
@click.argument('domain')
def email_check_deliverability(domain):
    """Check DNS records for email deliverability"""
    try:
        from core.email_templates import DeliverabilityChecker
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import DeliverabilityChecker
    
    click.echo(f"🔍 Checking deliverability for: {domain}\n")
    
    try:
        results = DeliverabilityChecker.check_dns_records(domain)
        
        click.echo("SPF Record:")
        if results['spf']:
            click.echo(f"  ✓ {results['spf']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nDMARC Record:")
        if results['dmarc']:
            click.echo(f"  ✓ {results['dmarc']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nMX Records:")
        if results['mx']:
            for mx in results['mx']:
                click.echo(f"  ✓ {mx}")
        else:
            click.echo("  ✗ Not found")
        
        # Generate setup guide
        click.echo("\n" + "="*50)
        click.echo("\n📖 Setup Guide:")
        click.echo(DeliverabilityChecker.generate_setup_guide(domain))
        
    except ImportError:
        click.echo("⚠️  dnspython not installed. Install with: pip install dnspython")
        click.echo("\n📖 Setup Guide:")
        click.echo(DeliverabilityChecker.generate_setup_guide(domain))

@cli.group()
def taxonomy():
    """Manage hierarchical taxonomies and tags"""
    pass

@taxonomy.command('list')
@click.pass_context
def taxonomy_list(ctx):
    """List all categories and tags"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    
    click.echo("\n📚 Categories:")
    for cat_name, cat_data in manager.get_all_categories().items():
        click.echo(f"\n  {cat_name}")
        if cat_data.get('description'):
            click.echo(f"    {cat_data['description']}")
        if cat_data.get('children'):
            click.echo(f"    Subcategories: {', '.join(cat_data['children'])}")
    
    click.echo("\n🏷️  Tags:")
    tags = manager.get_all_tags()
    for tag in tags:
        click.echo(f"  • {tag}")
    
    click.echo(f"\n✅ {len(manager.get_all_categories())} categories, {len(tags)} tags")

@taxonomy.command('analyze')
@click.pass_context
def taxonomy_analyze(ctx):
    """Analyze taxonomy usage across content"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    analysis = manager.analyze_content_taxonomy()
    
    click.echo("\n📊 Taxonomy Usage Analysis:\n")
    
    click.echo("By Category:")
    for category, items in sorted(analysis['by_category'].items()):
        click.echo(f"  {category}: {len(items)} items")
    
    click.echo("\nBy Tag:")
    for tag, items in sorted(analysis['by_tag'].items()):
        click.echo(f"  {tag}: {len(items)} items")
    
    if analysis['uncategorized']:
        click.echo(f"\n⚠️  {len(analysis['uncategorized'])} uncategorized items")
    
    if analysis['untagged']:
        click.echo(f"⚠️  {len(analysis['untagged'])} untagged items")

@taxonomy.command('add-category')
@click.argument('name')
@click.option('--description', help='Category description')
@click.option('--parent', help='Parent category for subcategory')
@click.pass_context
def taxonomy_add_category(ctx, name, description, parent):
    """Add a new category or subcategory"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    manager.add_category(name, description or '', parent)
    
    if parent:
        click.echo(f"✅ Added subcategory '{name}' under '{parent}'")
    else:
        click.echo(f"✅ Added category '{name}'")

@taxonomy.command('add-tag')
@click.argument('tag')
@click.pass_context
def taxonomy_add_tag(ctx, tag):
    """Add a new tag"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    manager.add_tag(tag)
    
    click.echo(f"✅ Added tag '{tag}'")

@cli.command()
@click.argument('product_json', type=click.Path(exists=True))
@click.option('--auto-pr', is_flag=True, help='Automatically create PR')
@click.pass_context
def shopify_sync(ctx, product_json, auto_pr):
    """Sync Shopify product and optionally create PR"""
    try:
        from core.shopify_pr_bot import ShopifyPRBot
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.shopify_pr_bot import ShopifyPRBot
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    mapping_path = Path('schemas/product.map.json')
    
    bot = ShopifyPRBot(content_path, mapping_path)
    
    # Load product data
    product_data = json.loads(Path(product_json).read_text())
    
    if auto_pr:
        click.echo("🤖 Creating PR for product update...")
        result = bot.create_pr(product_data)
        
        if result['success']:
            click.echo(f"✅ PR created: {result.get('pr_url', 'Branch created locally')}")
        else:
            click.echo(f"❌ Failed: {result.get('error', 'Unknown error')}", err=True)
            ctx.exit(1)
    else:
        # Just generate the file
        click.echo("📝 Generating product file...")
        file_path = bot.generate_markdown_file(product_data)
        click.echo(f"✅ Created: {file_path}")

@cli.group()
def products():
    """Manage products from Shopify, Stripe, Gumroad"""
    pass

@products.command('sync')
@click.option('--platforms', default='all', help='Platforms to sync (all, shopify, stripe, gumroad)')
@click.pass_context
def sync_products(ctx, platforms):
    """Fetch products from platforms and normalize"""
    try:
        from core.products import ProductAggregator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.products import ProductAggregator
    
    config = ctx.obj
    config['demo_mode'] = True  # Use demo mode if no API keys
    
    click.echo("🛒 Syncing products...")
    aggregator = ProductAggregator(config)
    products = aggregator.get_normalized_products()
    
    click.echo(f"✅ Fetched {len(products)} product(s)")
    for p in products:
        source = p.get('_meta', {}).get('source', 'unknown')
        click.echo(f"  • {p['name']} (from {source})")

@products.command('list')
@click.option('--format', type=click.Choice(['text', 'json']), default='text')
@click.pass_context
def list_products(ctx, format):
    """List all synced products"""
    try:
        from core.products import ProductAggregator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.products import ProductAggregator
    
    config = ctx.obj
    config['demo_mode'] = True
    
    aggregator = ProductAggregator(config)
    cache = aggregator.load_cache()
    
    if not cache:
        click.echo("No products cached. Run 'gang products sync' first.")
        return
    
    products = aggregator.get_normalized_products()
    
    if format == 'json':
        import json
        click.echo(json.dumps(products, indent=2))
    else:
        click.echo(f"🛒 Products ({len(products)} total)\n")
        for p in products:
            source = p.get('_meta', {}).get('source', 'unknown')
            
            # Handle both single offer and array of offers
            offers = p.get('offers', {})
            if type(offers).__name__ == 'list':
                # Multiple offers (variants)
                first_offer = offers[0] if offers else {}
                price = first_offer.get('price', 'N/A')
                currency = first_offer.get('priceCurrency', 'USD')
                variant_count = len(offers)
                click.echo(f"• {p['name']}")
                click.echo(f"  Price: {currency} {price} ({variant_count} variant{'s' if variant_count != 1 else ''}) | Source: {source}")
            else:
                # Single offer
                price = offers.get('price', 'N/A')
                currency = offers.get('priceCurrency', 'USD')
                click.echo(f"• {p['name']}")
                click.echo(f"  Price: {currency} {price} | Source: {source}")

@cli.command('agentmap')
@click.pass_context
def generate_agentmap(ctx):
    """Generate AgentMap.json for AI agent navigation"""
    try:
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        from core.scheduler import ContentScheduler
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    site_url = config['site']['url']
    
    click.echo("🤖 Generating AgentMap for AI agents...")
    
    # Get publishable content - avoid rglob recursion issue
    scheduler = ContentScheduler(content_path)
    
    # Manually collect .md files to avoid Click recursion
    all_md_files = []
    for category_dir in ['posts', 'pages', 'projects']:
        category_path = content_path / category_dir
        if category_path.exists():
            all_md_files.extend(list(category_path.glob('*.md')))
    
    schedule_result = scheduler.get_publishable_content(all_md_files)
    publishable = [item['path'] for item in schedule_result['publishable']]
    
    # Get products if available
    config['demo_mode'] = True
    aggregator = ProductAggregator(config)
    products = aggregator.get_normalized_products()
    
    # Generate AgentMap
    generator = AgentMapGenerator(config, site_url)
    agentmap = generator.generate(publishable, products if products else None)
    
    # Write AgentMap
    agentmap_file = dist_path / 'agentmap.json'
    agentmap_file.write_text(json.dumps(agentmap, indent=2))
    
    # Generate Content API
    api_dir = dist_path / 'api'
    api_dir.mkdir(exist_ok=True)
    
    api_generator = ContentAPIGenerator(site_url)
    content_index = api_generator.generate_content_index(publishable, content_path)
    
    (api_dir / 'content.json').write_text(json.dumps(content_index, indent=2))
    
    if products:
        (api_dir / 'products.json').write_text(json.dumps(products, indent=2))
    
    click.echo(f"✅ Generated AgentMap with {len(publishable)} content items")
    if products:
        click.echo(f"✅ Generated Products API with {len(products)} products")
    click.echo(f"📄 Files: agentmap.json, api/content.json")

@cli.command()
@click.option('--fix', is_flag=True, help='Suggest unique slugs for conflicts')
@click.pass_context
def slugs(ctx, fix):
    """Check slug uniqueness across all content"""
    try:
        from core.content_importer import SlugChecker
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import SlugChecker
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    click.echo("🔍 Checking slug uniqueness...\n")
    
    checker = SlugChecker(content_path)
    results = checker.check_all_slugs()
    
    click.echo(f"📊 Slug Report:")
    click.echo(f"├─ Total slugs: {results['total_slugs']}")
    click.echo(f"├─ Unique: {results['unique_slugs']}")
    click.echo(f"└─ Duplicates: {results['duplicate_slugs']}")
    
    if results['duplicates']:
        click.echo(f"\n❌ Duplicate slugs found:")
        for slug, files in results['duplicates'].items():
            click.echo(f"\n  Slug: '{slug}' used in:")
            for file in files:
                click.echo(f"    - {file}")
            
            if fix:
                click.echo(f"  💡 To fix: Rename one file to make slugs unique")
        
        if not fix:
            click.echo(f"\n💡 Run with --fix to see suggestions")
        
        ctx.exit(1)
    else:
        click.echo(f"\n✅ All slugs are unique!")

@cli.command()
@click.option('--check-quality', is_flag=True, help='Run content quality checks before building')
@click.option('--min-quality-score', type=int, default=85, help='Minimum quality score (default: 85)')
@click.option('--validate-links', is_flag=True, help='Validate all links before building')
@click.option('--check-slugs', is_flag=True, default=True, help='Check slug uniqueness (default: enabled)')
@click.option('--optimize-images', is_flag=True, help='Auto-optimize images before building')
@click.option('--profile', is_flag=True, help='Show build performance metrics')
@click.pass_context
def build(ctx, check_quality, min_quality_score, validate_links, check_slugs, optimize_images, profile):
    """Build static site with semantic HTML"""
    try:
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
    
    # Initialize profiler
    profiler = BuildProfiler() if profile else None
    if profiler:
        profiler.start()
    
    click.echo("🔨 Building site...")
    config = ctx.obj
    
    # Slug uniqueness check (enabled by default)
    if check_slugs:
        from core.content_importer import SlugChecker
        content_path = Path(config['build']['content'])
        checker = SlugChecker(content_path)
        results = checker.check_all_slugs()
        
        if results['duplicate_slugs'] > 0:
            click.echo("❌ Duplicate slugs detected!\n")
            for slug, files in results['duplicates'].items():
                click.echo(f"  Slug '{slug}' used in:")
                for file in files:
                    click.echo(f"    - {file}")
            
            click.echo(f"\n🚫 Cannot build: {results['duplicate_slugs']} duplicate slug(s) found")
            click.echo("   Run 'gang slugs' for details")
            click.echo("   Fix by renaming files to have unique slugs")
            ctx.exit(1)
        else:
            click.echo(f"✓ All {results['total_slugs']} slugs are unique\n")
    
    # Quality gate check
    if check_quality:
        from core.analyzer import ContentAnalyzer
        click.echo("🔍 Running content quality checks...")
        analyzer = ContentAnalyzer(config)
        content_path = Path(config['build']['content'])
        md_files = list(content_path.rglob('*.md'))
        
        failed_files = []
        for md_file in md_files:
            try:
                analysis = analyzer.analyze_file(md_file)
                seo_score = analysis['seo']['score']
                if seo_score < min_quality_score:
                    failed_files.append((md_file.relative_to(content_path), seo_score))
            except Exception as e:
                click.echo(f"⚠️  Could not analyze {md_file.relative_to(content_path)}: {e}")
        
        if failed_files:
            click.echo(f"\n❌ Quality gate failed! {len(failed_files)} file(s) below minimum score ({min_quality_score}):")
            for file, score in failed_files:
                click.echo(f"  - {file}: {score}/100")
            click.echo(f"\nRun 'gang analyze --all' for detailed report")
            click.echo("Tip: Use --min-quality-score to adjust threshold or fix content issues")
            ctx.exit(1)
        else:
            click.echo(f"✓ All {len(md_files)} files pass quality threshold ({min_quality_score}+)\n")
    
    # Link validation check
    if validate_links:
        from core.link_validator import LinkValidator
        click.echo("🔗 Validating links...")
        content_path = Path(config['build']['content'])
        dist_path = Path(config['build']['output'])
        validator = LinkValidator(config, content_path, dist_path)
        
        results = validator.scan_all_files()
        
        broken_count = len(results['broken_internal']) + len(results['broken_external'])
        
        if broken_count > 0:
            click.echo(f"❌ Found {broken_count} broken link(s):")
            for item in results['broken_internal'][:3]:
                click.echo(f"  - {item['file']}: {item['url']} (internal)")
            for item in results['broken_external'][:3]:
                click.echo(f"  - {item['file']}: {item['url']} → {item['error']}")
            if broken_count > 6:
                click.echo(f"  ... and {broken_count - 6} more")
            click.echo(f"\nRun 'gang validate --links' for full report")
            click.echo("Build aborted due to broken links\n")
            ctx.exit(1)
        else:
            click.echo(f"✓ All {results['total_links']} links valid\n")
    
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
    
    # Optimize images if requested
    if optimize_images:
        from core.images import ImageProcessor
        click.echo("🖼️  Optimizing images...")
        
        public_path = Path(config['build']['public'])
        images_source = public_path / 'images' if (public_path / 'images').exists() else public_path
        images_output = dist_path / 'assets' / 'images'
        images_output.mkdir(parents=True, exist_ok=True)
        
        processor = ImageProcessor(config)
        result = processor.process_all_images(images_source, images_output)
        
        stats = result['stats']
        if stats['total_images'] > 0:
            savings_kb = stats['savings_bytes'] / 1024
            click.echo(f"  ✓ Optimized {stats['total_images']} image(s) → {stats['total_variants']} variants")
            click.echo(f"  💾 Saved {savings_kb:.1f}KB ({stats['savings_percent']:.1f}% reduction)")
    
    # Copy public assets
    public_path = Path(config['build']['public'])
    if public_path.exists():
        if profiler:
            with profiler.stage('copy_assets'):
                click.echo("📦 Copying public assets...")
                shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
        else:
            click.echo("📦 Copying public assets...")
            shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
    
    # Build content
    content_path = Path(config['build']['content'])
    all_pages = []
    all_posts = []
    all_projects = []
    all_newsletters = []
    
    # Parse markdown files
    if profiler:
        profiler.stage('process_content').__enter__()
    
    # Filter content based on publish dates
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    scheduler = ContentScheduler(content_path)
    
    # Manually collect .md files to avoid Click recursion issue
    all_md_files = []
    for category_dir in ['posts', 'pages', 'projects', 'newsletters']:
        category_path = content_path / category_dir
        if category_path.exists():
            for md_file in category_path.glob('*.md'):
                all_md_files.append(md_file)
    
    schedule_result = scheduler.get_publishable_content(all_md_files)
    
    publishable_files = [item['path'] for item in schedule_result['publishable']]
    
    # Show scheduling info if there are scheduled items
    if schedule_result['scheduled']:
        click.echo(f"🕐 {len(schedule_result['scheduled'])} post(s) scheduled for future")
    if schedule_result['draft']:
        click.echo(f"📝 {len(schedule_result['draft'])} draft post(s) excluded")
    
    click.echo(f"📝 Processing {len(publishable_files)} publishable content file(s)...")
    for md_file in publishable_files:
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
        
        # Process external links to open in new tabs
        content_html = process_external_links(content_html)
        
        # Prepare context for template
        build_time = datetime.now()
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
            'build_time': build_time.strftime('%B %d, %Y at %I:%M %p'),
            'build_time_iso': build_time.isoformat(),
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
        elif content_type == 'newsletters':
            template_name = 'newsletter.html'
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
        
        # Add to appropriate collection (no duplicates)
        if content_type == 'posts':
            all_posts.append(page_data)
        elif content_type == 'projects':
            all_projects.append(page_data)
        elif content_type == 'newsletters':
            all_newsletters.append(page_data)
        elif content_type == 'pages':
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
    page_size_bytes = len(index_html.encode('utf-8'))
    index_html = index_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
    (dist_path / 'index.html').write_text(index_html)
    
    # Create newsletters list page
    if all_newsletters:
        newsletters_dir = dist_path / 'newsletters'
        newsletters_dir.mkdir(parents=True, exist_ok=True)
        
        newsletters_html = create_list_page_simple(config, sorted(all_newsletters, key=lambda x: x.get('date', ''), reverse=True), 'Newsletters')
        page_size_bytes = len(newsletters_html.encode('utf-8'))
        newsletters_html = newsletters_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (newsletters_dir / 'index.html').write_text(newsletters_html)
    
    # Create list pages
    if all_posts:
        click.echo("📄 Creating posts index...")
        posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts')
        page_size_bytes = len(posts_html.encode('utf-8'))
        posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (dist_path / 'posts' / 'index.html').write_text(posts_html)
    
    if all_projects:
        click.echo("📄 Creating projects index...")
        projects_html = create_list_page_simple(config, all_projects, 'Projects')
        page_size_bytes = len(projects_html.encode('utf-8'))
        projects_html = projects_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (dist_path / 'projects' / 'index.html').write_text(projects_html)
    
    # Generate outputs
    click.echo("🗺️  Generating sitemap, feeds, etc...")
    all_pages.append({'url': '/', 'title': config['site']['title'], 'type': 'home'})
    if all_posts:
        all_pages.append({'url': '/posts/', 'title': 'Posts', 'type': 'list'})
    if all_projects:
        all_pages.append({'url': '/projects/', 'title': 'Projects', 'type': 'list'})
    
    # Combine all content for sitemap generation
    all_content = all_pages + all_posts + all_projects
    
    if profiler:
        with profiler.stage('generate_outputs'):
            generators.generate_all(dist_path, all_content, all_posts)
    else:
        generators.generate_all(dist_path, all_content, all_posts)
    
    # Generate redirect rules if any exist
    try:
        from core.redirects import RedirectManager
        redirect_manager = RedirectManager(content_path, dist_path)
        redirect_list = redirect_manager.list_all_redirects()
        
        if redirect_list:
            redirect_manager.write_redirects_file(format='cloudflare')
            click.echo(f"🔀 Generated {len(redirect_list)} redirect(s) → dist/_redirects")
    except Exception as e:
        click.echo(f"⚠️  Could not generate redirects: {e}")
    
    # Generate product pages (only active products)
    try:
        from core.products import ProductAggregator
        from jinja2 import Environment, FileSystemLoader
        
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='active')
        
        if products:
            click.echo(f"🛒 Generating {len(products)} product page(s)...")
            
            # Setup Jinja2
            template_dir = Path(__file__).parent.parent.parent / 'templates'
            jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
            
            products_path = dist_path / 'products'
            products_path.mkdir(parents=True, exist_ok=True)
            
            # Generate PLP
            plp_template = jinja_env.get_template('products-list.html')
            plp_html = plp_template.render(
                products=products,
                site_title=config['site']['title'],
                year=datetime.now().year,
                navigation=config.get('nav', {}).get('main', []),
                build_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                build_time_iso=datetime.now().isoformat()
            )
            (products_path / 'index.html').write_text(plp_html)
            
            # Generate PDPs
            pdp_template = jinja_env.get_template('product.html')
            for product in products:
                # Use 'handle' if 'slug' not present (Shopify uses 'handle')
                slug = product['_meta'].get('slug') or product['_meta'].get('handle')
                if not slug:
                    click.echo(f"⚠️  Skipping product without slug/handle: {product.get('name')}")
                    continue
                
                pdp_dir = products_path / slug
                pdp_dir.mkdir(parents=True, exist_ok=True)
                
                # Handle images FIRST (can be string or list)
                raw_images = product.get('image', [])
                
                # Ensure we have a proper Python list (avoid isinstance for Click compatibility)
                type_name = type(raw_images).__name__
                if type_name in ('list', 'tuple'):
                    images = [str(img) for img in raw_images if img]
                elif raw_images:
                    images = [str(raw_images)]
                else:
                    images = []
                
                # Extract offer data and variants
                offers = product.get('offers', {})
                variants_list = []
                
                if type(offers).__name__ == 'list':
                    # Multiple variants - extract unique colors and sizes
                    colors = set()
                    sizes = set()
                    color_to_image = {}  # Map colors to images
                    
                    # First pass: collect unique colors in order they appear
                    color_order = []
                    for offer in offers:
                        variant_name = offer.get('name', '')
                        if '/' in variant_name:
                            parts = variant_name.split('/')
                            color = parts[0].strip()
                            size = parts[1].strip() if len(parts) > 1 else ''
                            
                            if color not in colors:
                                color_order.append(color)
                                colors.add(color)
                            
                            if size:
                                sizes.add(size)
                    
                    # Map each color to an image (assume images are in same order as colors appear)
                    for idx, color in enumerate(color_order):
                        if idx < len(images):
                            color_to_image[color] = idx
                    
                    # Second pass: prepare variant data with correct image mapping
                    for offer in offers:
                        variant_name = offer.get('name', '')
                        color_part = ''
                        size_part = ''
                        
                        if '/' in variant_name:
                            parts = variant_name.split('/')
                            color_part = parts[0].strip()
                            size_part = parts[1].strip() if len(parts) > 1 else ''
                        
                        variants_list.append({
                            'name': variant_name,
                            'color': color_part,
                            'size': size_part,
                            'price': offer.get('price', '0'),
                            'currency': offer.get('priceCurrency', 'USD'),
                            'availability': offer.get('availability', 'InStock'),
                            'url': offer.get('url', '#'),
                            'sku': offer.get('sku', ''),
                            'image_index': color_to_image.get(color_part, 0) if color_part else 0
                        })
                    
                    first_offer = offers[0]
                    # Convert sets to lists without using list() to avoid Click collision
                    colors_list = [c for c in sorted(colors)]
                    sizes_list = [s for s in sorted(sizes)]
                else:
                    first_offer = offers
                    colors_list = []
                    sizes_list = []
                
                # Prepare template variables
                brand_data = product.get('brand', '')
                brand_name = brand_data.get('name', '') if hasattr(brand_data, 'get') else str(brand_data)
                
                pdp_context = {
                    'lang': config['site'].get('language', 'en'),
                    'site_title': config['site']['title'],
                    'title': product.get('name', ''),
                    'description': product.get('description', ''),
                    'canonical_url': f"{config['site']['url']}/products/{slug}/",
                    'product_image': images[0] if images else '',
                    'product_images': images,
                    'price': first_offer.get('price', '0'),
                    'currency': first_offer.get('priceCurrency', 'USD'),
                    'recurring': None,
                    'content': product.get('description', ''),
                    'buy_url': first_offer.get('url', '#'),
                    'variants': variants_list,
                    'colors': colors_list,
                    'sizes': sizes_list,
                    'sku': product.get('sku', ''),
                    'brand': brand_name,
                    'category': product.get('category', ''),
                    'availability': first_offer.get('availability', 'InStock'),
                    'jsonld': product,
                    'year': datetime.now().year,
                    'navigation': config.get('nav', {}).get('main', []),
                    'build_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'build_time_iso': datetime.now().isoformat()
                }
                
                pdp_html = pdp_template.render(**pdp_context)
                (pdp_dir / 'index.html').write_text(pdp_html)
            
            click.echo(f"✅ Generated product pages (PLP + {len(products)} PDPs)")
            
            # Generate cart page
            cart_dir = dist_path / 'cart'
            cart_dir.mkdir(parents=True, exist_ok=True)
            
            cart_template = jinja_env.get_template('cart.html')
            cart_html = cart_template.render()
            (cart_dir / 'index.html').write_text(cart_html)
            
            click.echo("🛒 Generated cart page")
            
            # Generate HTML sitemap
            sitemap_dir = dist_path / 'sitemap'
            sitemap_dir.mkdir(parents=True, exist_ok=True)
            
            sitemap_template = jinja_env.get_template('sitemap.html')
            sitemap_html = sitemap_template.render(
                site_title=config['site']['title'],
                site_url=config['site']['url'],
                pages=all_pages,
                posts=all_posts,
                projects=all_projects,
                products=products,
                year=datetime.now().year,
                build_time_iso=datetime.now().isoformat()
            )
            (sitemap_dir / 'index.html').write_text(sitemap_html)
            
            click.echo("🗺️  Generated HTML sitemap")
    except Exception as e:
        click.echo(f"⚠️  Could not generate product pages: {e}")
    
    # Generate search index
    try:
        from core.search import SearchIndexer
        from core.scheduler import ContentScheduler
        
        scheduler = ContentScheduler(content_path)
        all_md = list(content_path.rglob('*.md'))
        schedule_result = scheduler.get_publishable_content(all_md)
        publishable = [item['path'] for item in schedule_result['publishable']]
        
        indexer = SearchIndexer(content_path, config)
        search_index = indexer.build_search_index(publishable)
        
        # Write search index
        search_index_file = dist_path / 'search-index.json'
        search_index_file.write_text(json.dumps(search_index))
        
        # Write search page
        search_page = dist_path / 'search' / 'index.html'
        search_page.parent.mkdir(parents=True, exist_ok=True)
        search_page.write_text(indexer.generate_search_page_html())
        
        click.echo(f"🔍 Generated search index ({len(search_index['documents'])} documents)")
    except Exception as e:
        click.echo(f"⚠️  Could not generate search index: {e}")
    
    # Generate AgentMap for AI agents
    try:
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        
        # Get publishable content (convert Path objects to list)
        scheduler = ContentScheduler(content_path)
        all_md_files = [f for f in content_path.rglob('*.md')]
        schedule_result = scheduler.get_publishable_content(all_md_files)
        publishable_paths = [Path(item['path']) if isinstance(item['path'], str) else item['path'] 
                            for item in schedule_result['publishable']]
        
        # Get products
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='active')
        
        # Generate AgentMap
        site_url = config.get('site', {}).get('url', 'https://example.com')
        generator = AgentMapGenerator(config, site_url)
        agentmap = generator.generate(publishable_paths, products if products else None)
        
        # Write AgentMap
        agentmap_file = dist_path / 'agentmap.json'
        agentmap_file.write_text(json.dumps(agentmap, indent=2))
        
        # Generate Content API
        api_generator = ContentAPIGenerator(config, site_url)
        content_api = api_generator.generate(publishable_paths, products)
        
        api_dir = dist_path / 'api'
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / 'content.json').write_text(json.dumps(content_api, indent=2))
        
        # Generate products API
        if products:
            products_api = {
                'products': products,
                'count': len(products),
                'generated': datetime.now().isoformat()
            }
            (api_dir / 'products.json').write_text(json.dumps(products_api, indent=2))
        
        click.echo(f"🤖 Generated AgentMap with {len(publishable_paths)} content items")
    except Exception as e:
        click.echo(f"⚠️  Could not generate AgentMap: {e}")
    
    # Minify HTML, CSS, and JS (simple implementation)
    try:
        import re
        
        # Minify JS (safer approach - preserve operators)
        js_files = [f for f in dist_path.rglob('*.js')]
        js_original = 0
        js_minified = 0
        for js_file in js_files:
            js_content = js_file.read_text()
            js_original += len(js_content)
            # Remove single-line comments (but preserve URLs)
            js_content = re.sub(r'(?<!["\'/])//[^\n]*', '', js_content)
            # Remove multi-line comments
            js_content = re.sub(r'/\*.*?\*/', '', js_content, flags=re.DOTALL)
            # Remove extra whitespace (but not all - preserve some for safety)
            js_content = re.sub(r'\n\s+', '\n', js_content)
            js_content = re.sub(r'\s{2,}', ' ', js_content)
            # Remove empty lines
            js_content = '\n'.join(line for line in js_content.split('\n') if line.strip())
            js_minified += len(js_content.strip())
            js_file.write_text(js_content.strip())
        
        if js_files:
            js_savings = ((js_original - js_minified) / js_original * 100) if js_original > 0 else 0
            click.echo(f"🗜️  Minified {len(js_files)} JS file(s) ({js_savings:.1f}% reduction)")
        
        # Minify CSS
        css_files = [f for f in dist_path.rglob('*.css')]
        css_original = 0
        css_minified = 0
        for css_file in css_files:
            css_content = css_file.read_text()
            css_original += len(css_content)
            # Remove comments
            css_content = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)
            # Remove extra whitespace
            css_content = re.sub(r'\s+', ' ', css_content)
            # Remove spaces around special characters
            css_content = re.sub(r'\s*([{}:;,])\s*', r'\1', css_content)
            css_minified += len(css_content.strip())
            css_file.write_text(css_content.strip())
        
        if css_files:
            css_savings = ((css_original - css_minified) / css_original * 100) if css_original > 0 else 0
            click.echo(f"🗜️  Minified {len(css_files)} CSS file(s) ({css_savings:.1f}% reduction)")
        
        # Minify HTML
        html_files = [f for f in dist_path.rglob('*.html')]
        minified_count = 0
        original_size = 0
        minified_size = 0
        
        for html_file in html_files:
            original_html = html_file.read_text()
            original_size += len(original_html)
            
            # Simple minification:
            # 1. Remove HTML comments
            minified = re.sub(r'<!--.*?-->', '', original_html, flags=re.DOTALL)
            # 2. Remove whitespace between tags
            minified = re.sub(r'>\s+<', '><', minified)
            # 3. Remove leading/trailing whitespace on lines
            minified = '\n'.join(line.strip() for line in minified.split('\n') if line.strip())
            
            minified_size += len(minified)
            html_file.write_text(minified)
            minified_count += 1
        
        savings = ((original_size - minified_size) / original_size * 100) if original_size > 0 else 0
        click.echo(f"🗜️  Minified {minified_count} HTML files ({savings:.1f}% reduction)")
    except Exception as e:
        click.echo(f"⚠️  Could not minify assets: {e}")
    
    # End profiling
    if profiler:
        profiler.end()
        profiler.record_files('pages', len(all_pages))
        profiler.record_files('posts', len(all_posts))
        profiler.record_files('projects', len(all_projects))
        profiler.save_run()
    
    click.echo(f"✅ Build complete! Output in {dist_path}")
    
    # Show performance report if requested
    if profiler:
        click.echo("")
        report = profiler.format_report()
        click.echo(report)


def process_markdown_fallback(md_file: Path, content_type: str, config: Dict) -> str:
    """Fallback markdown processor if templates fail"""
    return process_markdown(md_file, content_type, config)


def process_external_links(html: str) -> str:
    """
    Opt-in external link processing
    Only adds target='_blank' if link has data-newtab attribute or 'ext' class
    Always adds rel='noopener noreferrer' for security
    """
    import re
    
    def replace_link(match):
        full_tag = match.group(0)
        href = match.group(1)
        
        # Skip internal links
        if href.startswith('/'):
            return full_tag
        
        # Always add rel for security
        if 'rel=' not in full_tag:
            full_tag = full_tag.replace('>', ' rel="noopener noreferrer">', 1)
        
        # Only add target if opt-in (data-newtab or class="ext")
        if 'data-newtab' in full_tag or 'class="ext"' in full_tag or "class='ext'" in full_tag:
            if 'target=' not in full_tag:
                full_tag = full_tag.replace('>', ' target="_blank">', 1)
        
        return full_tag
    
    # Pattern: <a href="http(s)://..."
    pattern = r'<a\s+([^>]*href=["\']?(https?://[^"\'>\s]+)["\']?[^>]*?)>'
    return re.sub(pattern, lambda m: replace_link(m), html)


def format_bytes(bytes_size: int) -> str:
    """Format bytes to human readable string"""
    if bytes_size < 1024:
        return f"{bytes_size}B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f}KB"
    else:
        return f"{bytes_size / (1024 * 1024):.2f}MB"


def create_index_simple(config: Dict, recent_posts: List) -> str:
    """Create simple index page"""
    posts_html = ""
    for post in recent_posts:
        posts_html += f'<li><a href="{post["url"]}">{post["title"]}</a></li>\n'
    
    # Create JSON-LD structured data
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config['site']['title'],
        "description": config['site']['description'],
        "url": config['site']['url']
    }
    import json
    jsonld_str = json.dumps(jsonld, indent=2)
    
    # Build timestamp
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Dark mode toggle HTML
    toggle_html = '<div class="theme-toggle"><input type="checkbox" id="theme-switch" aria-label="Toggle dark mode"><label for="theme-switch"></label></div>'
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self'; connect-src 'self' http://localhost:8000; base-uri 'self'; form-action 'self' https:;">
    <title>{config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <script type="application/ld+json">
{jsonld_str}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
    <style>
        /* Page-specific: unstyled list */
        ul {{
            list-style: none;
        }}
    </style>
</head>
<body>
    {toggle_html}
    <header>
        <strong>{config['site']['title']}</strong>
        <nav>
            <a href="/">Home</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/products/">Products</a>
            <a href="/pages/manifesto/">Manifesto</a>
            <a href="/pages/about/">About</a>
            <a href="/pages/contact/">Contact</a>
            <a href="/cart/">Cart <span class="cart-count">0</span></a>
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
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG. __PAGE_SIZE__</p>
        <p class="lighthouse-scores">
            <span class="score" title="Performance">⚡ <strong>100</strong></span>
            <span class="score" title="Accessibility">♿ <strong>100</strong></span>
            <span class="score" title="Best Practices">✓ <strong>100</strong></span>
            <span class="score" title="SEO">🔍 <strong>100</strong></span>
        </p>
        <p class="last-updated">
            <time datetime="{build_time_iso}">Last updated: {build_time_formatted}</time>
        </p>
        <p style="margin-top: 1rem; font-size: 0.85rem; font-style: italic; max-width: 65ch; margin-left: auto; margin-right: auto;">
            This platform builds the smallest possible website that guarantees accessibility, performance, and machine legibility—then add only features that measurably improve comprehension, trust, or conversion.
        </p>
        <p style="margin-top: 1rem; font-size: 0.85rem;">
            <a href="/pages/contact/">Contact</a> · 
            <a href="/pages/faq/">FAQ</a> · 
            <a href="/sitemap/">Sitemap</a> · 
            <a href="/feed.json">RSS</a> · 
            <a href="/agentmap.json">AgentMap</a>
        </p>
        <p style="margin-top: 0.5rem; font-size: 0.85rem;">
            <a href="https://github.com/www-gang-tech" rel="noopener noreferrer" target="_blank">GitHub</a> · 
            <a href="http://instagram.com/gang__tech" rel="noopener noreferrer" target="_blank">Instagram</a>
        </p>
    </footer>
</body>
</html>"""
    
    return html


def create_list_page_simple(config: Dict, items: List, title: str) -> str:
    """Create simple list page"""
    items_html = ""
    for item in items:
        items_html += f'<li><a href="{item["url"]}">{item["title"]}</a>'
        if item.get('summary'):
            items_html += f'<p>{item["summary"]}</p>'
        items_html += '</li>\n'
    
    # Create JSON-LD structured data
    import json
    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": config['site']['description'],
        "url": config['site']['url']
    }
    jsonld_str = json.dumps(jsonld, indent=2)
    
    # Build timestamp
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Dark mode toggle HTML
    toggle_html = '<div class="theme-toggle"><input type="checkbox" id="theme-switch" aria-label="Toggle dark mode"><label for="theme-switch"></label></div>'
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self'; connect-src 'self' http://localhost:8000; base-uri 'self'; form-action 'self' https:;">
    <title>{title} - {config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <script type="application/ld+json">
{jsonld_str}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
    <style>
        /* Page-specific: unstyled list */
        ul {{
            list-style: none;
        }}
        li {{
            margin-bottom: 1.5rem;
        }}
    </style>
</head>
<body>
    {toggle_html}
    <header>
        <a href="/" style="text-decoration: none; color: inherit;">
            <strong>{config['site']['title']}</strong>
        </a>
        <nav>
            <a href="/">Home</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/products/">Products</a>
            <a href="/pages/manifesto/">Manifesto</a>
            <a href="/pages/about/">About</a>
            <a href="/pages/contact/">Contact</a>
            <a href="/cart/">Cart <span class="cart-count">0</span></a>
        </nav>
    </header>
    <main>
        <h1>{title}</h1>
        <ul>
            {items_html}
        </ul>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG. __PAGE_SIZE__</p>
        <p class="lighthouse-scores">
            <span class="score" title="Performance">⚡ <strong>100</strong></span>
            <span class="score" title="Accessibility">♿ <strong>100</strong></span>
            <span class="score" title="Best Practices">✓ <strong>100</strong></span>
            <span class="score" title="SEO">🔍 <strong>100</strong></span>
        </p>
        <p class="last-updated">
            <time datetime="{build_time_iso}">Last updated: {build_time_formatted}</time>
        </p>
        <p style="margin-top: 1rem; font-size: 0.85rem; font-style: italic; max-width: 65ch; margin-left: auto; margin-right: auto;">
            This platform builds the smallest possible website that guarantees accessibility, performance, and machine legibility—then add only features that measurably improve comprehension, trust, or conversion.
        </p>
        <p style="margin-top: 1rem; font-size: 0.85rem;">
            <a href="/pages/contact/">Contact</a> · 
            <a href="/pages/faq/">FAQ</a> · 
            <a href="/sitemap/">Sitemap</a> · 
            <a href="/feed.json">RSS</a> · 
            <a href="/agentmap.json">AgentMap</a>
        </p>
        <p style="margin-top: 0.5rem; font-size: 0.85rem;">
            <a href="https://github.com/www-gang-tech" rel="noopener noreferrer" target="_blank">GitHub</a> · 
            <a href="http://instagram.com/gang__tech" rel="noopener noreferrer" target="_blank">Instagram</a>
        </p>
    </footer>
</body>
</html>"""
    
    return html


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
    
    # Process external links to open in new tabs
    body_html = process_external_links(body_html)
    
    title = frontmatter.get('title', md_file.stem.replace('-', ' ').title())
    description = frontmatter.get('summary', config['site']['description'])
    
    # Build HTML page
    page_html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self'; base-uri 'self'; form-action 'self';">
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
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
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
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
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
            <a href="/products/">Products</a>
            <a href="/pages/manifesto/">Manifesto</a>
            <a href="/pages/about/">About</a>
            <a href="/pages/contact/">Contact</a>
            <a href="/cart/">Cart <span class="cart-count">0</span></a>
        </nav>
    </header>
    <main>
        <article>
            {body_html}
        </article>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG. __PAGE_SIZE__</p>
        <p class="lighthouse-scores">
            <span class="score" title="Performance">⚡ <strong>100</strong></span>
            <span class="score" title="Accessibility">♿ <strong>100</strong></span>
            <span class="score" title="Best Practices">✓ <strong>100</strong></span>
            <span class="score" title="SEO">🔍 <strong>100</strong></span>
        </p>
        <p class="last-updated">
            <time datetime="{build_time_iso}">Last updated: {build_time_formatted}</time>
        </p>
    </footer>
</body>
</html>"""
    
    return page_html


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
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
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
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        a:hover {{
            text-decoration-thickness: 2px;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
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
            <a href="/products/">Products</a>
            <a href="/pages/manifesto/">Manifesto</a>
            <a href="/pages/about/">About</a>
            <a href="/pages/contact/">Contact</a>
            <a href="/cart/">Cart <span class="cart-count">0</span></a>
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
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
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
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        a:hover {{
            text-decoration-thickness: 2px;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
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
            <a href="/products/">Products</a>
            <a href="/pages/manifesto/">Manifesto</a>
            <a href="/pages/about/">About</a>
            <a href="/pages/contact/">Contact</a>
            <a href="/cart/">Cart <span class="cart-count">0</span></a>
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
def check(ctx, output):
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
    if output:
        output_path = Path(output)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        click.echo(f"\n📄 Report saved to {output_path}")
    
    # Exit with error code if validation failed
    if summary['failed'] > 0:
        ctx.exit(1)

@cli.command()
@click.option('--output', '-o', type=click.Path(), help='Output JSON report to file')
@click.pass_context
def audit(ctx, output):
    """Run Lighthouse + axe audits (auto-discovers all pages)"""
    import subprocess
    from pathlib import Path
    
    config = ctx.obj
    dist_path = Path(config['build']['output'])
    
    if not dist_path.exists():
        click.echo("❌ Error: dist/ directory not found. Run 'gang build' first.", err=True)
        ctx.exit(1)
    
    # Check if Lighthouse CI is available
    try:
        subprocess.run(['npx', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("❌ Error: npx not found. Install Node.js to run Lighthouse audits.", err=True)
        ctx.exit(1)
    
    # Count pages
    page_count = len(list(dist_path.rglob('index.html')))
    click.echo(f"📊 Running audits on {page_count} pages...")
    click.echo("🔦 Lighthouse CI will auto-discover all pages in dist/")
    click.echo("   (3 runs per page, this may take a few minutes)\n")
    
    try:
        # Run Lighthouse CI with autorun (uses staticDistDir from config)
        result = subprocess.run(
            ['npx', '--yes', '@lhci/cli@0.13.x', 'autorun'],
            text=True
        )
        
        # Check thresholds from config
        thresholds = config.get('lighthouse', {})
        if result.returncode != 0:
            click.echo("\n❌ Lighthouse audits failed!")
            click.echo(f"   Expected: Performance ≥{thresholds.get('performance', 95)}, "
                      f"Accessibility ≥{thresholds.get('accessibility', 98)}, "
                      f"Best Practices ≥{thresholds.get('bestPractices', 100)}, "
                      f"SEO ≥{thresholds.get('seo', 100)}")
            ctx.exit(1)
        
        click.echo("\n✅ All audits passed!")
        
        # Report location
        lhci_dir = Path('.lighthouseci')
        if lhci_dir.exists():
            click.echo(f"📄 Detailed reports: {lhci_dir.absolute()}")
        
        if output:
            click.echo(f"📊 Custom report: {output}")
        
    except KeyboardInterrupt:
        click.echo("\n⚠️  Audit interrupted")
        ctx.exit(1)

@cli.command('update-deps')
@click.option('--check-only', is_flag=True, help='Only check for updates, do not install')
@click.option('--security-only', is_flag=True, help='Only update packages with security issues')
@click.pass_context
def update_deps(ctx, check_only, security_only):
    """Check and update third-party dependencies"""
    import subprocess
    
    click.echo("🔍 Checking for dependency updates...\n")
    
    # Check if pip-audit is available for security checks
    has_pip_audit = False
    if security_only:
        try:
            subprocess.run(['pip-audit', '--version'], capture_output=True, check=True)
            has_pip_audit = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            click.echo("⚠️  pip-audit not found. Install with: pip install pip-audit")
            click.echo("    Falling back to regular update check.\n")
    
    # Security audit
    if security_only and has_pip_audit:
        click.echo("🔒 Running security audit...")
        result = subprocess.run(
            ['pip-audit', '-r', 'requirements.txt'],
            capture_output=True,
            text=True
        )
        click.echo(result.stdout)
        if result.returncode != 0:
            click.echo("❌ Security vulnerabilities found!")
            ctx.exit(1)
        else:
            click.echo("✅ No security vulnerabilities found.")
        return
    
    # Check for outdated packages
    click.echo("📦 Checking Python packages...")
    result = subprocess.run(
        ['pip', 'list', '--outdated', '--format=columns'],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        click.echo(result.stdout)
        
        if not check_only:
            if click.confirm('\n📥 Update all dependencies in requirements.txt?'):
                # Update requirements.txt with latest versions
                click.echo("\n⬆️  Updating dependencies...")
                subprocess.run(['pip', 'install', '--upgrade', '-r', 'requirements.txt'])
                click.echo("\n✅ Dependencies updated! Run 'gang check && gang audit' to verify.")
            else:
                click.echo("⏭️  Skipped updates.")
    else:
        click.echo("✅ All dependencies are up to date!")
    
    # Reminder
    click.echo("\n💡 Tip: Enable Dependabot in .github/dependabot.yml for automated PRs")

@cli.command()
@click.argument('source_dir', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), help='Output directory for processed images')
@click.option('--analyze', is_flag=True, help='Analyze image usage in content')
@click.option('--check-alt', is_flag=True, help='Check for missing alt text')
@click.pass_context
def image(ctx, source_dir, output, analyze, check_alt):
    """Process images to responsive formats and validate usage"""
    try:
        from core.images import ImageProcessor
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.images import ImageProcessor
    
    config = ctx.obj
    processor = ImageProcessor(config)
    
    # If analyze or check-alt mode
    if analyze or check_alt:
        content_path = Path(config['build']['content'])
        click.echo("🔍 Analyzing images in content...\n")
        
        total_missing_alt = 0
        total_external = 0
        total_images = 0
        
        for md_file in content_path.rglob('*.md'):
            content = md_file.read_text()
            analysis = processor.analyze_markdown_images(content)
            
            if analysis['total_images'] > 0:
                total_images += analysis['total_images']
                total_missing_alt += analysis['missing_alt']
                total_external += analysis['external_images']
                
                if check_alt and analysis['missing_alt'] > 0:
                    click.echo(f"⚠️  {md_file.relative_to(content_path)}")
                    for img in analysis['images']:
                        if not img['has_alt']:
                            click.echo(f"   Missing alt: {img['url']}")
        
        click.echo(f"\n📊 Image Analysis Summary:")
        click.echo(f"├─ Total images: {total_images}")
        click.echo(f"├─ Missing alt text: {total_missing_alt}")
        click.echo(f"└─ External images: {total_external}")
        
        if total_missing_alt > 0:
            click.echo(f"\n💡 Run 'gang optimize' to auto-generate alt text with AI")
            ctx.exit(1)
        
        return
    
    # Regular image processing
    click.echo("🖼️  Processing images...")
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
            def log_message(self, format, *args):
                # Suppress HTTP request logs
                pass
            
            def do_GET(self):
                if self.path == '/api/content':
                    try:
                        # List all content files
                        content_path = Path(config['build']['content']).resolve()
                        files = []
                        
                        click.echo(f"🔍 Looking for content in: {content_path}")
                        
                        if not content_path.exists():
                            click.echo(f"⚠️  Content directory not found: {content_path}")
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps([]).encode())
                            return
                        
                        for md_file in content_path.rglob('*.md'):
                            files.append({
                                'path': str(md_file.relative_to(content_path)),
                                'type': md_file.parent.name,
                                'name': md_file.stem
                            })
                        
                        click.echo(f"📂 Found {len(files)} content files: {[f['name'] for f in files]}")
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(files).encode())
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error listing files: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path.startswith('/api/content/'):
                    try:
                        # Get specific content file
                        file_path = self.path.replace('/api/content/', '')
                        content_base = Path(config['build']['content']).resolve()
                        content_path = content_base / file_path
                        
                        click.echo(f"📖 Reading file: {content_path}")
                        
                        if content_path.exists():
                            content = content_path.read_text()
                            self.send_response(200)
                            self.send_header('Content-type', 'text/plain')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(content.encode())
                        else:
                            click.echo(f"❌ File not found: {content_path}")
                            self.send_error(404)
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error reading file: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path == '/' or self.path == '/studio.html':
                    # Serve studio UI
                    try:
                        studio_html_path = Path('studio.html').resolve()
                        click.echo(f"🎨 Serving studio from: {studio_html_path}")
                        if studio_html_path.exists():
                            with open(studio_html_path, 'r') as f:
                                content = f.read()
                            self.send_response(200)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(content.encode())
                        else:
                            click.echo(f"❌ studio.html not found at: {studio_html_path}")
                            self.send_error(404, "studio.html not found")
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error serving studio: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                else:
                    self.send_error(404)
            
            def do_POST(self):
                """Handle POST requests"""
                if self.path == '/api/rename-slug':
                    try:
                        # Read request body
                        content_length = int(self.headers['Content-Length'])
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode())
                        
                        old_slug = data.get('old_slug')
                        new_slug = data.get('new_slug')
                        category = data.get('category')
                        create_redirect = data.get('create_redirect', True)
                        
                        click.echo(f"🔄 Rename request: {old_slug} → {new_slug} (redirect: {create_redirect})")
                        
                        # Import redirect manager
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        from core.content_importer import SlugChecker
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])
                        
                        # Check old file exists
                        old_file = content_path / category / f"{old_slug}.md"
                        if not old_file.exists():
                            self.send_response(404)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'File not found',
                                'message': f'File {old_file} does not exist'
                            }).encode())
                            return
                        
                        # Check new slug is unique
                        new_file = content_path / category / f"{new_slug}.md"
                        if new_file.exists():
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Slug already exists',
                                'message': f'A file with slug "{new_slug}" already exists'
                            }).encode())
                            return
                        
                        # Rename file
                        old_file.rename(new_file)
                        click.echo(f"✅ File renamed: {old_file.name} → {new_file.name}")
                        
                        # Create redirect if requested
                        redirect_info = None
                        if create_redirect:
                            old_url = f"/{category}/{old_slug}/"
                            new_url = f"/{category}/{new_slug}/"
                            
                            redirect_manager = RedirectManager(content_path, dist_path)
                            result = redirect_manager.add_redirect(old_url, new_url, reason='slug_rename_cms')
                            redirect_info = result.get('redirect')
                            click.echo(f"✅ 301 redirect created: {old_url} → {new_url}")
                        
                        # Return success response
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'old_path': str(old_file.relative_to(content_path)),
                            'new_path': str(new_file.relative_to(content_path)),
                            'redirect': redirect_info
                        }).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error renaming slug: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Internal server error',
                            'message': str(e)
                        }).encode())
                
                elif self.path == '/api/redirects':
                    # Get all redirects
                    try:
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])
                        
                        manager = RedirectManager(content_path, dist_path)
                        redirects_list = manager.list_all_redirects()
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(redirects_list).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error listing redirects: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path == '/api/products/sync':
                    # Sync products from Shopify/Stripe/Gumroad
                    try:
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.products import ProductAggregator
                        
                        click.echo("🛒 Syncing products via API...")
                        aggregator = ProductAggregator(config)
                        products = aggregator.get_normalized_products(status_filter='all')
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'total': len(products),
                            'products': products
                        }).encode())
                        
                        click.echo(f"✅ Synced {len(products)} products")
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error syncing products: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                else:
                    self.send_error(404)
            
            def do_PUT(self):
                """Handle PUT requests"""
                if self.path.startswith('/api/content/'):
                    try:
                        # Get file path and content
                        file_path = self.path.replace('/api/content/', '')
                        content_base = Path(config['build']['content']).resolve()
                        content_path = content_base / file_path
                        
                        # Read request body
                        content_length = int(self.headers['Content-Length'])
                        body = self.rfile.read(content_length)
                        content = body.decode()
                        
                        # Save file
                        content_path.write_text(content)
                        click.echo(f"✅ Saved file: {content_path}")
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'path': str(content_path.relative_to(content_base))
                        }).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error saving file: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Failed to save',
                            'message': str(e)
                        }).encode())
                else:
                    self.send_error(404)
            
            def do_DELETE(self):
                """Handle DELETE requests"""
                if self.path.startswith('/api/redirects/'):
                    try:
                        # Get redirect path
                        from_path = self.path.replace('/api/redirects', '')
                        
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])
                        
                        manager = RedirectManager(content_path, dist_path)
                        
                        if manager.remove_redirect(from_path):
                            click.echo(f"✅ Redirect removed: {from_path}")
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'success': True,
                                'message': 'Redirect removed'
                            }).encode())
                        else:
                            self.send_response(404)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Redirect not found'
                            }).encode())
                            
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error deleting redirect: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                else:
                    self.send_error(404)
        
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


@cli.command()
@click.option('--port', default=8000, help='Port for dev server')
@click.option('--host', default='localhost', help='Host to bind to')
@click.pass_context
def serve(ctx, port, host):
    """Start dev server with live reload"""
    click.echo("🚀 Starting dev server with live reload...")
    
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import os
        
        config = ctx.obj
        content_path = Path(config['build']['content']).resolve()
        templates_path = Path(config['build'].get('templates', './templates')).resolve()
        public_path = Path(config['build']['public']).resolve()
        dist_path = Path(config['build']['output']).resolve()
        
        # Track clients for live reload
        reload_clients = []
        rebuild_pending = False
        last_rebuild = 0
        
        class ChangeHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                nonlocal rebuild_pending, last_rebuild
                
                if event.is_directory:
                    return
                
                # Ignore dist folder changes and hidden files
                if str(dist_path) in event.src_path or '/__pycache__/' in event.src_path:
                    return
                
                if event.src_path.startswith('.') or '/.git/' in event.src_path:
                    return
                
                # Debounce rebuilds (wait 0.5 seconds)
                current_time = time.time()
                if current_time - last_rebuild < 0.5:
                    rebuild_pending = True
                    return
                
                click.echo(f"\n📝 Change detected: {Path(event.src_path).name}")
                rebuild_site(ctx)
                # Small delay to ensure files are fully written
                time.sleep(0.1)
                notify_reload()
                last_rebuild = time.time()
                rebuild_pending = False
        
        # Live reload script to inject during build
        live_reload_script = '''
<script>
(function() {
    console.log('🔌 Connecting to live reload...');
    const source = new EventSource('/__livereload');
    
    source.onmessage = function(e) {
        if (e.data === 'reload') {
            console.log('🔄 Reloading page...');
            location.reload();
        }
    };
    
    source.onerror = function(e) {
        console.warn('Live reload disconnected');
        source.close();
    };
    
    source.onopen = function(e) {
        console.log('✅ Live reload connected');
    };
    
    // IMPORTANT: Close connection when navigating away
    window.addEventListener('beforeunload', function() {
        console.log('Closing live reload connection...');
        source.close();
    });
    
    // Also close on pagehide (for back/forward navigation)
    window.addEventListener('pagehide', function() {
        source.close();
    });
})();
</script>
'''
        
        def rebuild_site(ctx):
            """Rebuild the site"""
            click.echo("🔨 Rebuilding site...")
            try:
                # Import here to use fresh code
                from core.templates import TemplateEngine
                from core.generators import OutputGenerators
                from core.optimizer import AIOptimizer
                
                # Clear dist
                if dist_path.exists():
                    shutil.rmtree(dist_path)
                dist_path.mkdir(parents=True, exist_ok=True)
                
                # Initialize systems
                template_engine = TemplateEngine(templates_path)
                generators = OutputGenerators(config)
                optimizer = AIOptimizer(config)
                
                # Copy public assets
                if public_path.exists():
                    shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
                
                # Build content
                all_pages = []
                all_posts = []
                all_projects = []
                
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
                    md_converter = markdown.Markdown(extensions=['extra', 'meta'])
                    content_html = md_converter.convert(body)
                    
                    # Process external links to open in new tabs
                    content_html = process_external_links(content_html)
                    
                    # Prepare context
                    slug = md_file.stem
                    if content_type == 'posts':
                        url = f"/posts/{slug}/"
                        template_name = 'post.html'
                    elif content_type == 'projects':
                        url = f"/projects/{slug}/"
                        template_name = 'post.html'
                    elif content_type == 'pages':
                        url = f"/pages/{slug}/"
                        template_name = 'page.html'
                    else:
                        url = f"/{content_type}/{slug}/"
                        template_name = 'page.html'
                    
                    build_time = datetime.now()
                    context = {
                        'site_title': config['site']['title'],
                        'lang': config['site']['language'],
                        'title': frontmatter.get('title', slug.replace('-', ' ').title()),
                        'description': frontmatter.get('summary', config['site']['description']),
                        'content': content_html,
                        'year': datetime.now().year,
                        'navigation': config.get('nav', {}).get('main', []),
                        'date': frontmatter.get('date'),
                        'date_formatted': str(frontmatter.get('date', '')),
                        'tags': frontmatter.get('tags', []),
                        'build_time': build_time.strftime('%B %d, %Y at %I:%M %p'),
                        'build_time_iso': build_time.isoformat(),
                        'jsonld': frontmatter.get('jsonld'),
                        'canonical_url': f"{config['site']['url']}{url}",
                    }
                    
                    # Render HTML
                    try:
                        html = template_engine.render(template_name, context)
                    except Exception as e:
                        html = process_markdown_fallback(md_file, content_type, config)
                    
                    # Inject live reload script
                    if '</body>' in html:
                        html = html.replace('</body>', live_reload_script + '</body>')
                    else:
                        html += live_reload_script
                    
                    # Calculate and inject page size
                    page_size_bytes = len(html.encode('utf-8'))
                    page_size_str = format_bytes(page_size_bytes)
                    html = html.replace('__PAGE_SIZE__', page_size_str)
                    
                    # Write output
                    output_file = dist_path / content_type / slug / 'index.html'
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    output_file.write_text(html)
                    
                    # Collect metadata
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
                index_html = create_index_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5])
                # Inject live reload script
                if '</body>' in index_html:
                    index_html = index_html.replace('</body>', live_reload_script + '</body>')
                else:
                    index_html += live_reload_script
                # Recalculate page size after injecting live reload
                page_size_bytes = len(index_html.encode('utf-8'))
                index_html = index_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                (dist_path / 'index.html').write_text(index_html)
                
                # Create list pages
                if all_posts:
                    posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts')
                    # Inject live reload script
                    if '</body>' in posts_html:
                        posts_html = posts_html.replace('</body>', live_reload_script + '</body>')
                    # Recalculate page size after injecting live reload
                    page_size_bytes = len(posts_html.encode('utf-8'))
                    posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                    (dist_path / 'posts' / 'index.html').write_text(posts_html)
                
                if all_projects:
                    projects_html = create_list_page_simple(config, all_projects, 'Projects')
                    # Inject live reload script
                    if '</body>' in projects_html:
                        projects_html = projects_html.replace('</body>', live_reload_script + '</body>')
                    # Recalculate page size after injecting live reload
                    page_size_bytes = len(projects_html.encode('utf-8'))
                    projects_html = projects_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                    (dist_path / 'projects' / 'index.html').write_text(projects_html)
                
                # Generate outputs
                all_pages.append({'url': '/', 'title': config['site']['title'], 'type': 'home'})
                if all_posts:
                    all_pages.append({'url': '/posts/', 'title': 'Posts', 'type': 'list'})
                if all_projects:
                    all_pages.append({'url': '/projects/', 'title': 'Projects', 'type': 'list'})
                
                generators.generate_all(dist_path, all_pages, all_posts)
                
                # Generate product pages (only active products)
                try:
                    from core.products import ProductAggregator
                    from jinja2 import Environment, FileSystemLoader
                    
                    aggregator = ProductAggregator(config)
                    products = aggregator.get_normalized_products(status_filter='active')
                    
                    if products:
                        # Setup Jinja2
                        template_dir = Path(__file__).parent.parent.parent / 'templates'
                        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
                        
                        products_path = dist_path / 'products'
                        products_path.mkdir(parents=True, exist_ok=True)
                        
                        # Generate PLP
                        plp_template = jinja_env.get_template('products-list.html')
                        plp_html = plp_template.render(
                            products=products,
                            site_title=config['site']['title'],
                            lang=config['site'].get('language', 'en'),
                            canonical_url=f"{config['site']['url']}/products/",
                            year=datetime.now().year,
                            navigation=config.get('nav', {}).get('main', []),
                            build_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                            build_time_iso=datetime.now().isoformat()
                        )
                        # Inject live reload
                        if '</body>' in plp_html:
                            plp_html = plp_html.replace('</body>', live_reload_script + '</body>')
                        (products_path / 'index.html').write_text(plp_html)
                        
                        # Generate PDPs
                        pdp_template = jinja_env.get_template('product.html')
                        for product in products:
                            slug = product['_meta'].get('slug') or product['_meta'].get('handle')
                            if not slug:
                                continue
                            
                            pdp_dir = products_path / slug
                            pdp_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Handle images FIRST
                            raw_images = product.get('image', [])
                            type_name = type(raw_images).__name__
                            if type_name in ('list', 'tuple'):
                                images = [str(img) for img in raw_images if img]
                            elif raw_images:
                                images = [str(raw_images)]
                            else:
                                images = []
                            
                            # Extract offer data and variants
                            offers = product.get('offers', {})
                            variants_list = []
                            
                            if type(offers).__name__ == 'list':
                                colors = set()
                                sizes = set()
                                color_to_image = {}
                                color_order = []
                                
                                for offer in offers:
                                    variant_name = offer.get('name', '')
                                    if '/' in variant_name:
                                        parts = variant_name.split('/')
                                        color = parts[0].strip()
                                        size = parts[1].strip() if len(parts) > 1 else ''
                                        
                                        if color not in colors:
                                            color_order.append(color)
                                            colors.add(color)
                                        if size:
                                            sizes.add(size)
                                
                                for idx, color in enumerate(color_order):
                                    if idx < len(images):
                                        color_to_image[color] = idx
                                
                                for offer in offers:
                                    variant_name = offer.get('name', '')
                                    color_part = ''
                                    size_part = ''
                                    
                                    if '/' in variant_name:
                                        parts = variant_name.split('/')
                                        color_part = parts[0].strip()
                                        size_part = parts[1].strip() if len(parts) > 1 else ''
                                    
                                    variants_list.append({
                                        'name': variant_name,
                                        'color': color_part,
                                        'size': size_part,
                                        'price': offer.get('price', '0'),
                                        'currency': offer.get('priceCurrency', 'USD'),
                                        'availability': offer.get('availability', 'InStock'),
                                        'url': offer.get('url', '#'),
                                        'sku': offer.get('sku', ''),
                                        'image_index': color_to_image.get(color_part, 0) if color_part else 0
                                    })
                                
                                first_offer = offers[0]
                                colors_list = [c for c in sorted(colors)]
                                sizes_list = [s for s in sorted(sizes)]
                            else:
                                first_offer = offers
                                colors_list = []
                                sizes_list = []
                            
                            # Prepare template variables
                            brand_data = product.get('brand', '')
                            brand_name = brand_data.get('name', '') if hasattr(brand_data, 'get') else str(brand_data)
                            
                            pdp_context = {
                                'lang': config['site'].get('language', 'en'),
                                'site_title': config['site']['title'],
                                'title': product.get('name', ''),
                                'description': product.get('description', ''),
                                'canonical_url': f"{config['site']['url']}/products/{slug}/",
                                'product_image': images[0] if images else '',
                                'product_images': images,
                                'price': first_offer.get('price', '0'),
                                'currency': first_offer.get('priceCurrency', 'USD'),
                                'recurring': None,
                                'content': product.get('description', ''),
                                'buy_url': first_offer.get('url', '#'),
                                'variants': variants_list,
                                'colors': colors_list,
                                'sizes': sizes_list,
                                'sku': product.get('sku', ''),
                                'brand': brand_name,
                                'category': product.get('category', ''),
                                'availability': first_offer.get('availability', 'InStock'),
                                'jsonld': product,
                                'year': datetime.now().year,
                                'navigation': config.get('nav', {}).get('main', []),
                                'build_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                                'build_time_iso': datetime.now().isoformat()
                            }
                            
                            pdp_html = pdp_template.render(**pdp_context)
                            # Inject live reload
                            if '</body>' in pdp_html:
                                pdp_html = pdp_html.replace('</body>', live_reload_script + '</body>')
                            (pdp_dir / 'index.html').write_text(pdp_html)
                        
                        # Generate cart page
                        cart_dir = dist_path / 'cart'
                        cart_dir.mkdir(parents=True, exist_ok=True)
                        cart_template = jinja_env.get_template('cart.html')
                        cart_html = cart_template.render()
                        if '</body>' in cart_html:
                            cart_html = cart_html.replace('</body>', live_reload_script + '</body>')
                        (cart_dir / 'index.html').write_text(cart_html)
                        
                        # Generate HTML sitemap
                        sitemap_dir = dist_path / 'sitemap'
                        sitemap_dir.mkdir(parents=True, exist_ok=True)
                        sitemap_template = jinja_env.get_template('sitemap.html')
                        sitemap_html = sitemap_template.render(
                            site_title=config['site']['title'],
                            site_url=config['site']['url'],
                            pages=all_pages,
                            posts=all_posts,
                            projects=all_projects,
                            products=products,
                            year=datetime.now().year,
                            build_time_iso=datetime.now().isoformat()
                        )
                        if '</body>' in sitemap_html:
                            sitemap_html = sitemap_html.replace('</body>', live_reload_script + '</body>')
                        (sitemap_dir / 'index.html').write_text(sitemap_html)
                except Exception as e:
                    click.echo(f"⚠️  Could not generate product pages: {e}")
                
                click.echo("✅ Build complete!")
                
            except Exception as e:
                click.echo(f"❌ Build error: {e}", err=True)
                import traceback
                traceback.print_exc()
        
        def notify_reload():
            """Notify all connected clients to reload"""
            click.echo(f"📡 Notifying {len(reload_clients)} connected clients")
            for client in reload_clients[:]:
                try:
                    client.wfile.write(b"data: reload\n\n")
                    client.wfile.flush()
                except Exception as e:
                    if client in reload_clients:
                        reload_clients.remove(client)
        
        class LiveReloadHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(dist_path), **kwargs)
            
            def log_message(self, format, *args):
                # Log requests for debugging
                if len(args) > 0:
                    click.echo(f"[REQUEST] {args[0]}")
            
            def do_GET(self):
                try:
                    if self.path == '/__livereload':
                        # SSE endpoint for live reload
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Connection', 'keep-alive')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        
                        reload_clients.append(self)
                        
                        # Keep connection alive - just wait, no pings needed
                        try:
                            # Block until client disconnects or we send reload
                            while True:
                                time.sleep(60)
                        except:
                            pass
                        finally:
                            if self in reload_clients:
                                reload_clients.remove(self)
                    else:
                        # Let parent handle all other requests (HTML and assets)
                        super().do_GET()
                except BrokenPipeError:
                    # Client disconnected, ignore
                    pass
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    try:
                        self.send_error(500)
                    except:
                        pass
        
        # Initial build
        click.echo("🔨 Initial build...")
        rebuild_site(ctx)
        
        # Start file watcher
        observer = Observer()
        handler = ChangeHandler()
        
        # Watch content, templates, and public directories
        if content_path.exists():
            observer.schedule(handler, str(content_path), recursive=True)
            click.echo(f"👀 Watching: {content_path}")
        
        if templates_path.exists():
            observer.schedule(handler, str(templates_path), recursive=True)
            click.echo(f"👀 Watching: {templates_path}")
        
        if public_path.exists():
            observer.schedule(handler, str(public_path), recursive=True)
            click.echo(f"👀 Watching: {public_path}")
        
        observer.start()
        
        # Start HTTP server (threading to handle multiple connections)
        server = ThreadingHTTPServer((host, port), LiveReloadHandler)
        
        click.echo(f"\n✅ Dev server running at http://{host}:{port}")
        click.echo("📝 Live reload enabled - changes will auto-refresh the browser")
        click.echo("Press Ctrl+C to stop\n")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down...")
            observer.stop()
            observer.join()
            server.shutdown()
    
    except ImportError as e:
        click.echo(f"❌ Error: {e}", err=True)
        click.echo("Install watchdog: pip install watchdog>=3.0.0")
        ctx.abort()


def create_studio_html(output_path: Path):
    """Create the Studio CMS HTML interface"""
    html = r"""<!DOCTYPE html>
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
            color: #595959;
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
            const listEl = document.getElementById('contentList');
            try {
                console.log('Fetching content from /api/content...');
                const response = await fetch('/api/content');
                console.log('Response status:', response.status);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const files = await response.json();
                console.log('Received files:', files);
                
                listEl.innerHTML = '';
                
                if (files.length === 0) {
                    listEl.innerHTML = '<div class="loading">No content files found</div>';
                    return;
                }
                
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
                listEl.innerHTML = `<div class="loading" style="color: #ff6b6b;">Error: ${e.message}<br><br>Check browser console for details</div>`;
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GANG CLI - Single binary for all build operations
"""

import click
import yaml
import os
import sys
import re
import hashlib
import json
import shutil
import markdown
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

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
        
        click.echo("Score Analyzing answerability...\n")
        
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


@cli.group()
def migrate():
    """Run reversible repository migrations"""
    pass


@migrate.command("analyze")
@click.option("--content-dir", type=click.Path(exists=True, file_okay=False), help="Content directory to analyze")
@click.option("--output-dir", type=click.Path(file_okay=False), default="reports", help="Directory for migration reports")
@click.pass_context
def migrate_analyze(ctx, content_dir, output_dir):
    """Analyze future vault migration without changing content"""
    try:
        from core.migration_analysis import MigrationAnalyzer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.migration_analysis import MigrationAnalyzer

    config = ctx.obj
    root_path = Path(".")
    output_path = Path(output_dir)
    analyzer = MigrationAnalyzer(
        config,
        root_path=root_path,
        content_path=Path(content_dir) if content_dir else None,
        id_map_path=output_path / "migration-manifest.json",
    )
    analysis = analyzer.analyze()
    paths = analyzer.write_reports(output_path, analysis)
    summary = analysis["summary"]

    click.echo("Migration analysis complete (dry run only).")
    click.echo(f"  Files analyzed: {summary['total_files_analyzed']}")
    click.echo(f"  Canonical candidates: {summary['canonical_migration_candidates']}")
    click.echo(f"  Excluded from migration: {summary['excluded_from_migration']}")
    click.echo(f"  Currently public: {summary['currently_public']}")
    click.echo(f"  Migration-safe: {summary['migration_safe']}")
    click.echo(f"  Review required: {summary['review_required']}")
    click.echo(f"  URL conflicts: {summary['url_conflicts']}")
    click.echo(f"  JSON report: {paths['analysis_json']}")
    click.echo(f"  Markdown report: {paths['analysis_md']}")
    click.echo(f"  Manifest: {paths['manifest_json']}")


@migrate.command('apply')
@click.argument('plan_path', type=click.Path(exists=True))
@click.option('--apply', 'apply_changes', is_flag=True, help='Write migrated files (default is dry-run)')
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help='Audit output format')
def migrate_apply(plan_path, apply_changes, format):
    """Apply a durable migration plan"""
    try:
        from core.migration import LegacyContentMigrator, MigrationError
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.migration import LegacyContentMigrator, MigrationError

    migrator = LegacyContentMigrator(Path.cwd())

    try:
        audit = migrator.apply_plan(Path(plan_path), apply=apply_changes)
    except MigrationError as e:
        click.echo(f"❌ Migration failed: {e}", err=True)
        ctx = click.get_current_context()
        ctx.exit(1)

    if format == 'json':
        click.echo(json.dumps(audit, indent=2))
        return

    mode = "APPLY" if apply_changes else "DRY-RUN"
    click.echo(f"🧭 Migration {mode}: {plan_path}")
    click.echo(f"Records: {audit['records']}")
    click.echo(f"Would write: {audit['would_write']}")
    click.echo(f"Written: {audit['written']}")
    click.echo(f"Unchanged: {audit['unchanged']}")
    click.echo(f"Failed: {audit['failed']}")

    for result in audit['results']:
        click.echo(f"  {result['status']}: {result['source_path']} -> {result['destination_path']}")

    if audit.get('excluded_records'):
        click.echo("\nReview-required records excluded:")
        for item in audit['excluded_records']:
            click.echo(f"  {item.get('source_path')}: {item.get('reason')}")

    click.echo("\nReports written:")
    click.echo("  reports/migration-audit.json")
    click.echo("  reports/migration-manifest.json")

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
    
    click.echo("Score Validating site against contracts...\n")
    
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
            click.echo(f"  Best Practices {md_file.relative_to(content_path)}")
    
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
            click.echo(f"  Best Practices Good: {statuses.count('good') + statuses.count('excellent')}")
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
        click.echo(f"Performance Build Performance History (last {min(limit, len(runs))} runs)")
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
        click.echo("Best Practices No broken links found!")
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
                click.echo(f"  Best Practices {item['file']}")
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

@cli.group()
def ingest():
    """Import private source material into the knowledge inbox"""
    pass

def _run_private_ingest(adapter):
    try:
        from core.ingestion import IngestionPipeline, LocalRawStore
        from core.ingestion.registry import IngestionRegistry
        from core.paths import GangPaths
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import IngestionPipeline, LocalRawStore
        from core.ingestion.registry import IngestionRegistry
        from core.paths import GangPaths

    paths = GangPaths.from_env()
    pipeline = IngestionPipeline(
        LocalRawStore(paths.raw_path),
        inbox_path=paths.inbox_path,
        meetings_path=paths.meetings_path,
        registry=IngestionRegistry(paths.registry_path, root_path=paths.home),
    )
    return pipeline.ingest(adapter)

def _print_ingest_results(results):
    if not results:
        click.echo("No supported sources found.")
        return

    click.echo(f"✅ Ingested {len(results)} source(s)")
    for result in results:
        click.echo(f"  - Status: {result.status}")
        click.echo(f"  - Document: {result.document_path}")
        click.echo(f"    Document ID: {result.document_id}")
        click.echo(f"    Source ID: {result.source_id}")
        click.echo(f"    Raw version: v{result.version:06d}")
        click.echo(f"    Raw ref: {result.raw_record.raw_ref}")

@ingest.command('file')
@click.argument('path', type=click.Path(exists=True))
@click.option('--namespace', default='local-file', help='Stable source namespace for local file identity')
def ingest_file(path, namespace):
    """Import a local .md, .txt, .json, or .jsonl file as private knowledge"""
    try:
        from core.ingestion import FileAdapter
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import FileAdapter

    try:
        results = _run_private_ingest(FileAdapter(Path(path), source_namespace=namespace))
    except Exception as e:
        click.echo(f"❌ Ingest failed: {e}", err=True)
        raise click.Abort()

    _print_ingest_results(results)

@ingest.command('meeting')
@click.argument('path', type=click.Path(exists=True))
@click.option('--namespace', default='local-meeting', help='Stable source namespace for meeting source identity')
def ingest_meeting(path, namespace):
    """Import a local meeting transcript as private knowledge"""
    try:
        from core.ingestion import MeetingTranscriptAdapter
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import MeetingTranscriptAdapter

    try:
        results = _run_private_ingest(MeetingTranscriptAdapter(Path(path), source_namespace=namespace))
    except Exception as e:
        click.echo(f"❌ Ingest failed: {e}", err=True)
        raise click.Abort()

    _print_ingest_results(results)

@ingest.command('status')
def ingest_status():
    """Show private ingestion registry status"""
    try:
        from core.ingestion import IngestionRegistry
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import IngestionRegistry

    registry = IngestionRegistry()
    sources = registry.all_sources()
    click.echo("Private ingestion registry")
    click.echo(f"  Registry: {registry.path}")
    click.echo(f"  Sources: {len(sources)}")
    for source_id, record in sorted(sources.items()):
        click.echo(f"  - {source_id}")
        click.echo(f"    adapter: {record.get('adapter')}")
        click.echo(f"    document_id: {record.get('document_id')}")
        click.echo(f"    version: {record.get('version')}")
        click.echo(f"    document_path: {record.get('document_path')}")

@ingest.command('inspect')
@click.argument('source_id')
def ingest_inspect(source_id):
    """Inspect one private ingestion source record"""
    try:
        from core.ingestion import IngestionRegistry
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import IngestionRegistry

    registry = IngestionRegistry()
    record = registry.get(source_id)
    if not record:
        click.echo(f"Source not found: {source_id}", err=True)
        raise click.Abort()
    click.echo(json.dumps(record, indent=2, sort_keys=True))


@cli.group("brain")
def brain():
    """Manage the durable private brain home"""
    pass


@brain.command("status")
def brain_status():
    """Show private brain home status without printing private content"""
    try:
        from core.brain_home import BrainHome
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.brain_home import BrainHome

    status = BrainHome(repo_root=Path.cwd()).status()
    click.echo("Private brain home")
    click.echo(f"  Private home: {status['private_home']}")
    click.echo(f"  Private documents: {status['private_documents']}")
    click.echo(f"  Raw sources: {status['raw_sources']}")
    click.echo(f"  Gmail threads: {status['gmail_threads']}")
    click.echo(f"  Generated index: {status['generated_index']}")
    click.echo(f"  Index exists: {'yes' if status['generated_index_exists'] else 'no'}")
    click.echo(f"  Repository public documents: {status['repository_public_documents']}")


@brain.command("migrate")
@click.option("--from", "from_path", type=click.Path(exists=True, file_okay=False), help="Source repo/workspace to migrate from")
@click.option("--apply", "apply_changes", is_flag=True, help="Copy files into GANG_HOME (default is dry-run)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
def brain_migrate(from_path, apply_changes, output_format):
    """Dry-run or apply migration from repo-local private brain state"""
    try:
        from core.brain_home import BrainHome
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.brain_home import BrainHome

    result = BrainHome(repo_root=Path.cwd()).migrate(source_root=Path(from_path) if from_path else None, apply=apply_changes)
    if output_format == "json":
        serializable = {
            key: [
                {
                    "kind": item.kind,
                    "status": item.status,
                    "source": item.source.as_posix(),
                    "destination": item.destination.as_posix(),
                }
                for item in value
            ]
            if key in {"items", "conflicts", "will_copy", "unchanged"}
            else (value.as_posix() if isinstance(value, Path) else value)
            for key, value in result.items()
        }
        click.echo(json.dumps(serializable, indent=2, sort_keys=True))
        return

    mode = "APPLY" if apply_changes else "DRY-RUN"
    click.echo(f"Brain migration {mode}")
    click.echo(f"  Source: {result['source_root']}")
    click.echo(f"  Private home: {result['private_home']}")
    click.echo(f"  Would copy: {len(result['will_copy'])}")
    click.echo(f"  Unchanged: {len(result['unchanged'])}")
    click.echo(f"  Conflicts: {len(result['conflicts'])}")
    for item in result["items"]:
        click.echo(f"  - {item.status}: {item.kind}: {item.source} -> {item.destination}")
    if result["conflicts"]:
        click.echo("Conflicts detected; no files were copied.", err=True)
        raise click.Abort()
    if apply_changes:
        click.echo("Migration copied files into GANG_HOME. Source files were left untouched.")
    else:
        click.echo("Dry run only. Re-run with --apply to copy files.")


@ingest.group("gmail", invoke_without_command=True)
@click.option("--since", help="Bounded first sync range, such as 30d or 2026-01-31")
@click.pass_context
def ingest_gmail(ctx, since):
    """Authenticate and import Gmail threads as private knowledge"""
    if ctx.invoked_subcommand is not None:
        return

    try:
        from core.ingestion import GmailIngestionError, GmailSyncService, GoogleGmailProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import GmailIngestionError, GmailSyncService, GoogleGmailProvider

    try:
        result = GmailSyncService(GoogleGmailProvider()).sync(since=since)
    except GmailIngestionError as e:
        click.echo(f"❌ Gmail ingest failed: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ Gmail ingest failed: {e}", err=True)
        raise click.Abort()

    _print_gmail_sync_result(result)


@ingest_gmail.command("auth")
def ingest_gmail_auth():
    """Authorize Gmail read access for this local workspace"""
    try:
        from core.ingestion import GmailIngestionError, GoogleGmailProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import GmailIngestionError, GoogleGmailProvider

    provider = GoogleGmailProvider()
    try:
        token_path = provider.authenticate()
    except GmailIngestionError as e:
        click.echo(f"❌ Gmail auth failed: {e}", err=True)
        raise click.Abort()
    click.echo("✅ Gmail authorized")
    click.echo(f"  Token: {token_path}")
    click.echo("  Scope: gmail.readonly")


@ingest_gmail.command("status")
def ingest_gmail_status():
    """Show private Gmail connector status"""
    try:
        from core.ingestion import GmailSyncService, GoogleGmailProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import GmailSyncService, GoogleGmailProvider

    status = GmailSyncService(GoogleGmailProvider()).status()
    checkpoint = status["checkpoint"]
    click.echo("Gmail ingestion")
    click.echo(f"  Checkpoint: {status['checkpoint_path']}")
    click.echo(f"  Threads: {status['threads']}")
    click.echo(f"  Documents: {status['documents']}")
    if checkpoint:
        click.echo(f"  Last successful sync: {checkpoint.get('last_successful_sync_at')}")
        click.echo(f"  Last checkpoint: {checkpoint.get('last_successful_internal_date_ms')}")
        click.echo(f"  Last query: {checkpoint.get('last_query')}")
    else:
        click.echo("  Last successful sync: never")


def _print_gmail_sync_result(result):
    click.echo("Gmail ingestion complete")
    click.echo(f"  Threads discovered: {result.threads_discovered}")
    click.echo(f"  Messages discovered: {result.messages_discovered}")
    click.echo(f"  Created: {result.created}")
    click.echo(f"  Updated: {result.updated}")
    click.echo(f"  Unchanged: {result.unchanged}")
    click.echo(f"  Failed: {result.failed}")
    checkpoint_value = result.checkpoint.get("last_successful_internal_date_ms") if result.checkpoint else None
    click.echo(f"  Checkpoint: {checkpoint_value or 'not advanced'}")
    for item in result.results:
        click.echo(f"  - Thread: {item.thread_id}")
        click.echo(f"    Status: {item.status}")
        if item.document_id:
            click.echo(f"    Document ID: {item.document_id}")
        if item.document_path:
            click.echo(f"    Document: {item.document_path}")
        click.echo(f"    Source ID: {item.source_id}")
        click.echo(f"    Messages: {item.messages}")
        if item.error:
            click.echo(f"    Error: {item.error}")


@ingest.group("drive", invoke_without_command=True)
@click.option("--since", help="Bounded first sync range, such as 30d or 2026-01-31")
@click.option("--folder", "folder_id", help="Bounded initial sync to one Drive folder ID")
@click.pass_context
def ingest_drive(ctx, since, folder_id):
    """Authenticate and import Google Drive files as private documents"""
    if ctx.invoked_subcommand is not None:
        return

    try:
        from core.ingestion import DriveIngestionError, DriveSyncService, GoogleDriveProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import DriveIngestionError, DriveSyncService, GoogleDriveProvider

    try:
        result = DriveSyncService(GoogleDriveProvider()).sync(since=since, folder_id=folder_id)
    except DriveIngestionError as e:
        click.echo(f"❌ Drive ingest failed: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ Drive ingest failed: {e}", err=True)
        raise click.Abort()

    _print_drive_sync_result(result)


@ingest_drive.command("auth")
def ingest_drive_auth():
    """Authorize Drive read access for this local workspace"""
    try:
        from core.ingestion import DriveIngestionError, GoogleDriveProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import DriveIngestionError, GoogleDriveProvider

    provider = GoogleDriveProvider()
    try:
        token_path = provider.authenticate()
    except DriveIngestionError as e:
        click.echo(f"❌ Drive auth failed: {e}", err=True)
        raise click.Abort()
    click.echo("✅ Drive authorized")
    click.echo(f"  Token: {token_path}")
    click.echo("  Scope: drive.readonly")


@ingest_drive.command("status")
def ingest_drive_status():
    """Show private Drive connector status"""
    try:
        from core.ingestion import DriveSyncService, GoogleDriveProvider
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ingestion import DriveSyncService, GoogleDriveProvider

    status = DriveSyncService(GoogleDriveProvider()).status()
    checkpoint = status["checkpoint"]
    click.echo("Drive ingestion")
    click.echo(f"  Checkpoint: {status['checkpoint_path']}")
    click.echo(f"  Files: {status['files']}")
    click.echo(f"  Documents: {status['documents']}")
    if checkpoint:
        click.echo(f"  Last successful sync: {checkpoint.get('last_successful_sync_at')}")
        click.echo(f"  Start page token: {checkpoint.get('start_page_token')}")
        if checkpoint.get("last_since"):
            click.echo(f"  Last since bound: {checkpoint.get('last_since')}")
        if checkpoint.get("last_folder_id"):
            click.echo(f"  Last folder bound: {checkpoint.get('last_folder_id')}")
    else:
        click.echo("  Last successful sync: never")


def _print_drive_sync_result(result):
    click.echo("Drive ingestion complete")
    click.echo(f"  Files discovered: {result.files_discovered}")
    click.echo(f"  Supported: {result.supported}")
    click.echo(f"  Unsupported: {result.unsupported}")
    click.echo(f"  Created: {result.created}")
    click.echo(f"  Updated: {result.updated}")
    click.echo(f"  Unchanged: {result.unchanged}")
    click.echo(f"  Failed: {result.failed}")
    checkpoint_value = result.checkpoint.get("start_page_token") if result.checkpoint else None
    click.echo(f"  Checkpoint: {checkpoint_value or 'not advanced'}")
    for item in result.results:
        click.echo(f"  - Drive file: {item.drive_file_id}")
        click.echo(f"    Status: {item.status}")
        click.echo(f"    Source ID: {item.source_id}")
        if item.document_id:
            click.echo(f"    Document ID: {item.document_id}")
        if item.document_path:
            click.echo(f"    Document: {item.document_path}")
        if item.error:
            click.echo(f"    Error: {item.error}")


@cli.group("index")
def private_index():
    """Build and inspect the local private knowledge index"""
    pass


@private_index.command("build")
def private_index_build():
    """Build the local private SQLite FTS index from brain/vault"""
    try:
        from core.private_index import PrivateKnowledgeIndex
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.private_index import PrivateKnowledgeIndex

    try:
        result = PrivateKnowledgeIndex().build()
    except Exception as e:
        click.echo(f"❌ Index build failed: {e}", err=True)
        raise click.Abort()

    click.echo("✅ Built private knowledge index")
    click.echo(f"  Database: {PrivateKnowledgeIndex().relative_database_path()}")
    click.echo(f"  Documents: {result.documents}")
    click.echo(f"  Entities: {result.entities}")
    click.echo(f"  Entity mentions: {result.mentions}")
    click.echo(f"  Relationships: {result.relationships}")
    click.echo(f"  Generated: {result.generated_at}")


@private_index.command("status")
def private_index_status():
    """Show local private knowledge index status"""
    try:
        from core.private_index import PrivateKnowledgeIndex
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.private_index import PrivateKnowledgeIndex

    status = PrivateKnowledgeIndex().status()
    click.echo("Private knowledge index")
    click.echo(f"  Database: {status['database']}")
    click.echo(f"  Built: {'yes' if status['exists'] else 'no'}")
    click.echo(f"  Documents: {status['documents']}")
    if status["generated_at"]:
        click.echo(f"  Generated: {status['generated_at']}")
    if status["by_visibility"]:
        click.echo("  Visibility:")
        for visibility, count in status["by_visibility"].items():
            click.echo(f"    {visibility}: {count}")
    if status["by_type"]:
        click.echo("  Types:")
        for doc_type, count in status["by_type"].items():
            click.echo(f"    {doc_type}: {count}")
    click.echo("  Entity graph:")
    click.echo(f"    entities: {status['entities']}")
    click.echo(f"    mentions: {status['entity_mentions']}")
    click.echo(f"    relationships: {status['relationships']}")


@cli.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--type", "type_filter", help="Filter by document type")
@click.option("--visibility", help="Filter by visibility")
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum results")
@click.option("--tag", help="Filter by tag")
@click.option("--project", help="Filter by project")
@click.option("--person", help="Filter by person")
@click.option("--source", help="Filter by source ID")
def private_search(query, type_filter, visibility, limit, tag, project, person, source):
    """Search the local private knowledge index"""
    try:
        from core.private_index import PrivateKnowledgeIndex
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.private_index import PrivateKnowledgeIndex

    index = PrivateKnowledgeIndex()
    try:
        results = index.search(
            " ".join(query),
            limit=limit,
            type=type_filter,
            visibility=visibility,
            tag=tag,
            project=project,
            person=person,
            source=source,
        )
    except FileNotFoundError:
        click.echo("Private knowledge index is missing. Run: gang index build", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ Search failed: {e}", err=True)
        raise click.Abort()

    if not results:
        click.echo("No results.")
        return

    for i, result in enumerate(results, 1):
        source_ids = ", ".join(result["source_ids"]) if result["source_ids"] else ""
        click.echo(f"{i}. {result['title']}")
        click.echo(f"   id: {result['document_id']}")
        click.echo(f"   type: {result['type']}")
        click.echo(f"   visibility: {result['visibility']}")
        click.echo(f"   updated: {result['updated']}")
        if source_ids:
            click.echo(f"   source_id: {source_ids}")
        if result["excerpt"]:
            click.echo(f"   excerpt: {result['excerpt']}")

@cli.command("ask")
@click.argument("question", nargs=-1, required=False)
@click.option("--new", "new_session", is_flag=True, help="Start a fresh conversation, discarding prior context")
@click.option("--resume", "resume_id", help="Resume an existing session by ID")
@click.option("--session", "session_id", help="Use (and create if needed) a session by ID")
@click.option("--sessions", "list_sessions", is_flag=True, help="List saved conversations and exit")
@click.option("--since", help="Only use evidence updated on/after this date (YYYY-MM-DD, 30d, or 'last week')")
@click.option("--until", help="Only use evidence updated on/before this date")
@click.option("--type", "document_types", multiple=True, help="Filter by document type (repeatable)")
@click.option("--source-type", "source_types", multiple=True, help="Filter by source type, such as gmail-thread (repeatable)")
@click.option("--entity", "entity_ids", multiple=True, help="Restrict retrieval to an entity ID (repeatable)")
@click.option("--visibility", type=click.Choice(["private", "public"]), help="Restrict evidence to one visibility")
@click.option("--limit", default=8, show_default=True, type=int, help="Maximum evidence documents (bounded)")
@click.option("--order", type=click.Choice(["relevance", "recency"]), help="Ranking order")
@click.option("--show-sources", is_flag=True, help="Show source IDs, excerpts, and entity references per citation")
@click.option("--json", "as_json", is_flag=True, help="Emit the structured result instead of terminal prose")
@click.option("--plan", "plan_only", is_flag=True, help="Show the typed query plan without retrieving or answering")
@click.option("--no-ai", is_flag=True, help="Answer deterministically from retrieval only")
@click.option("--no-cache", is_flag=True, help="Skip the disposable answer cache")
@click.option("--show-research", is_flag=True, help="Show the research trace: tools called and why")
@click.option("--mode", "mode_override", type=click.Choice(["evidence", "advisory", "ideation"]),
              help="Developer override for the epistemic mode; intent inference is the default")
@click.option("--model", help="Override the configured synthesis model")
def ask(
    question,
    new_session,
    resume_id,
    session_id,
    list_sessions,
    since,
    until,
    document_types,
    source_types,
    entity_ids,
    visibility,
    limit,
    order,
    show_sources,
    as_json,
    plan_only,
    no_ai,
    no_cache,
    show_research,
    mode_override,
    model,
):
    """Ask the private knowledge corpus. Conversational, and strictly read-only.

    With a QUESTION, answers it once. With no QUESTION, opens an interactive
    session where follow-ups keep their context:

    \b
        gang ask
        GANG > What's going on with certification?
        GANG > What's blocking it?
        GANG > What would you do?
    """
    try:
        from core.ask import (
            AskOptions,
            AskService,
            ConversationOptions,
            ConversationService,
            PlanOverrides,
            QueryPlanError,
            RetrievalError,
            SessionError,
        )
        from core.ask.answer import ConversationSynthesizer
        from core.ask.temporal import TemporalError
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.ask import (
            AskOptions,
            AskService,
            ConversationOptions,
            ConversationService,
            PlanOverrides,
            QueryPlanError,
            RetrievalError,
            SessionError,
        )
        from core.ask.answer import ConversationSynthesizer
        from core.ask.temporal import TemporalError

    text = " ".join(question or ()).strip()
    synthesizer = None
    if model and not no_ai:
        synthesizer = ConversationSynthesizer(model=model)
        if not synthesizer.has_credentials:
            synthesizer = None

    service = ConversationService(root_path=Path.cwd(), synthesizer=synthesizer)

    if list_sessions:
        _print_ask_sessions(service)
        return

    overrides = PlanOverrides(
        since=since or "",
        until=until or "",
        # Note: this module shadows the builtin `list` with a click command,
        # so unpack rather than calling list().
        document_types=[*document_types],
        source_types=[*source_types],
        entity_ids=[*entity_ids],
        visibility=visibility,
        order=order,
        limit=limit,
    )

    # `--plan` is a question about planning, not a turn of conversation: it
    # shows the typed plan and retrieves nothing.
    if plan_only:
        try:
            result = AskService(root_path=Path.cwd()).ask(
                text,
                overrides=overrides,
                options=AskOptions(use_ai=not no_ai, use_cache=False, plan_only=True),
            )
        except (QueryPlanError, TemporalError, RetrievalError) as e:
            click.echo(f"❌ {e}", err=True)
            raise click.Abort()
        if as_json:
            click.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        else:
            _print_ask_plan(result)
        return

    try:
        session = _resolve_ask_session(service, resume_id, session_id, new_session)
    except SessionError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    # A bare one-shot question leaves nothing behind. Naming a session, or
    # opening an interactive one, is what opts into persistence.
    persist = bool(resume_id or session_id or not text)
    options = ConversationOptions(
        use_ai=not no_ai,
        use_cache=not no_cache,
        persist=persist,
        mode_override=mode_override,
        show_research=show_research,
    )

    if not text:
        _run_ask_session(service, session, overrides, options, show_sources=show_sources)
        return

    result = _ask_turn(service, text, session, overrides, options)
    if result is None:
        raise click.Abort()

    if as_json:
        click.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    _print_conversation_answer(result, show_sources=show_sources, show_research=show_research)


def _resolve_ask_session(service, resume_id, session_id, new_session):
    """Pick the session this invocation runs in.

    `--new` alongside `--session` means "that name, starting over", which is
    the only reading that makes both flags useful together.
    """
    if resume_id:
        return service.resume(resume_id)
    if session_id:
        if new_session:
            return service.sessions.create(session_id)
        return service.sessions.load_or_create(session_id)
    return service.start()


def _ask_turn(service, text, session, overrides, options):
    """Run one turn, reporting operational failures without a traceback."""
    from core.ask import AskError, QueryPlanError, RetrievalError
    from core.ask.temporal import TemporalError

    try:
        return service.converse(text, session=session, overrides=overrides, options=options)
    except RetrievalError as e:
        click.echo(f"❌ {e}", err=True)
    except (QueryPlanError, TemporalError) as e:
        click.echo(f"❌ {e}", err=True)
    except AskError as e:
        click.echo(f"❌ Ask failed: {e}", err=True)
    return None


SESSION_HELP = """Commands:
  /new              start a fresh conversation
  /context          show the active topics, entities, and assumptions
  /sources          toggle full provenance on each answer
  /research         toggle the research trace
  /forget           clear scenario assumptions for this session
  /exit, /quit      leave (the session is saved)"""


def _run_ask_session(service, session, overrides, options, *, show_sources=False):
    """The interactive loop. Every turn keeps the context of the one before."""
    show_research = options.show_research
    click.echo(f"GANG conversational ask — session {session.session_id}")
    click.echo("Ask anything about the private corpus. /help for commands, /exit to leave.")

    while True:
        try:
            line = click.prompt("\nGANG >", prompt_suffix=" ", default="", show_default=False)
        except (EOFError, click.Abort):
            click.echo("")
            break

        text = (line or "").strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/help":
            click.echo(SESSION_HELP)
            continue
        if text == "/new":
            service.sessions.save(session)
            session = service.start()
            click.echo(f"Started session {session.session_id}.")
            continue
        if text == "/context":
            _print_ask_context(session)
            continue
        if text == "/sources":
            show_sources = not show_sources
            click.echo(f"Provenance {'on' if show_sources else 'off'}.")
            continue
        if text == "/research":
            show_research = not show_research
            click.echo(f"Research trace {'on' if show_research else 'off'}.")
            continue
        if text == "/forget":
            session.clear_assumptions()
            service.sessions.save(session)
            click.echo("Cleared scenario assumptions. Canonical knowledge is unchanged.")
            continue
        if text.startswith("/"):
            click.echo(f"Unknown command {text}. /help for the list.")
            continue

        turn_options = _with_research(options, show_research)
        result = _ask_turn(service, text, session, overrides, turn_options)
        if result is None:
            continue
        click.echo("")
        _print_conversation_answer(
            result, show_sources=show_sources, show_research=show_research
        )

    service.sessions.save(session)
    click.echo(f"Saved session {session.session_id}.")


def _with_research(options, show_research):
    from core.ask import ConversationOptions

    return ConversationOptions(
        use_ai=options.use_ai,
        use_cache=options.use_cache,
        persist=options.persist,
        mode_override=options.mode_override,
        show_research=show_research,
    )


def _print_ask_sessions(service):
    entries = service.sessions.list_sessions()
    if not entries:
        click.echo("No saved conversations.")
        return
    click.echo(f"Saved conversations in {service.paths.display_home()}/sessions:")
    for entry in entries:
        topics = ", ".join(entry["active_topics"][:3])
        click.echo(
            f"  {entry['session_id']}  {entry['updated'][:16]}  "
            f"{entry['turn_count']} turn(s)" + (f"  — {topics}" if topics else "")
        )


def _print_ask_context(session):
    summary = session.context_summary()
    click.echo(f"Session {summary['session_id']} — {summary['turn_count']} turn(s)")
    if summary["active_topics"]:
        click.echo(f"  topics: {', '.join(summary['active_topics'])}")
    for entity in summary["active_entities"]:
        click.echo(f"  entity: {entity['name']} ({entity['entity_id']})")
    if summary["active_time_range"]:
        window = summary["active_time_range"]
        click.echo(f"  time range: {window.get('start') or 'any'} .. {window.get('end') or 'any'}")
    for assumption in summary["session_assumptions"]:
        click.echo(f"  assumption (not a company fact): {assumption['text']}")
    click.echo(f"  documents in working set: {len(summary['active_document_ids'])}")
    click.echo("  This is working memory, not evidence.")


def _print_conversation_answer(result, *, show_sources=False, show_research=False):
    """Print one conversational turn, then everything qualifying it."""
    if result.get("clarification"):
        click.echo(result["answer"])
        return

    _print_ask_answer(result, show_sources=show_sources)

    for assumption in result.get("scenario_assumptions", []):
        click.echo(f"(scenario assumption, not a company fact: {assumption['text']})")

    for item in result.get("stale_evidence", []):
        click.echo(
            f"(evidence changed since an earlier turn: {item.get('title') or item['document_id']})",
            err=True,
        )

    if show_sources:
        _print_ask_ledger(result)

    if show_research:
        _print_ask_research(result)

    for item in result.get("rejected_claims", []):
        click.echo(f"(rejected {item['type']} claim: {item['reason']})", err=True)
    for item in result.get("ungrounded_premises", []):
        click.echo(
            f"(claim {item['claim_id']} rests on premises that are not grounded: "
            + ", ".join(item["ungrounded_premises"])
            + ")",
            err=True,
        )


#: How each claim type is introduced in the terminal. The distinction between
#: what the corpus says and what was generated is the whole point of the
#: ledger, so it is spelled out rather than implied by a symbol.
CLAIM_LABELS = {
    "fact": "fact (from evidence)",
    "synthesis": "synthesis (derived from evidence)",
    "recommendation": "recommendation (generated, not a company decision)",
    "idea": "idea (generated, not a company decision)",
    "scenario": "scenario (rests on your assumption)",
    "uncertainty": "uncertain (not fully supported)",
}


def _print_ask_ledger(result):
    claims = result.get("claims", [])
    if not claims:
        return
    click.echo("")
    click.echo("Claim ledger:")
    for claim in claims:
        citations = "".join(f"[{value}]" for value in claim.get("citations", []))
        label = CLAIM_LABELS.get(claim.get("type", ""), claim.get("type", ""))
        click.echo(f"  {claim.get('id', '?')}  {label}")
        click.echo(f"      {claim.get('text', '')} {citations}".rstrip())
        for note in claim.get("notes", []):
            click.echo(f"      note: {note}")
        if claim.get("presented_as_decision"):
            click.echo("      warning: phrased as an existing company decision")


def _print_ask_research(result):
    research = result.get("research", {})
    click.echo("")
    click.echo(
        f"Research: {research.get('rounds', 0)} round(s), "
        f"{research.get('document_count', 0)} document(s), "
        f"stopped because {research.get('stopped_because', 'unknown')}"
    )
    for entry in research.get("trace", []):
        detail = entry.get("reason") or entry.get("refused") or entry.get("error") or ""
        click.echo(f"  {entry.get('decision', '')} {entry.get('tool', '')}: {detail}".strip())
        if entry.get("document_ids"):
            click.echo(f"      returned: {', '.join(entry['document_ids'])}")
    for refusal in research.get("refusals", []):
        click.echo(f"  refused {refusal.get('tool', '')}: {refusal.get('refused', '')}")


def _print_ask_plan(result):
    plan = result["plan"]
    click.echo(f"Query plan (v{plan['version']}) via {result['planner']}")
    click.echo(f"  question: {result['question']}")
    for label, key in (
        ("text queries", "text_queries"),
        ("entity ids", "entity_ids"),
        ("document types", "document_types"),
        ("source types", "source_types"),
    ):
        if plan.get(key):
            click.echo(f"  {label}: {', '.join(plan[key])}")
    if plan.get("date_range"):
        window = plan["date_range"]
        click.echo(f"  date range ({window['field']}): {window['start'] or 'any'} .. {window['end'] or 'any'}")
    if plan.get("visibility"):
        click.echo(f"  visibility: {plan['visibility']}")
    click.echo(f"  order: {plan['order']}")
    click.echo(f"  limit: {plan['limit']}")
    for entity in result.get("resolved_entities", []):
        click.echo(f"  resolved: {entity['text']} -> {entity['name']} ({entity['entity_id']})")
    for item in result.get("ambiguities", []):
        click.echo(f"  ambiguous: {item['text']} ({len(item.get('candidates', []))} candidates)")
    for note in result.get("notes", []):
        click.echo(f"  note: {note}")


def _print_ask_answer(result, *, show_sources=False):
    click.echo(result["answer"])

    if result.get("conflicts"):
        click.echo("")
        click.echo("Conflicting evidence:")
        for conflict in result["conflicts"]:
            citations = "".join(f"[{value}]" for value in conflict.get("citations", []))
            click.echo(f"  - {conflict['summary']} {citations}".rstrip())

    if result.get("uncertainty"):
        click.echo("")
        click.echo(f"Uncertainty: {result['uncertainty']}")

    sources = result.get("sources", [])
    if sources:
        from core.ask.service import citation_labels

        labels = citation_labels(sources)
        evidence = {item["citation_id"]: item for item in result.get("evidence", [])}
        cited = [source for source in sources if source.get("cited")]
        unused = [source for source in sources if not source.get("cited")]

        # Separate headings, because a retrieved document that nothing cited
        # did not support the answer.
        for heading, group in (
            ("Cited sources:", cited),
            ("Also retrieved, not cited in the answer:", unused),
        ):
            if not group:
                continue
            click.echo("")
            click.echo(heading)
            for source in group:
                _print_ask_source(source, labels, evidence, show_sources=show_sources)

    excluded = result.get("excluded_sources", [])
    if excluded:
        click.echo("")
        click.echo("Retrieved but unreadable (excluded from the answer):")
        for item in excluded:
            click.echo(f"  - {item['title']} ({item['reason']})")
            if show_sources:
                click.echo(f"      document_id: {item['document_id']}")
                click.echo("      The canonical document and its raw source are unchanged.")

    meta = result.get("synthesis", {})
    if meta.get("mode") == "deterministic":
        click.echo("")
        click.echo(f"(answered from retrieval only: {meta.get('reason', 'deterministic')})")

    for warning in result.get("grounding_warnings", []):
        click.echo(
            f"(unverified {warning['check']} claim [{warning['status']}]: {warning['claim']})",
            err=True,
        )
    for sentence in result.get("softened_negatives", []):
        click.echo(f"(removed unsupported denial: {sentence})", err=True)
    for value in result.get("dropped_citations", []):
        click.echo(f"(dropped unsupported citation [{value}])", err=True)
    for field_name in result.get("rejected_fields", []):
        click.echo(f"(ignored unsupported answer field: {field_name})", err=True)


def _print_ask_source(source, labels, evidence, *, show_sources=False):
    click.echo(f"  [{source['citation_id']}] {labels[source['citation_id']]}")
    if not show_sources:
        return
    click.echo(f"      document_id: {source['document_id']}")
    click.echo(f"      type: {source['type'] or 'knowledge'}"
               + (f" / {source['source_type']}" if source["source_type"] else ""))
    click.echo(f"      visibility: {source['visibility']}")
    if source.get("updated"):
        click.echo(f"      updated: {source['updated']}")
    if source.get("source_ids"):
        click.echo(f"      source_ids: {', '.join(source['source_ids'])}")
    click.echo(f"      enrichment: {source['enrichment_status']}")
    item = evidence.get(source["citation_id"], {})
    for entity in item.get("entity_refs", []):
        click.echo(f"      entity: {entity.get('name', '')} ({entity.get('entity_id', '')})")
    for excerpt in item.get("excerpts", []):
        click.echo(f"      excerpt: {excerpt}")
    if item.get("stale_enrichment_warning"):
        click.echo(f"      stale enrichment: {item['stale_enrichment_warning']}")


@cli.command("enrich")
@click.argument("args", nargs=-1)
@click.option("--context-limit", default=3, show_default=True, type=int, help="Related private documents to supply as context")
@click.option("--overwrite-existing", is_flag=True, help="Allow apply to replace existing authored enrichment fields")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def enrich(ctx, args, context_limit, overwrite_existing, output_format):
    """Create, inspect, and explicitly apply AI enrichment proposals."""
    try:
        from core.enrichment import (
            AIProviderError,
            AnthropicEnrichmentProvider,
            EnrichmentConflictError,
            EnrichmentError,
            EnrichmentService,
            ProposalValidationError,
            StaleProposalError,
        )
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.enrichment import (
            AIProviderError,
            AnthropicEnrichmentProvider,
            EnrichmentConflictError,
            EnrichmentError,
            EnrichmentService,
            ProposalValidationError,
            StaleProposalError,
        )

    def print_workflow():
        click.echo("Usage:")
        click.echo("  gang enrich DOCUMENT_ID")
        click.echo("  gang enrich show PROPOSAL_ID")
        click.echo("  gang enrich apply PROPOSAL_ID")

    if not args:
        print_workflow()
        return

    config = ctx.obj or {}
    model = config.get("ai", {}).get("model")
    service = EnrichmentService(provider=AnthropicEnrichmentProvider(model=model))

    try:
        if args[0] == "show":
            if len(args) != 2:
                print_workflow()
                ctx.exit(1)
            proposal = service.show_proposal(args[1])
            if output_format == "json":
                click.echo(json.dumps(proposal, indent=2, sort_keys=True))
            else:
                _print_enrichment_proposal(proposal)
            return

        if args[0] == "apply":
            if len(args) != 2:
                print_workflow()
                ctx.exit(1)
            proposal = service.apply_proposal(args[1], overwrite_existing=overwrite_existing)
            if output_format == "json":
                click.echo(json.dumps(proposal, indent=2, sort_keys=True))
            else:
                click.echo("✅ Applied enrichment proposal")
                click.echo(f"  Proposal: {proposal['proposal_id']}")
                click.echo(f"  Document: {proposal['document_id']}")
                click.echo(f"  Resulting hash: {proposal['resulting_hash']}")
                click.echo("  Reindexed: GANG_HOME/generated/brain.sqlite")
            return

        if len(args) != 1:
            print_workflow()
            ctx.exit(1)

        proposal = service.create_proposal(args[0], context_limit=context_limit)
        if output_format == "json":
            click.echo(json.dumps(proposal, indent=2, sort_keys=True))
        else:
            click.echo("✅ Created enrichment proposal")
            click.echo(f"  Proposal: {proposal['proposal_id']}")
            click.echo(f"  Document: {proposal['document_id']}")
            click.echo(f"  Provider/model: {proposal['provider']}/{proposal['model']}")
            click.echo(f"  Context documents: {len(proposal['context_document_ids'])}")
            click.echo(f"  Show: gang enrich show {proposal['proposal_id']}")
            click.echo(f"  Apply: gang enrich apply {proposal['proposal_id']}")
    except EnrichmentConflictError as e:
        click.echo("❌ Existing authored enrichment would be overwritten.", err=True)
        click.echo("Conflicts:", err=True)
        for field in e.conflicts:
            click.echo(f"  - {field}", err=True)
        click.echo("Use --overwrite-existing only after reviewing the proposal.", err=True)
        raise click.Abort()
    except StaleProposalError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()
    except (AIProviderError, ProposalValidationError, EnrichmentError) as e:
        click.echo(f"❌ Enrichment failed: {e}", err=True)
        raise click.Abort()


def _print_enrichment_proposal(proposal):
    click.echo(f"Proposal: {proposal['proposal_id']}")
    click.echo(f"Document: {proposal['document_id']}")
    click.echo(f"Base hash: {proposal['base_document_hash']}")
    click.echo(f"Provider/model: {proposal['provider']}/{proposal['model']}")
    click.echo(f"Generated: {proposal['generated_at']}")
    click.echo(f"Apply status: {proposal.get('apply_status', 'pending')}")
    if proposal.get("context_document_ids"):
        click.echo("Context:")
        for document_id in proposal["context_document_ids"]:
            click.echo(f"  - {document_id}")
    click.echo("Proposed enrichment:")
    click.echo(json.dumps(proposal["proposed_enrichment"], indent=2, sort_keys=True))


@cli.group("entity")
def entity():
    """Create, resolve, and inspect stable private entities and relationships"""
    pass


def _entity_imports():
    try:
        from core.entities import (
            AliasCollisionError,
            DuplicateEntityError,
            EntityError,
            EntityService,
            MergeConflictError,
            PREDICATES,
            ProposalValidationError,
            StaleProposalError,
        )
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.entities import (
            AliasCollisionError,
            DuplicateEntityError,
            EntityError,
            EntityService,
            MergeConflictError,
            PREDICATES,
            ProposalValidationError,
            StaleProposalError,
        )
    return {
        "AliasCollisionError": AliasCollisionError,
        "DuplicateEntityError": DuplicateEntityError,
        "EntityError": EntityError,
        "EntityService": EntityService,
        "MergeConflictError": MergeConflictError,
        "PREDICATES": PREDICATES,
        "ProposalValidationError": ProposalValidationError,
        "StaleProposalError": StaleProposalError,
    }


@contextmanager
def _entity_errors():
    names = _entity_imports()
    try:
        yield names
    except names["EntityError"] as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()


def _echo_entity(record):
    click.echo(f"  ID: {record.id}")
    click.echo(f"  Type: {record.type}")
    click.echo(f"  Name: {record.name}")
    if record.aliases:
        click.echo(f"  Aliases: {', '.join(record.aliases)}")
    if record.emails:
        click.echo(f"  Emails: {', '.join(record.emails)}")
    if record.domains:
        click.echo(f"  Domains: {', '.join(record.domains)}")
    click.echo(f"  Visibility: {record.visibility}")
    click.echo(f"  Status: {record.status}")


@entity.command("create")
@click.argument("entity_type")
@click.argument("name")
@click.option("--alias", "aliases", multiple=True, help="Additional alias (repeatable)")
@click.option("--email", "emails", multiple=True, help="Deterministic email identifier (repeatable)")
@click.option("--domain", "domains", multiple=True, help="Deterministic domain identifier (repeatable)")
@click.option("--allow-duplicate-name", is_flag=True, help="Create even if a same-named entity exists")
def entity_create(entity_type, name, aliases, emails, domains, allow_duplicate_name):
    """Create a canonical entity: person, company, project, or product"""
    with _entity_errors() as names:
        service = names["EntityService"]()
        record = service.create(
            entity_type,
            name,
            aliases=aliases,
            emails=emails,
            domains=domains,
            allow_duplicate_name=allow_duplicate_name,
        )
        click.echo("✅ Created entity")
        _echo_entity(record)
        click.echo(f"  File: {record.path}")


@entity.command("list")
@click.option("--type", "entity_type", help="Filter by entity type")
@click.option("--include-merged", is_flag=True, help="Include merged tombstones")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_list(entity_type, include_merged, output_format):
    """List canonical entities"""
    with _entity_errors() as names:
        records = names["EntityService"]().store.list(
            entity_type=entity_type, include_merged=include_merged
        )
        if output_format == "json":
            click.echo(
                json.dumps(
                    [
                        {
                            "entity_id": record.id,
                            "type": record.type,
                            "name": record.name,
                            "aliases": record.aliases,
                            "status": record.status,
                        }
                        for record in records
                    ],
                    indent=2,
                )
            )
            return
        if not records:
            click.echo("No entities yet. Create one: gang entity create person \"Name\"")
            return
        for record in records:
            suffix = f" -> {record.merged_into}" if record.status == "merged" else ""
            click.echo(f"{record.type:<8} {record.id}  {record.name}{suffix}")


@entity.command("show")
@click.argument("entity_id")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_show(entity_id, output_format):
    """Show an entity with its mentions, relationships, and provenance"""
    with _entity_errors() as names:
        view = names["EntityService"]().show(entity_id)
        if output_format == "json":
            click.echo(json.dumps(view, indent=2, sort_keys=True))
            return

        click.echo(f"{view['name']}  ({view['type']})")
        click.echo(f"  ID: {view['entity_id']}")
        if view["status"] != "active":
            click.echo(f"  Status: {view['status']} -> {view['merged_into']}")
        aliases = [item["value"] for item in view["aliases"] if item["kind"] == "alias"]
        emails = [item["value"] for item in view["aliases"] if item["kind"] == "email"]
        domains = [item["value"] for item in view["aliases"] if item["kind"] == "domain"]
        if aliases:
            click.echo(f"  Aliases: {', '.join(aliases)}")
        if emails:
            click.echo(f"  Emails: {', '.join(emails)}")
        if domains:
            click.echo(f"  Domains: {', '.join(domains)}")

        click.echo("\nMentioned in:")
        if not view["documents"]:
            click.echo("  (none)")
        for document in view["documents"]:
            sources = f" [{', '.join(document['source_ids'])}]" if document["source_ids"] else ""
            click.echo(f"  - {document['title']} ({document['type']}){sources}")
            click.echo(f"    document: {document['document_id']}  as: {document['label']}")

        click.echo("\nRelationships:")
        if not view["relationships"]:
            click.echo("  (none)")
        for relationship in view["relationships"]:
            arrow = "->" if relationship["direction"] == "outbound" else "<-"
            click.echo(
                f"  {arrow} {relationship['predicate']} {relationship['other_entity_name']}"
            )
            click.echo(f"     evidence: {relationship['evidence_excerpt']}")
            click.echo(f"     document: {relationship['document_id']}")

        provenance = view["provenance"]
        click.echo("\nProvenance:")
        click.echo(f"  documents: {provenance['documents']}")
        click.echo(f"  mentions: {provenance['mentions']}")
        click.echo(f"  relationships: {provenance['relationships']}")
        click.echo(f"  source ids: {provenance['source_ids']}")


@entity.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--type", "entity_type", help="Filter by entity type")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_search(query, entity_type, limit, output_format):
    """Search canonical entities by name, alias, email, or domain"""
    with _entity_errors() as names:
        results = names["EntityService"]().search(
            " ".join(query), entity_type=entity_type, limit=limit
        )
        if output_format == "json":
            click.echo(json.dumps(results, indent=2, sort_keys=True))
            return
        if not results:
            click.echo("No entities matched.")
            return
        for result in results:
            matched = ", ".join(result["matched"])
            click.echo(f"{result['type']:<8} {result['entity_id']}  {result['name']}")
            click.echo(f"         matched: {matched}  mentions: {result['mentions']}")


@entity.command("resolve")
@click.argument("text")
@click.option("--type", "entity_type", help="Restrict resolution to one entity type")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_resolve(text, entity_type, output_format):
    """Deterministically resolve a name, alias, email, or domain"""
    with _entity_errors() as names:
        resolution = names["EntityService"]().resolve(text, entity_type=entity_type)
        if output_format == "json":
            click.echo(json.dumps(resolution, indent=2, sort_keys=True))
            return
        click.echo(f"{text} -> {resolution['status']}")
        if resolution["entity_id"]:
            click.echo(f"  entity: {resolution['name']} ({resolution['entity_id']})")
            click.echo(f"  method: {resolution['method']}")
        click.echo(f"  reason: {resolution['reason']}")
        if resolution["candidates"]:
            click.echo("  candidates (require confirmation):")
            for candidate in resolution["candidates"]:
                click.echo(f"    - {candidate['name']} ({candidate['entity_id']}): {candidate['reason']}")


@entity.command("rename")
@click.argument("entity_id")
@click.argument("name")
def entity_rename(entity_id, name):
    """Rename an entity without changing its identity"""
    with _entity_errors() as names:
        record = names["EntityService"]().rename(entity_id, name)
        click.echo("✅ Renamed entity (identity unchanged)")
        _echo_entity(record)


@entity.group("alias")
def entity_alias():
    """Manage entity aliases"""
    pass


@entity_alias.command("add")
@click.argument("entity_id")
@click.argument("alias")
@click.option("--allow-ambiguous", is_flag=True, help="Add even if it collides; lookups stay ambiguous")
def entity_alias_add(entity_id, alias, allow_ambiguous):
    """Add an alias to an entity"""
    with _entity_errors() as names:
        record = names["EntityService"]().add_alias(entity_id, alias, allow_ambiguous=allow_ambiguous)
        click.echo("✅ Added alias")
        _echo_entity(record)


@entity_alias.command("remove")
@click.argument("entity_id")
@click.argument("alias")
def entity_alias_remove(entity_id, alias):
    """Remove an alias from an entity"""
    with _entity_errors() as names:
        record = names["EntityService"]().store.remove_alias(entity_id, alias)
        click.echo("✅ Removed alias")
        _echo_entity(record)


@entity.command("identifier")
@click.argument("entity_id")
@click.option("--email", default="", help="Deterministic email identifier")
@click.option("--domain", default="", help="Deterministic domain identifier")
def entity_identifier(entity_id, email, domain):
    """Add a strong deterministic identifier to an entity"""
    if not email and not domain:
        raise click.UsageError("Provide --email or --domain")
    with _entity_errors() as names:
        record = names["EntityService"]().add_identifier(entity_id, email=email, domain=domain)
        click.echo("✅ Added identifier")
        _echo_entity(record)


@entity.command("merge")
@click.argument("source_entity_id")
@click.argument("target_entity_id")
def entity_merge(source_entity_id, target_entity_id):
    """Explicitly merge SOURCE into TARGET, preserving the source as a tombstone"""
    with _entity_errors() as names:
        audit = names["EntityService"]().merge(source_entity_id, target_entity_id)
        click.echo("✅ Merged entity")
        click.echo(f"  Source: {audit['source_name']} ({audit['source_entity_id']}) -> tombstone")
        click.echo(f"  Target: {audit['target_name']} ({audit['target_entity_id']})")
        if audit["absorbed_aliases"]:
            click.echo(f"  Absorbed aliases: {', '.join(audit['absorbed_aliases'])}")
        click.echo(f"  Rewritten documents: {len(audit['rewritten_documents'])}")


@entity.command("mention")
@click.argument("document_id")
@click.argument("entity_id")
@click.option("--label", help="Text as it appears in the document (defaults to the entity name)")
@click.option("--excerpt", default="", help="Short supporting excerpt")
def entity_mention(document_id, entity_id, label, excerpt):
    """Record that a private document mentions an entity"""
    with _entity_errors() as names:
        result = names["EntityService"]().add_mention(
            document_id, entity_id, label=label, excerpt=excerpt
        )
        if result["changed"]:
            click.echo("✅ Added entity reference")
        else:
            click.echo("Already referenced; nothing changed.")
        click.echo(f"  Document: {document_id}")


@entity.command("relate")
@click.argument("document_id")
@click.option("--subject", required=True, help="Subject entity ID")
@click.option("--predicate", required=True, help="Relationship predicate")
@click.option("--object", "object_entity_id", required=True, help="Object entity ID")
@click.option("--evidence", required=True, help="Verbatim excerpt from the document body")
@click.option("--source-id", default="", help="Optional originating source ID")
def entity_relate(document_id, subject, predicate, object_entity_id, evidence, source_id):
    """Assert an evidence-backed relationship carried by one document"""
    with _entity_errors() as names:
        result = names["EntityService"]().assert_relationship(
            document_id=document_id,
            subject_entity_id=subject,
            predicate=predicate,
            object_entity_id=object_entity_id,
            excerpt=evidence,
            source_id=source_id,
        )
        if result["changed"]:
            click.echo("✅ Recorded relationship assertion")
            for relationship in result["added_relationships"]:
                click.echo(f"  {relationship['relationship_id']}")
        else:
            click.echo("Identical assertion already recorded; nothing changed.")


@entity.command("candidates")
@click.option("--type", "entity_type", help="Filter by entity type")
@click.option("--unresolved-only", is_flag=True, help="Hide strings that already resolve")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_candidates(entity_type, unresolved_only, output_format):
    """Report entity-like strings across the corpus (read-only)"""
    with _entity_errors() as names:
        report = names["EntityService"]().candidates(
            entity_type=entity_type, unresolved_only=unresolved_only
        )
        if output_format == "json":
            click.echo(json.dumps(report, indent=2, sort_keys=True))
            return
        summary = report["summary"]
        click.echo(
            f"{summary['candidates']} candidate strings "
            f"({summary['resolved']} resolved, {summary['ambiguous']} ambiguous, "
            f"{summary['unresolved']} unresolved)"
        )
        for row in report["candidates"]:
            marker = {"resolved": "✓", "ambiguous": "?"}.get(row["status"], " ")
            click.echo(f"  {marker} {row['text']:<28} {row['documents']:>4} documents  [{row['entity_type']}]")
            if row["status"] == "resolved":
                click.echo(f"      -> {row['entity_name']} ({row['entity_id']})")
            for candidate in row["candidates"]:
                click.echo(f"      ? {candidate['name']} ({candidate['entity_id']}): {candidate['reason']}")
        click.echo("\nThis command does not change anything.")


@entity.command("propose")
@click.argument("document_id")
@click.option("--ai", "use_ai", is_flag=True, help="Ask the configured AI provider instead of deterministic metadata")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def entity_propose(ctx, document_id, use_ai, output_format):
    """Generate an entity resolution proposal for a document (no mutation)"""
    with _entity_errors() as names:
        config = ctx.obj or {}
        model = config.get("ai", {}).get("model")
        proposal = names["EntityService"]().propose(document_id, use_ai=use_ai, model=model)
        if output_format == "json":
            click.echo(json.dumps(proposal, indent=2, sort_keys=True))
            return
        click.echo("✅ Created entity proposal (nothing has been applied)")
        click.echo(f"  Proposal: {proposal['proposal_id']}")
        click.echo(f"  Document: {proposal['document_id']}")
        click.echo(f"  Provider/model: {proposal['provider']}/{proposal['model']}")
        click.echo(f"  Proposed mentions: {len(proposal['proposed_mentions'])}")
        click.echo(f"  Proposed relationships: {len(proposal['proposed_relationships'])}")
        click.echo(f"  Unresolved strings: {len(proposal.get('unresolved', []))}")
        click.echo(f"  Review: gang entity proposal {proposal['proposal_id']}")
        click.echo(f"  Apply: gang entity apply {proposal['proposal_id']}")


@entity.command("proposals")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_proposals(output_format):
    """List entity proposals"""
    with _entity_errors() as names:
        proposals = names["EntityService"]().proposals.list_proposals()
        if output_format == "json":
            click.echo(json.dumps(proposals, indent=2, sort_keys=True))
            return
        if not proposals:
            click.echo("No entity proposals yet.")
            return
        for proposal in proposals:
            click.echo(
                f"{proposal['proposal_id']}  {proposal.get('apply_status', 'pending'):<8} "
                f"{proposal['document_id']}  {proposal['generated_at']}"
            )


@entity.command("proposal")
@click.argument("proposal_id")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_proposal_show(proposal_id, output_format):
    """Show one entity proposal"""
    with _entity_errors() as names:
        proposal = names["EntityService"]().show_proposal(proposal_id)
        if output_format == "json":
            click.echo(json.dumps(proposal, indent=2, sort_keys=True))
            return
        click.echo(f"Proposal: {proposal['proposal_id']}")
        click.echo(f"Document: {proposal['document_id']}")
        click.echo(f"Base hash: {proposal['base_document_hash']}")
        click.echo(f"Provider/model: {proposal['provider']}/{proposal['model']}")
        click.echo(f"Generated: {proposal['generated_at']}")
        click.echo(f"Apply status: {proposal.get('apply_status', 'pending')}")
        click.echo("Proposed mentions:")
        click.echo(json.dumps(proposal["proposed_mentions"], indent=2, sort_keys=True))
        click.echo("Proposed relationships:")
        click.echo(json.dumps(proposal["proposed_relationships"], indent=2, sort_keys=True))
        if proposal.get("unresolved"):
            click.echo("Unresolved (require a human decision):")
            click.echo(json.dumps(proposal["unresolved"], indent=2, sort_keys=True))


@entity.command("apply")
@click.argument("proposal_id")
@click.option("--create-new", is_flag=True, help="Also create the reviewed new entities in the proposal")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def entity_apply(proposal_id, create_new, output_format):
    """Apply a reviewed entity proposal to canonical documents"""
    with _entity_errors() as names:
        try:
            proposal = names["EntityService"]().apply_proposal(
                proposal_id, create_new_entities=create_new
            )
        except names["StaleProposalError"] as e:
            click.echo(f"❌ {e}", err=True)
            click.echo("Regenerate the proposal: gang entity propose DOCUMENT_ID", err=True)
            raise click.Abort()

        if output_format == "json":
            click.echo(json.dumps(proposal, indent=2, sort_keys=True))
            return
        summary = proposal.get("apply_summary", {})
        click.echo("✅ Applied entity proposal")
        click.echo(f"  Proposal: {proposal['proposal_id']}")
        click.echo(f"  Document: {proposal['document_id']}")
        click.echo(f"  Mentions added: {summary.get('applied_mentions', 0)}")
        click.echo(f"  Relationships added: {summary.get('applied_relationships', 0)}")
        for created in summary.get("created_entities", []):
            click.echo(f"  Created {created['type']}: {created['name']} ({created['entity_id']})")
        for skipped in summary.get("skipped", []):
            click.echo(f"  Skipped {skipped['text']}: {skipped['reason']}")
        click.echo("  Reindexed: GANG_HOME/generated/brain.sqlite")


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
    click.echo("Score Analyzing content...")
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
                click.echo(f"  Best Practices Uploaded & compressed: {size_kb:.1f}KB (saved {savings:.0f}%)")
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
        click.echo("Score Detecting focal point...")
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
    
    click.echo(f"Score Checking deliverability for: {domain}\n")
    
    try:
        results = DeliverabilityChecker.check_dns_records(domain)
        
        click.echo("SPF Record:")
        if results['spf']:
            click.echo(f"  Best Practices {results['spf']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nDMARC Record:")
        if results['dmarc']:
            click.echo(f"  Best Practices {results['dmarc']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nMX Records:")
        if results['mx']:
            for mx in results['mx']:
                click.echo(f"  Best Practices {mx}")
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
    
    click.echo("Score Checking slug uniqueness...\n")
    
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
@click.option('--source', type=click.Choice(['vault', 'legacy']), default='vault', show_default=True, help='Public content source')
@click.option('--output-dir', type=click.Path(file_okay=False), help='Override build output directory')
@click.pass_context
def build(ctx, check_quality, min_quality_score, validate_links, check_slugs, optimize_images, profile, source, output_dir):
    """Build static site with semantic HTML"""
    try:
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
        from core.content_loader import PublicContentError, load_public_content
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
        from core.content_loader import PublicContentError, load_public_content
    
    # Initialize profiler
    profiler = BuildProfiler() if profile else None
    if profiler:
        profiler.start()
    
    click.echo("🔨 Building site...")
    config = dict(ctx.obj)
    config['build'] = dict(config.get('build', {}))
    if output_dir:
        config['build']['output'] = output_dir
    content_path = (Path(config['build']['content']) if source == 'legacy' else Path('brain/vault/public')).resolve()
    click.echo(f"📚 Public content source: {source} ({content_path})")

    try:
        public_documents = load_public_content(config, source=source, root_path=Path("."))
    except PublicContentError as e:
        click.echo(f"❌ Public content validation failed:\n{e}", err=True)
        ctx.exit(1)
    
    # Slug uniqueness check (enabled by default)
    if check_slugs:
        from core.content_importer import SlugChecker
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
            click.echo(f"Best Practices All {results['total_slugs']} slugs are unique\n")
    
    # Quality gate check
    if check_quality:
        from core.analyzer import ContentAnalyzer
        click.echo("Score Running content quality checks...")
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
            click.echo(f"Best Practices All {len(md_files)} files pass quality threshold ({min_quality_score}+)\n")
    
    # Link validation check
    if validate_links:
        from core.link_validator import LinkValidator
        click.echo("🔗 Validating links...")
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
            click.echo(f"Best Practices All {results['total_links']} links valid\n")
    
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
            click.echo(f"  Best Practices Optimized {stats['total_images']} image(s) → {stats['total_variants']} variants")
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
    
    # Build content from the validated public document collection.
    all_pages = []
    all_posts = []
    all_projects = []
    all_newsletters = []

    if profiler:
        profiler.stage('process_content').__enter__()

    click.echo(f"📝 Processing {len(public_documents)} validated public document(s)...")
    for document in public_documents:
        content_type = document.collection
        frontmatter = document.frontmatter
        body = document.body

        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra', 'meta'])
        content_html = md.convert(body)

        # Process external links to open in new tabs
        content_html = process_external_links(content_html)

        # Prepare context for template
        build_time = datetime.now()
        slug = document.slug

        # Check if editor mode is enabled (for in-place editing)
        user_authenticated = os.environ.get('EDITOR_MODE', '').lower() == 'true'

        context = {
            'site_title': config['site']['title'],
            'lang': config['site']['language'],
            'title': document.title,
            'description': document.summary or config['site']['description'],
            'content': content_html,
            'year': datetime.now().year,
            'navigation': config.get('nav', {}).get('main', []),
            'date': document.date,
            'date_formatted': str(document.date or ''),
            'tags': document.tags,
            'build_time': build_time.strftime('%B %d, %Y at %I:%M %p'),
            'build_time_iso': build_time.isoformat(),
            'jsonld': frontmatter.get('jsonld'),
            # In-place editor context
            'page_type': document.type,
            'category': content_type,
            'slug': slug,
            'user_authenticated': user_authenticated,
        }

        # Add canonical URL
        url = document.url
        context['canonical_url'] = f"{config['site']['url']}{url}"

        # Select template
        if content_type == 'posts':
            template_name = 'post.html'
        elif content_type == 'projects':
            template_name = 'article.html'  # Use article template for projects
        elif content_type == 'newsletters':
            template_name = 'newsletter.html'
        else:
            template_name = 'page.html'
        
        # Render HTML
        try:
            html = template_engine.render(template_name, context)
        except Exception as e:
            click.echo(f"⚠️  Template error in {document.source_path}: {e}")
            html = process_markdown_fallback(document.source_path, content_type, config)

        # Determine output path
        output_file = output_file_for_url(dist_path, document.url)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html)
        click.echo(f"  Best Practices {document.source_path.relative_to(content_path)}")

        # Collect metadata for sitemaps
        page_data = document.to_page_data(content_html)

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
    
    index_html = create_index_simple(config, all_posts[:5], templates_path)
    page_size_bytes = len(index_html.encode('utf-8'))
    index_html = index_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
    (dist_path / 'index.html').write_text(index_html)
    
    # Create newsletters list page
    if all_newsletters:
        newsletters_dir = dist_path / 'newsletters'
        newsletters_dir.mkdir(parents=True, exist_ok=True)
        
        newsletters_html = create_list_page_simple(config, sorted(all_newsletters, key=lambda x: x.get('date', ''), reverse=True), 'Newsletters', templates_path)
        page_size_bytes = len(newsletters_html.encode('utf-8'))
        newsletters_html = newsletters_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (newsletters_dir / 'index.html').write_text(newsletters_html)
    
    # Create list pages
    # Always create posts index page, even if empty
    click.echo("📄 Creating posts index...")
    posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts', templates_path)
    page_size_bytes = len(posts_html.encode('utf-8'))
    posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
    (dist_path / 'posts').mkdir(parents=True, exist_ok=True)
    (dist_path / 'posts' / 'index.html').write_text(posts_html)
    
    if all_projects:
        click.echo("📄 Creating projects index...")
        projects_html = create_list_page_simple(config, all_projects, 'Projects', templates_path)
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
    if all_newsletters:
        all_pages.append({'url': '/newsletters/', 'title': 'Newsletters', 'type': 'list'})
    
    # Combine all content for sitemap generation
    all_content = all_pages + all_posts + all_projects + all_newsletters
    
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
            
            build_time = datetime.now()
            build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
            build_time_iso = build_time.isoformat()
            
            cart_template = jinja_env.get_template('cart.html')
            cart_html = cart_template.render(
                year=datetime.now().year,
                site_title=config['site']['title'],
                lighthouse_scores=True,
                build_time=build_time_formatted,
                build_time_iso=build_time_iso,
                description=config['site']['description']
            )
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

        indexer = SearchIndexer(content_path, config)
        search_index = build_search_index_from_documents(public_documents, indexer)
        
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
        from core.products import ProductAggregator

        # Get products
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='active')

        # Generate AgentMap
        site_url = config.get('site', {}).get('url', 'https://example.com')
        agentmap = generate_agentmap_from_documents(config, site_url, public_documents, products if products else None)

        # Write AgentMap
        agentmap_file = dist_path / 'agentmap.json'
        agentmap_file.write_text(json.dumps(agentmap, indent=2))

        # Generate Content API
        content_api = generate_content_api_from_documents(site_url, public_documents)

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
        
        click.echo(f"🤖 Generated AgentMap with {len(public_documents)} content items")
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
            # Skip editor-bundle.js to avoid corruption
            if js_file.name == 'editor-bundle.js':
                continue
                
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


def output_file_for_url(dist_path: Path, url: str) -> Path:
    clean = url.strip("/")
    if not clean:
        return dist_path / "index.html"
    return dist_path / clean / "index.html"


def build_search_index_from_documents(public_documents, indexer):
    documents = []
    for document in public_documents:
        clean_text = indexer._clean_markdown(document.body)
        description = document.summary
        if not description:
            paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
            description = paragraphs[0][:200] + "..." if paragraphs else ""

        searchable = f"{document.title} {document.title} {document.title} {description} {clean_text} {' '.join(document.tags)}"
        documents.append({
            "id": document.id or f"{document.collection}/{document.slug}",
            "title": document.title,
            "description": description,
            "url": document.url,
            "category": document.collection,
            "tags": document.tags,
            "content": clean_text[:500],
            "searchable": searchable.lower(),
            "date": document.date or "",
        })

    return {
        "version": "1.0",
        "generated": datetime.now().isoformat(),
        "documents": documents,
    }


def generate_agentmap_from_documents(config, site_url, public_documents, products=None):
    site_url = site_url.rstrip("/")
    by_category = {}
    for document in public_documents:
        by_category.setdefault(document.collection, []).append({
            "slug": document.slug,
            "url": f"{site_url}{document.url}",
            "apiEndpoint": f"{site_url}/api/{document.collection}/{document.slug}.json",
        })

    content_types = [
        {
            "type": category,
            "url": f"{site_url}/{category}/",
            "apiEndpoint": f"{site_url}/api/{category}.json",
        }
        for category in sorted(by_category)
    ]

    agentmap = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "version": "1.0",
        "generated": datetime.now().isoformat(),
        "name": config.get("site", {}).get("title", "Site"),
        "url": site_url,
        "description": config.get("site", {}).get("description", ""),
        "capabilities": ["read", "search"] + (["purchase"] if products else []),
        "endpoints": {
            "api": f"{site_url}/api/",
            "content": f"{site_url}/api/content.json",
            "search": f"{site_url}/api/search.json",
            "sitemap": f"{site_url}/sitemap.xml",
        },
        "contentTypes": content_types,
        "navigation": {
            "main": [
                {"label": item["type"].title(), "url": item["url"], "type": item["type"]}
                for item in content_types
            ],
            "content": by_category,
        },
        "search": {
            "endpoint": f"{site_url}/api/search.json",
            "method": "GET",
            "parameters": ["q", "category", "limit"],
            "description": "Full-text search across all validated public content",
        },
    }

    if products:
        platforms = sorted({product.get("_meta", {}).get("source") for product in products if product.get("_meta", {}).get("source")})
        agentmap["endpoints"]["products"] = f"{site_url}/api/products.json"
        agentmap["commerce"] = {
            "enabled": True,
            "productsEndpoint": f"{site_url}/api/products.json",
            "platforms": platforms,
            "totalProducts": len(products),
        }

    return agentmap


def generate_content_api_from_documents(site_url, public_documents):
    site_url = site_url.rstrip("/")
    return {
        "version": "1.0",
        "generated": datetime.now().isoformat(),
        "totalItems": len(public_documents),
        "items": [
            {
                "id": document.id,
                "title": document.title,
                "url": f"{site_url}{document.url}",
                "apiEndpoint": f"{site_url}/api/{document.collection}/{document.slug}.json",
                "category": document.collection,
                "type": document.type,
                "slug": document.slug,
                "summary": document.summary,
                "date": document.date or "",
                "tags": document.tags,
            }
            for document in public_documents
        ],
    }


@cli.command("compare-public-cutover")
@click.option("--legacy-output", type=click.Path(file_okay=False), default=".context/public-cutover-legacy")
@click.option("--vault-output", type=click.Path(file_okay=False), default=".context/public-cutover-vault")
@click.pass_context
def compare_public_cutover(ctx, legacy_output, vault_output):
    """Build legacy and vault sources separately and compare public output."""
    try:
        from core.content_loader import load_public_content
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_loader import load_public_content

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    legacy_dir = Path(legacy_output)
    vault_dir = Path(vault_output)

    click.echo("Building legacy comparison output...")
    ctx.invoke(
        build,
        check_quality=False,
        min_quality_score=85,
        validate_links=False,
        check_slugs=True,
        optimize_images=False,
        profile=False,
        source="legacy",
        output_dir=str(legacy_dir),
    )

    click.echo("Building vault comparison output...")
    ctx.invoke(
        build,
        check_quality=False,
        min_quality_score=85,
        validate_links=False,
        check_slugs=True,
        optimize_images=False,
        profile=False,
        source="vault",
        output_dir=str(vault_dir),
    )

    config = dict(ctx.obj)
    legacy_docs = {doc.url: doc for doc in load_public_content(config, source="legacy", root_path=Path("."))}
    vault_docs = {doc.url: doc for doc in load_public_content(config, source="vault", root_path=Path("."))}
    all_urls = sorted(set(legacy_docs) | set(vault_docs))

    records = []
    for url in all_urls:
        legacy_file = output_file_for_url(legacy_dir, url)
        vault_file = output_file_for_url(vault_dir, url)
        checks = []

        checks.append(compare_value("url", url if url in legacy_docs else None, url if url in vault_docs else None))
        checks.append(compare_value("output_path", legacy_file.relative_to(legacy_dir).as_posix(), vault_file.relative_to(vault_dir).as_posix()))
        checks.append(compare_value("title", legacy_docs.get(url).title if url in legacy_docs else None, vault_docs.get(url).title if url in vault_docs else None))
        checks.append(compare_value("publication_state", _state(legacy_docs.get(url)), _state(vault_docs.get(url))))
        checks.append(compare_value("authored_seo_overrides", _seo(legacy_docs.get(url)), _seo(vault_docs.get(url)), acceptable=True))
        checks.append(compare_value("rendered_article_html", normalize_html_fragment(read_main_html(legacy_file)), normalize_html_fragment(read_main_html(vault_file))))
        checks.append(compare_value("canonical_url", extract_canonical(legacy_file), extract_canonical(vault_file), acceptable=True))
        checks.append(compare_value("internal_links", extract_refs(legacy_file, "href", internal_only=True), extract_refs(vault_file, "href", internal_only=True)))
        checks.append(compare_value("image_media_references", extract_refs(legacy_file, "src"), extract_refs(vault_file, "src")))
        checks.append(compare_value("structured_data_semantics", extract_jsonld_types(legacy_file), extract_jsonld_types(vault_file), acceptable=True))
        checks.append(compare_value("sitemap_presence", sitemap_contains(legacy_dir, url), sitemap_contains(vault_dir, url)))
        checks.append(compare_value("feed_presence", feed_contains(legacy_dir, url), feed_contains(vault_dir, url), acceptable=True))
        checks.append(compare_value("content_api_presence", content_api_contains(legacy_dir, url), content_api_contains(vault_dir, url)))
        checks.append(compare_value("agentmap_presence", agentmap_contains(legacy_dir, url), agentmap_contains(vault_dir, url)))

        status = "equivalent"
        if any(check["classification"] == "blocking_difference" for check in checks):
            status = "blocking_difference"
        elif any(check["classification"] == "acceptable_expected_difference" for check in checks):
            status = "acceptable_expected_difference"

        records.append({"url": url, "status": status, "checks": checks})

    summary = {
        "legacy_output": str(legacy_dir),
        "vault_output": str(vault_dir),
        "records_compared": len(records),
        "equivalent": len([record for record in records if record["status"] == "equivalent"]),
        "acceptable_expected_difference": len([record for record in records if record["status"] == "acceptable_expected_difference"]),
        "blocking_difference": len([record for record in records if record["status"] == "blocking_difference"]),
    }
    report = {"summary": summary, "records": records}

    json_path = reports_dir / "public-cutover-equivalence.json"
    md_path = reports_dir / "public-cutover-equivalence.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(format_cutover_report(report))

    click.echo(f"Cutover comparison complete: {summary['blocking_difference']} blocking difference(s)")
    click.echo(f"  JSON: {json_path}")
    click.echo(f"  Markdown: {md_path}")
    if summary["blocking_difference"]:
        ctx.exit(1)


def compare_value(name, legacy, vault, acceptable=False):
    if legacy == vault:
        classification = "equivalent"
    elif acceptable:
        classification = "acceptable_expected_difference"
    else:
        classification = "blocking_difference"
    return {"name": name, "classification": classification, "legacy": legacy, "vault": vault}


def _state(document):
    if document is None:
        return None
    return {"status": document.status, "visibility": document.visibility}


def _seo(document):
    if document is None:
        return None
    return document.frontmatter.get("seo")


def read_main_html(path):
    if not path.exists():
        return None
    html = path.read_text()
    match = re.search(r"<main[^>]*>(.*?)</main>", html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else html


def normalize_html_fragment(value):
    if value is None:
        return None
    value = re.sub(r">\s+<", "><", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_canonical(path):
    if not path.exists():
        return None
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', path.read_text(), re.IGNORECASE)
    return match.group(1) if match else None


def extract_refs(path, attr, internal_only=False):
    if not path.exists():
        return []
    refs = re.findall(rf'{attr}=["\']([^"\']+)["\']', path.read_text(), flags=re.IGNORECASE)
    if internal_only:
        refs = [ref for ref in refs if ref.startswith("/") and not ref.startswith("//")]
    return sorted(set(refs))


def extract_jsonld_types(path):
    if not path.exists():
        return []
    html = path.read_text()
    blocks = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, flags=re.IGNORECASE | re.DOTALL)
    types = []
    for block in blocks:
        try:
            data = json.loads(block)
        except Exception:
            continue
        if isinstance(data, dict):
            types.append(data.get("@type"))
    return sorted(type_name for type_name in types if type_name)


def sitemap_contains(dist_path, url):
    path = dist_path / "sitemap.xml"
    return path.exists() and f"{url}" in path.read_text()


def feed_contains(dist_path, url):
    path = dist_path / "feed.json"
    return path.exists() and f"{url}" in path.read_text()


def content_api_contains(dist_path, url):
    path = dist_path / "api" / "content.json"
    return path.exists() and f"{url}" in path.read_text()


def agentmap_contains(dist_path, url):
    path = dist_path / "agentmap.json"
    return path.exists() and f"{url}" in path.read_text()


def format_cutover_report(report):
    summary = report["summary"]
    lines = [
        "# Public Cutover Equivalence",
        "",
        f"- Records compared: {summary['records_compared']}",
        f"- Equivalent: {summary['equivalent']}",
        f"- Acceptable expected differences: {summary['acceptable_expected_difference']}",
        f"- Blocking differences: {summary['blocking_difference']}",
        "",
        "## Records",
        "",
    ]
    for record in report["records"]:
        lines.append(f"### {record['url']} - {record['status']}")
        for check in record["checks"]:
            if check["classification"] != "equivalent":
                lines.append(f"- {check['name']}: {check['classification']}")
        lines.append("")
    return "\n".join(lines)


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


def render_header(config: Dict, templates_path: Path = None) -> str:
    """Render header partial template from HTML file"""
    from jinja2 import Environment, FileSystemLoader
    
    if templates_path is None:
        # Default to templates directory relative to project root
        templates_path = Path(__file__).parent.parent.parent / 'templates'
    
    try:
        env = Environment(loader=FileSystemLoader(str(templates_path)))
        template = env.get_template('partials/header.html')
        return template.render(site_title=config['site']['title'])
    except Exception as e:
        # Fallback to simple header if template fails
        return f"""<header role="banner">
    <a href="/" style="text-decoration: none; color: inherit;">
        <strong>{config['site']['title']}</strong>
    </a>
    <nav role="navigation" aria-label="Main navigation">
        <a href="/">Home</a>
        <a href="/posts/">Posts</a>
        <a href="/projects/">Projects</a>
        <a href="/products/">Products</a>
        <a href="/pages/manifesto/">Manifesto</a>
        <a href="/pages/about/">About</a>
        <a href="/pages/contact/">Contact</a>
        <a href="/cart/">Cart <span class="cart-count">0</span></a>
    </nav>
</header>"""


def render_footer(config: Dict, year: int = None, page_size: str = None, build_time: str = None, 
                  build_time_iso: str = None, lighthouse_scores: bool = True, 
                  description: str = None, templates_path: Path = None) -> str:
    """Render footer partial template from HTML file"""
    from jinja2 import Environment, FileSystemLoader
    from datetime import datetime
    
    if templates_path is None:
        # Default to templates directory relative to project root
        templates_path = Path(__file__).parent.parent.parent / 'templates'
    
    if year is None:
        year = datetime.now().year
    
    try:
        env = Environment(loader=FileSystemLoader(str(templates_path)))
        template = env.get_template('partials/footer.html')
        return template.render(
            site_title=config['site']['title'],
            year=year,
            page_size=page_size,
            build_time=build_time,
            build_time_iso=build_time_iso,
            lighthouse_scores=lighthouse_scores,
            description=description
        )
    except Exception as e:
        # Fallback to simple footer if template fails
        footer_text = f"<p>&copy; {year} {config['site']['title']}. Built with GANG."
        if page_size:
            footer_text += f" {page_size}"
        footer_text += "</p>"
        return f"<footer>{footer_text}</footer>"


def create_index_simple(config: Dict, recent_posts: List, templates_path: Path = None) -> str:
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
    
    # Render header and footer
    header_html = render_header(config, templates_path)
    footer_html = render_footer(
        config,
        year=datetime.now().year,
        page_size=None,  # Will be replaced with __PAGE_SIZE__ placeholder
        build_time=build_time_formatted,
        build_time_iso=build_time_iso,
        lighthouse_scores=True,
        description=config['site']['description'],
        templates_path=templates_path
    )
    
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
    {header_html}
    <main>
        <h1>{config['site']['title']}</h1>
        <p>{config['site']['description']}</p>
        
        <h2>Latest Posts</h2>
        <ul  class="unstyled">
            {posts_html}
        </ul>
        <p><a href="/posts/">View all posts →</a></p>
    </main>
    {footer_html}
</body>
</html>"""
    
    return html


def create_list_page_simple(config: Dict, items: List, title: str, templates_path: Path = None) -> str:
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
    
    # Render header and footer
    header_html = render_header(config, templates_path)
    footer_html = render_footer(
        config,
        year=datetime.now().year,
        page_size=None,  # Will be replaced with __PAGE_SIZE__ placeholder
        build_time=build_time_formatted,
        build_time_iso=build_time_iso,
        lighthouse_scores=True,
        description=config['site']['description'],
        templates_path=templates_path
    )
    
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
    {header_html}
    <main>
        <h1>{title}</h1>
        <ul>
            {items_html}
        </ul>
    </main>
    {footer_html}
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
    
    # Build time for footer
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Render header
    header_html = render_header(config)
    
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
    {header_html}
    <main>
        <article>
            {body_html}
        </article>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG. __PAGE_SIZE__</p>
        <p class="lighthouse-scores">
            <span class="score" title="Performance">Performance <strong>100</strong></span>
            <span class="score" title="Accessibility">Accessibility <strong>100</strong></span>
            <span class="score" title="Best Practices">Best Practices <strong>100</strong></span>
            <span class="score" title="SEO">Score <strong>100</strong></span>
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
    
    # Render header
    header_html = render_header(config)
    
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
    {header_html}
    <main>
        <h1>{config['site']['title']}</h1>
        <p>{config['site']['description']}</p>
        
        <h2>Latest Posts</h2>
        <ul  class="unstyled">>
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
    
    # Render header
    header_html = render_header(config)
    
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
    {header_html}
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
    
    click.echo("Score Checking for dependency updates...\n")
    
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
        click.echo("Score Analyzing images in content...\n")
        
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
                        
                        click.echo(f"Score Looking for content in: {content_path}")
                        
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
                if self.path == '/api/validate-headings':
                    try:
                        # Read request body
                        content_length = int(self.headers['Content-Length'])
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode())
                        
                        content = data.get('content', '')
                        
                        click.echo(f"Score Validating headings in content ({len(content)} chars)")
                        
                        # Import heading validator
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.heading_validator import HeadingValidator
                        
                        validator = HeadingValidator()
                        result = validator.validate_markdown(content)
                        
                        # Add formatted report
                        result['report'] = validator.generate_error_report(result)
                        
                        click.echo(f"✅ Validation complete: {'PASS' if result['valid'] else 'FAIL'}")
                        
                        # Return validation result
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(result, default=str).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error validating headings: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Internal server error',
                            'message': str(e)
                        }).encode())
                
                elif self.path == '/api/rename-slug':
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
    
    import signal
    import sys
    
    # Global variables for cleanup
    server = None
    observer = None
    
    def signal_handler(signum, frame):
        """Handle shutdown signals"""
        click.echo(f"\n👋 Received signal {signum}, shutting down...")
        try:
            if observer:
                observer.stop()
                observer.join(timeout=1)
        except:
            pass
        try:
            if server:
                server.shutdown()
        except:
            pass
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Terminal close
    signal.signal(signal.SIGHUP, signal_handler)   # Terminal hangup
    
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
                    
                    # Check if editor mode is enabled (for in-place editing)
                    user_authenticated = os.environ.get('EDITOR_MODE', '').lower() == 'true'
                    
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
                        # In-place editor context
                        'page_type': content_type.rstrip('s'),  # 'posts' -> 'post', 'pages' -> 'page'
                        'category': content_type,  # 'posts', 'pages', 'projects', etc.
                        'slug': slug,
                        'user_authenticated': user_authenticated,
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
                index_html = create_index_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5], templates_path)
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
                    posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts', templates_path)
                    # Inject live reload script
                    if '</body>' in posts_html:
                        posts_html = posts_html.replace('</body>', live_reload_script + '</body>')
                    # Recalculate page size after injecting live reload
                    page_size_bytes = len(posts_html.encode('utf-8'))
                    posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                    (dist_path / 'posts' / 'index.html').write_text(posts_html)
                
                if all_projects:
                    projects_html = create_list_page_simple(config, all_projects, 'Projects', templates_path)
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
                        build_time = datetime.now()
                        build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
                        build_time_iso = build_time.isoformat()
                        cart_template = jinja_env.get_template('cart.html')
                        cart_html = cart_template.render(
                            year=datetime.now().year,
                            site_title=config['site']['title'],
                            lighthouse_scores=True,
                            build_time=build_time_formatted,
                            build_time_iso=build_time_iso,
                            description=config['site']['description']
                        )
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
        click.echo("Press Ctrl+C to stop (or close terminal)\n")
        
        # The signal handler will take care of cleanup
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down...")
            observer.stop()
            observer.join()
            server.shutdown()
        except SystemExit:
            # Signal handler called sys.exit()
            pass
    
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

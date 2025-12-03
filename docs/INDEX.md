# GANG Platform Documentation Index

## Quick Links

- [README](../README.md) - Project overview
- [Quick Start](guides/QUICK_START.md) - Get started in 5 minutes
- [Quality Standards](QUALITY-BARS.md) - W3C alignment, WCAG AA, budgets

## Setup Guides

**Infrastructure**:
- [Cloudflare Setup](guides/CLOUDFLARE_SETUP.md) - Deploy to Cloudflare Pages
- [Deployment Guide](guides/DEPLOYMENT.md) - General deployment
- [R2 Storage Setup](guides/R2_SETUP.md) - Media CDN configuration

**Integrations**:
- [Shopify Setup](guides/SHOPIFY_SETUP_GUIDE.md) - E-commerce integration
- [Klaviyo Setup](guides/KLAVIYO_SETUP.md) - Email marketing
- [Media Storage](guides/MEDIA_STORAGE_GUIDE.md) - Image/video hosting

**Content Management**:
- [Content Import](guides/CONTENT_IMPORT_GUIDE.md) - Bulk import from other platforms
- [CMS Slug Rename](guides/CMS_SLUG_RENAME_GUIDE.md) - URL management
- [Email Workflow](guides/EMAIL_WORKFLOW.md) - Newsletter publishing
- [In-Place Editor Quick Start](guides/IN_PLACE_EDITOR_QUICKSTART.md) - Edit pages in context (NEW)

**Workflows**:
- [Operations Guide](guides/OPERATE.md) - Day-to-day operations
- [Collaborative Workflow](guides/COLLABORATIVE_WORKFLOW.md) - Team workflows

## Features

**Core Features**:
- [Complete Feature List v2](features/COMPLETE_FEATURE_LIST_v2.md) - Latest comprehensive list
- [Feature Status](features/FEATURES_STATUS.md) - Implementation status
- [Manifesto-Aligned Features](features/MANIFESTO_ALIGNED_FEATURES.md) - Philosophy-driven features

**AI & Automation**:
- [AI Link Suggestions](features/AI_LINK_SUGGESTIONS.md) - Internal linking
- [AI Suggestions Demo](features/AI_SUGGESTIONS_DEMO.md) - AI capabilities
- [Auto-Fix Feature](features/AUTO_FIX_FEATURE.md) - Automated corrections
- [Content Quality Analyzer](features/CONTENT_QUALITY_ANALYZER.md) - Quality scoring

**Performance & Quality**:
- [Progressive Enhancement](features/PROGRESSIVE_ENHANCEMENT_COMPLETE.md) - No-JS approach
- [Link Validator](features/LINK_VALIDATOR.md) - Broken link detection
- [Live Reload](features/LIVE_RELOAD_DEMO.md) - Development preview

## Architecture

**Implementation**:
- [Autonomous Build Summary](architecture/AUTONOMOUS_BUILD_SUMMARY.md) - Build system
- [Build Performance](architecture/BUILD_PERFORMANCE.md) - Performance metrics
- [Implementation Summary](architecture/IMPLEMENTATION_SUMMARY.md) - Tech decisions
- [Avoiding Stalls](architecture/AVOIDING_STALLS.md) - Performance optimization

**In-Place Editor** (NEW):
- [📚 Documentation Hub](architecture/IN_PLACE_EDITOR_README.md) - **Start here!** Navigation & overview
- [✅ Phase 1 Complete](architecture/IN_PLACE_EDITOR_PHASE1_COMPLETE.md) - **MVP Implementation Status**
- [📋 Executive Summary](architecture/IN_PLACE_EDITOR_SUMMARY.md) - Decision & rationale
- [📖 Implementation Plan](architecture/IN_PLACE_EDITOR_PLAN.md) - Detailed technical spec
- [⚖️ Studio Comparison](architecture/EDITOR_COMPARISON.md) - Feature & UX analysis
- [🔄 User Flows & Diagrams](architecture/IN_PLACE_EDITOR_FLOWS.md) - Visual architecture

**Status Reports**:
- [Build Complete Status](architecture/BUILD_COMPLETE_STATUS.md) - Final build state
- [Final Build Status](architecture/FINAL_BUILD_STATUS.md) - Production readiness
- [Optimization Report](architecture/OPTIMIZATION_REPORT.md) - Performance gains

## Quality & Testing

- [Quality Bars](QUALITY-BARS.md) - W3C standards, WCAG 2.2 AA compliance
- [Quality Gates](QUALITY_GATES.md) - CI/CD quality checks
- [Lighthouse Audit Checklist](LIGHTHOUSE_AUDIT_CHECKLIST.md) - Performance auditing
- [Lighthouse Status](LIGHTHOUSE_STATUS.md) - Current scores

## Advanced Topics

- [CrUX Monitoring](CRUX-MONITORING.md) - Real-user performance
- [Wayback Archival](WAYBACK-ARCHIVAL.md) - Permanent preservation
- [Image Pipeline v2](IMAGE-PIPELINE-V2.md) - Advanced image processing
- [Shopify Sync](SHOPIFY-SYNC.md) - Automated product updates
- [SRI Implementation](SRI.md) - Subresource integrity
- [Security Headers](SECURITY-HEADERS.md) - Production security

## Code Reviews & Session Notes

- [Code Review Summary](reviews/CODE_REVIEW_SUMMARY.md) - Latest review
- [Bug Report](reviews/BUG_REPORT.md) - Bugs found and fixed
- [Review Complete](reviews/REVIEW_COMPLETE.md) - Final review status
- [Session Summary](reviews/SESSION_SUMMARY.md) - Work session notes
- [Current TODO](reviews/CURRENT_TODO.md) - Active tasks
- [Morning Briefing](reviews/MORNING_BRIEFING.md) - Daily standup

## Documentation Organization

```
docs/
├── INDEX.md (this file)
├── QUALITY-BARS.md
├── guides/           # Setup & how-to guides
├── features/         # Feature documentation
├── architecture/     # Implementation details
└── reviews/          # Code reviews & session notes
```

## Contributing

When adding documentation:
- ✅ Keep in root: README.md, CHANGELOG.md, LICENSE
- ❌ Don't add to root: All other .md files
- ✅ Use subdirectories:
  - `docs/guides/` - Setup instructions
  - `docs/features/` - Feature documentation
  - `docs/architecture/` - Technical implementation
  - `docs/reviews/` - Session notes, reviews
  - `docs/` - Core documentation (quality standards, etc.)


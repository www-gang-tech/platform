# Build Performance Tracking

**Monitor build performance, identify bottlenecks, and track improvements over time.**

## Features

### ⚡ What Gets Tracked

- **Total build time** - End-to-end duration
- **Stage breakdown** - Where time is spent
- **File counts** - Pages, posts, projects processed
- **Trend analysis** - Compare with previous builds
- **Historical data** - Last 50 builds stored
- **Statistics** - Average, fastest, slowest

---

## Usage

### Profile a Single Build

```bash
gang build --profile
```

**Output:**
```
🔨 Building site...
📦 Copying public assets...
📝 Processing content...
✅ Build complete!

============================================================
⚡ Build Performance Report
============================================================

Total build time: 63ms (0.06s)

📊 Stage Breakdown:
├─ generate_outputs: 2ms (3.2%)
├─ copy_assets: 0ms (0.0%)

📝 Files Processed:
├─ pages: 5
├─ posts: 1
├─ projects: 1

🚀 vs previous: 3ms faster (4.5%)

============================================================
```

---

### View Build History

```bash
gang performance
```

**Output:**
```
============================================================
⚡ Build Performance History (last 5 runs)
============================================================

#1: 66ms (0.07s)
   Time: 2025-10-11T22:57:36
   Files: 7 (pages:5, posts:1, projects:1)

#2: 63ms (0.06s)
   Time: 2025-10-11T22:57:46
   Files: 7 (pages:5, posts:1, projects:1)

#3: 62ms (0.06s)
   Time: 2025-10-11T22:58:22
   Files: 7 (pages:5, posts:1, projects:1)

#4: 53ms (0.05s)
   Time: 2025-10-11T22:58:22
   Files: 7 (pages:5, posts:1, projects:1)

#5: 53ms (0.05s)
   Time: 2025-10-11T22:58:23
   Files: 7 (pages:5, posts:1, projects:1)

📊 Statistics:
├─ Average (last 5): 59ms
├─ Fastest: 53ms
└─ Slowest: 66ms

============================================================
```

---

## What You Learn

### Is Your Build Getting Slower?

```
Build #1: 50ms
Build #5: 150ms  
🐌 vs previous: 100ms slower (200%)

→ Something changed! Investigate.
```

**Possible causes:**
- Added many new files
- Large images
- Complex templates
- External API calls

### Is Your Build Getting Faster?

```
Build #1: 150ms
Build #5: 50ms
🚀 vs previous: 100ms faster (66%)

→ Optimization working!
```

**Possible improvements:**
- Removed unused files
- Optimized images
- Template caching
- Better algorithms

---

## Performance Targets

### Current Performance

Your builds are **blazing fast:**
- Average: **~60ms**
- 7 files processed
- Sub-100ms consistently

### Target Benchmarks

| Site Size | Target | Your Site |
|-----------|--------|-----------|
| Small (1-10 pages) | <100ms | ✅ 60ms |
| Medium (10-50 pages) | <500ms | N/A |
| Large (50-200 pages) | <2000ms | N/A |
| Huge (200+ pages) | <5000ms | N/A |

**You're crushing it!** ✅

---

## Stage Breakdown

### What Each Stage Does

| Stage | What It Does | Typical % |
|-------|--------------|-----------|
| `copy_assets` | Copy fonts, icons, static files | ~5% |
| `process_content` | Parse markdown, render HTML | ~60% |
| `generate_outputs` | Create sitemap, feeds, robots.txt | ~5% |
| `optimize_images` | Generate responsive variants | ~30% (if enabled) |

### Identifying Bottlenecks

```
📊 Stage Breakdown:
├─ process_content: 450ms (75%)     ← BOTTLENECK!
├─ optimize_images: 100ms (17%)
├─ generate_outputs: 30ms (5%)
└─ copy_assets: 20ms (3%)
```

**Actions:**
- Investigate template complexity
- Check for slow markdown extensions
- Profile individual file processing

---

## Historical Tracking

### Data Storage

Performance data stored in:
```
.lighthouseci/build-performance.json
```

**Format:**
```json
{
  "runs": [
    {
      "total_duration_ms": 63,
      "timestamp": "2025-10-11T22:57:46.770704",
      "stages": {
        "copy_assets": 0,
        "generate_outputs": 2
      },
      "files": {
        "pages": 5,
        "posts": 1,
        "projects": 1
      }
    }
  ]
}
```

### Retention

- Keeps last **50 builds**
- Automatic rotation
- JSON format for analysis

---

## Trend Analysis

### View Trends

```bash
# Last 10 builds (default)
gang performance

# Last 20 builds
gang performance --limit 20

# All builds
gang performance --limit 50
```

### Extract Metrics

```bash
# Average duration trend
cat .lighthouseci/build-performance.json | \
  jq '.runs[-10:] | map(.total_duration_ms) | add / length'

# Plot over time (with gnuplot or similar)
cat .lighthouseci/build-performance.json | \
  jq -r '.runs[] | "\(.timestamp) \(.total_duration_ms)"'
```

---

## Use Cases

### 1. **Identify Regressions**

```bash
# After adding new feature
gang build --profile

# Check if slower
gang performance

# If slower, investigate
```

### 2. **Validate Optimizations**

```bash
# Before optimization
gang build --profile  # 150ms

# Apply optimization
# ... make changes ...

# After optimization
gang build --profile  # 80ms
# 🚀 70ms faster!
```

### 3. **Track Growth**

```bash
# Week 1: 5 pages → 50ms
# Week 10: 50 pages → 500ms
# Scales linearly (good!)
```

### 4. **Debug Slow Builds**

```bash
gang build --profile

# Stage breakdown shows:
# optimize_images: 2000ms (90%)
# → Image optimization is slow
# → Solution: Reduce image sizes or enable caching
```

---

## Integration Examples

### CI/CD Monitoring

```yaml
# GitHub Actions
- name: Build with profiling
  run: gang build --profile > build-log.txt

- name: Extract performance
  run: |
    DURATION=$(jq '.runs[-1].total_duration_ms' .lighthouseci/build-performance.json)
    echo "BUILD_TIME_MS=$DURATION" >> $GITHUB_ENV

- name: Check for regression
  run: |
    if [ $BUILD_TIME_MS -gt 1000 ]; then
      echo "⚠️ Build is slower than 1s"
    fi
```

### Performance Dashboard

```python
# scripts/generate-dashboard.py
import json
import matplotlib.pyplot as plt

with open('.lighthouseci/build-performance.json') as f:
    data = json.load(f)
    
runs = data['runs']
durations = [r['total_duration_ms'] for r in runs]

plt.plot(durations)
plt.title('Build Performance Over Time')
plt.ylabel('Duration (ms)')
plt.xlabel('Build #')
plt.savefig('build-performance.png')
```

---

## Current Performance

### Your Build Stats

Based on recent runs:
- **Average:** 59ms
- **Fastest:** 53ms  
- **Slowest:** 66ms
- **Trend:** Getting faster! 🚀

### What This Means

**63ms is exceptional!**
- ✅ Sub-100ms target
- ✅ Near-instant feedback
- ✅ Great developer experience
- ✅ Room for 10x growth

**At this speed you can:**
- Process 100+ pages in <1s
- Rebuild on every save
- Run in CI without slowdown
- Scale to medium-sized site

---

## Commands Reference

```bash
# Profile current build
gang build --profile

# View history
gang performance

# View more history
gang performance --limit 20

# Combine with other flags
gang build --profile --check-quality --validate-links
```

---

## Performance Data

Stored in `.lighthouseci/build-performance.json`:

```json
{
  "runs": [
    {
      "total_duration_ms": 63,
      "timestamp": "2025-10-11T22:57:46.770704",
      "stages": {
        "copy_assets": 0,
        "generate_outputs": 2
      },
      "files": {
        "pages": 5,
        "posts": 1,
        "projects": 1
      }
    }
  ]
}
```

**Can be used for:**
- Trend graphs
- Performance dashboards
- CI/CD alerting
- Optimization tracking

---

## Best Practices

### 1. Profile Regularly

```bash
# Always profile in development
gang build --profile

# Check trends weekly
gang performance
```

### 2. Set Performance Budgets

```yaml
# Future: gang.config.yml
performance:
  max_build_time_ms: 1000
  max_stage_time_ms:
    process_content: 500
    optimize_images: 300
```

### 3. Track Before/After

```bash
# Before optimization
gang build --profile  # Note duration

# Make changes
# ...

# After optimization
gang build --profile  # Compare
gang performance      # See trend
```

### 4. Investigate Regressions

```bash
# If build gets slower
gang performance

# Check what changed
git log --oneline

# Identify cause
git bisect
```

---

## Future Enhancements

### Planned Features

- **Per-file profiling** - Which files are slowest
- **Template profiling** - Which templates take longest
- **Budget enforcement** - Fail if build >1s
- **Slack/Discord alerts** - Notify on regressions
- **Visual dashboard** - Performance graphs
- **Export to CSV** - For analysis tools

### Coming Soon

```bash
# Per-file breakdown
gang build --profile --detailed

# Output:
Slowest files:
  1. posts/huge-post.md: 25ms
  2. pages/complex.md: 18ms
  3. projects/big.md: 12ms
```

---

## Philosophy

Build performance tracking embodies GANG values:

✓ **Fast feedback** - Know immediately if build slows  
✓ **Data-driven** - Optimize based on metrics  
✓ **Transparent** - See exactly where time goes  
✓ **Non-intrusive** - Minimal overhead (<1ms)  
✓ **Historical** - Track trends over time  

**Measure what matters. Optimize what's slow.**


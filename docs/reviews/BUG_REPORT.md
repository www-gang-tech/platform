# Bug Report & Fixes

## Critical Bugs Found

### 1. ❌ CRITICAL: Alt Text Validation Logic Error
**File**: `cli/gang/core/validator.py:183` (task-3-contracts branch)

**Bug**:
```python
images_without_alt = [img for img in images if not img.get('alt') is not None]
```

**Issue**: Operator precedence causes this to always evaluate to `True`. The expression is parsed as `not (img.get('alt') is not None)`, which is always True when alt is None.

**Fix**:
```python
images_without_alt = [img for img in images if img.get('alt') is None]
```

**Impact**: Alt text coverage validation is completely broken - will report 0% coverage even when all images have alt text.

---

### 2. ⚠️ Missing Files in Branches
**Issue**: Scripts not present in all branches

- `scripts/crux_snapshot.js` - Only in task-6 branch
- `scripts/archive.js` - Only in task-8 branch  
- `contracts/*.yml` - Only in task-3 branch
- `_headers` - Only in task-4 branch

**Impact**: Commands fail when run from wrong branch

**Fix**: Each PR should be self-contained, or merge to main sequentially

---

### 3. ⚠️ JSON Import Missing in CLI
**File**: `cli/gang/cli.py:3514` (task-7-syndication branch)

**Bug**: Uses `json.load()` but doesn't import json at top of function

**Current**:
```python
def syndicate(ctx, bundle_file, format, output):
    # ... code ...
    with open(bundle_file, 'r') as f:
        bundle = json.load(f)  # json not imported!
```

**Fix**: Add import at function start:
```python
def syndicate(ctx, bundle_file, format, output):
    import json
    # ... rest of code
```

**Impact**: Command crashes with `NameError: name 'json' is not defined`

---

### 4. ⚠️ Shopify Workflow - Syntax Error in Python Heredoc
**File**: `.github/workflows/shopify-sync.yml:48` (task-10 branch)

**Bug**: Uses `::set-output` (deprecated GitHub Actions syntax)

**Current**:
```python
print(f"::set-output name=file::{output_file}")
print(f"::set-output name=handle::{handle}")
```

**Fix**: Use environment file syntax:
```python
with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
    f.write(f"file={output_file}\n")
    f.write(f"handle={handle}\n")
```

**Impact**: Workflow may fail in newer GitHub Actions runners

---

### 5. ℹ️ Minor: Inconsistent Error Handling
**Files**: Multiple scripts

**Issue**: Some scripts use `try/except` with generic exceptions, others don't catch errors

**Recommendation**: Add consistent error handling patterns

---

## Test Results

### ✅ Working:
- `gang check` command runs (but has bug #1)
- `gang report --answerability` works correctly
- `gang syndicate` has import bug but otherwise functional
- All modules import successfully
- Validator loads contracts correctly

### ❌ Needs Fixing:
- Alt text validation (bug #1)
- JSON import in syndicate command (bug #3)
- Shopify workflow output syntax (bug #4)

### ⚠️ Untested (requires env vars/setup):
- CrUX snapshot script (needs PSI_API_KEY)
- Archive script (needs BASE_URL)
- Shopify workflow (needs webhook payload)

---

## Recommended Actions

### Immediate (Critical):
1. Fix validator.py alt text logic
2. Add json import to syndicate command

### Before Merge:
3. Update Shopify workflow to use new output syntax
4. Test each script with required env vars
5. Add error handling to all scripts

### Nice to Have:
6. Add unit tests for validator logic
7. Add integration tests for CLI commands
8. Document env var requirements in each script

---

## Fixed Branches Needed

Create fix branches:
- `nightly/task-3-contracts-fix` - Fix alt validation
- `nightly/task-7-syndication-fix` - Add json import
- `nightly/task-10-shopify-fix` - Update workflow syntax

---

## Testing Checklist

- [ ] Run `gang check` on dist/ with images
- [ ] Test alt text validation with missing alts
- [ ] Run `gang syndicate` command
- [ ] Test CrUX script with valid API key
- [ ] Test archive script with valid BASE_URL
- [ ] Simulate Shopify webhook payload
- [ ] Check all GitHub Actions workflows syntax

---

Generated: 2025-10-13


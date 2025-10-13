# How to Avoid Command Stalls

## The Problem

Commands can stall when:
1. **Special characters** (like emojis) break shell parsing
2. **Wildcards** expand unexpectedly
3. **Quotes** aren't closed properly
4. **Interactive prompts** wait for input

## Solutions for Autonomous Operation

### 1. Use Simple Test Commands
```bash
# ❌ BAD - Wildcards can fail
ls -lh dist/search* && echo "✅ Done"

# ✅ GOOD - Simple, explicit tests  
test -f dist/search-index.json && echo "File exists" || echo "Missing"
```

### 2. Avoid Emojis in Shell Commands
```bash
# ❌ BAD - Emojis can break quotes
echo "✅ All features working!"

# ✅ GOOD - Plain text
echo "All features working"
```

### 3. Break Complex Commands
```bash
# ❌ BAD - Complex one-liner
ls dist/*.json 2>&1 | grep search && echo "Found"

# ✅ GOOD - Separate steps
test -f dist/search-index.json
if [ $? -eq 0 ]; then echo "Found"; fi
```

### 4. Use Explicit Paths
```bash
# ❌ BAD - Glob expansion
for f in dist/*.json; do ...

# ✅ GOOD - Find command
find dist -name "*.json" -type f
```

### 5. Redirect All Output
```bash
# ❌ BAD - Might hang on stderr
gang build

# ✅ GOOD - Capture everything
gang build 2>&1 | head -20
```

### 6. Set Timeouts (For Critical Commands)
```bash
# ✅ GOOD - Timeout after 30s
timeout 30 gang build || echo "Build timed out"
```

## Best Practices for AI Autonomous Operation

1. **Always use full paths**
   ```bash
   cd /Users/user/project && gang build
   ```

2. **Limit output**
   ```bash
   gang build 2>&1 | head -20
   ```

3. **Test, don't list**
   ```bash
   test -f file.json && echo "exists"
   ```

4. **Avoid interactive commands**
   ```bash
   echo "y" | gang command  # Pre-answer prompts
   ```

5. **Check exit codes**
   ```bash
   gang build
   if [ $? -eq 0 ]; then echo "Success"; fi
   ```

## For Future Improvements

### Option 1: Command Wrapper
Create a wrapper that auto-times out:
```python
def safe_command(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd, 
            timeout=timeout,
            capture_output=True
        )
        return result
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
```

### Option 2: Progress Indicators
Commands that take time should print progress:
```python
click.echo("Building... (step 1/5)")
click.echo("Building... (step 2/5)")
```

### Option 3: Async Commands
For long operations, run in background:
```bash
gang build &
PID=$!
sleep 30
kill -0 $PID || echo "Done or failed"
```

## Summary

**The stall happened because:**
- Command had `dist/search*` wildcard
- Shell tried to expand it
- Emoji `✅` caused quote parsing issues
- Command waited for more input

**To fix:**
- Use `test -f` instead of `ls` with wildcards
- Avoid emojis in commands
- Always redirect output `2>&1`
- Limit output with `| head -N`

**Going forward:**
- I'll use these safer patterns
- Test files explicitly
- Avoid complex shell syntax
- Keep commands simple and predictable


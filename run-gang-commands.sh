#!/bin/bash
# Run all gang commands in sequence for CI/CD
set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Set PYTHONPATH to include the CLI
export PYTHONPATH="cli/gang:$PYTHONPATH"

# Function to run a command and continue on error
run_command() {
    local cmd="$1"
    local description="$2"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "▶ $description"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if python3 cli/gang/cli.py $cmd; then
        echo "✅ $description completed successfully"
        return 0
    else
        local exit_code=$?
        echo "⚠️  $description completed with exit code $exit_code (continuing...)"
        return $exit_code
    fi
}

# Run commands in sequence
echo "🚀 Running GANG build pipeline..."

# 1. Optimize (may warn about missing API key, that's OK)
# Note: optimize may fail due to click/Python issues, that's OK - it's optional
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▶ AI Optimization (optional)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if python3 cli/gang/cli.py optimize 2>&1; then
    echo "✅ AI Optimization completed successfully"
else
    echo "⚠️  AI Optimization skipped or failed (this is OK if ANTHROPIC_API_KEY is not set)"
fi

# 2. Image processing (skip if no source directory)
if [ -d "public/images" ]; then
    run_command "image public/images" "Image Processing" || true
else
    echo ""
    echo "ℹ️  Skipping image processing: public/images/ directory not found"
    echo "   (This is OK if you don't have images to process)"
fi

# 3. Build
run_command "build" "Site Build"

# 4. Check
run_command "check" "Contract Validation"

# 5. Audit
run_command "audit" "Lighthouse + axe Audit"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All commands completed!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


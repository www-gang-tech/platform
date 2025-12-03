#!/bin/bash
# Simple test script for GANG Studio Backend API

BASE_URL="http://localhost:5001"

echo "🧪 Testing GANG Studio Backend API"
echo "=================================="
echo ""

# Test 1: Health check
echo "1. Testing /api/health..."
curl -s "$BASE_URL/api/health" | jq '.'
echo ""

# Test 2: Auth status
echo "2. Testing /api/auth/status..."
curl -s "$BASE_URL/api/auth/status" | jq '.'
echo ""

# Test 3: List content
echo "3. Testing /api/content/list..."
curl -s "$BASE_URL/api/content/list" | jq '.[0:3]'
echo ""

# Test 4: Get content
echo "4. Testing /api/content/<path> (GET)..."
curl -s "$BASE_URL/api/content/pages/manifesto" | head -n 10
echo ""
echo "..."
echo ""

# Test 5: Validate headings
echo "5. Testing /api/validate-headings..."
curl -s -X POST "$BASE_URL/api/validate-headings" \
  -H "Content-Type: application/json" \
  -d '{"content": "# Main Title\n\n## Subtitle\n\n### Section"}' | jq '.'
echo ""

echo "✅ All tests complete!"
echo ""
echo "To test the editor:"
echo "  1. Set EDITOR_MODE: export EDITOR_MODE=true"
echo "  2. Build site: gang build"
echo "  3. Serve: python -m http.server 8000 --directory dist"
echo "  4. Visit: http://localhost:8000/pages/manifesto/"



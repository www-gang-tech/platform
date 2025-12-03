#!/bin/bash
# Start In-Place Editor Demo
# Run this script to test the editor locally

set -e

echo "🚀 Starting GANG In-Place Editor Demo"
echo "======================================"
echo ""

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing backend dependencies..."
    cd apps/studio/backend
    pip install -r requirements.txt
    cd ../../..
fi

# Build site with editor enabled
echo "🔨 Building site with editor mode..."
export EDITOR_MODE=true
gang build

echo ""
echo "✅ Build complete!"
echo ""
echo "📋 Next steps:"
echo ""
echo "1. Start the backend API (in a new terminal):"
echo "   cd apps/studio/backend && python app.py"
echo ""
echo "2. Serve the site (in another new terminal):"
echo "   python -m http.server 8000 --directory dist"
echo ""
echo "3. Open in browser:"
echo "   http://localhost:8000/pages/manifesto/"
echo ""
echo "4. Click the '✏️ Edit' button to start editing!"
echo ""
echo "📖 Full guide: EDITOR_DEMO.md"



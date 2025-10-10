#!/bin/bash
set -e

echo "🚀 Installing dependencies..."
pip install -r requirements.txt

echo "🔨 Building GANG platform..."
cd cli/gang
pip install -e .
cd ../..

echo "📝 Generating static site..."
gang build

echo "✅ Build complete!"


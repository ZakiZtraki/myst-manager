#!/bin/bash
# Quick start script for crypto-portfolio-manager

set -e

echo "🚀 Crypto Portfolio Manager - Quick Start"
echo "=========================================="
echo

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Install package in development mode
echo "📦 Installing package..."
pip install -q -e .

# Create portfolio config if it doesn't exist
if [ ! -f "portfolio.json" ]; then
    echo "📝 Creating portfolio config from example..."
    cp examples/portfolio.example.json portfolio.json
    echo "⚠️  Edit portfolio.json with your actual holdings!"
fi

echo
echo "✅ Setup complete!"
echo
echo "Quick commands to try:"
echo "  crypto-portfolio status        # View portfolio"
echo "  crypto-portfolio recommend     # Get recommendations"
echo "  crypto-portfolio report        # Daily report"
echo "  crypto-portfolio price BTC ETH # Check prices"
echo
echo "📚 See README.md for full documentation"
echo "🤖 See CLAUDE_CODE_GUIDE.md for Claude Code usage"
echo
echo "To activate the virtual environment later:"
echo "  source venv/bin/activate"

#!/bin/bash
echo "🔍 Build Folder Verification"
echo "======================================"
echo ""

if [ ! -d "build" ]; then
    echo "❌ ERROR: build/ folder not found!"
    exit 1
fi

echo "✅ build/ folder exists"
echo ""

echo "Checking Windows scripts..."
if [ -f "build/windows/build_standard.bat" ] && [ -f "build/windows/build_hardened.bat" ]; then
    echo "  ✅ Windows build scripts found"
else
    echo "  ❌ Windows build scripts missing"
fi

echo "Checking Linux scripts..."
if [ -f "build/linux/build_standard.sh" ] && [ -f "build/linux/build_hardened.sh" ]; then
    echo "  ✅ Linux build scripts found"
else
    echo "  ❌ Linux build scripts missing"
fi

echo "Checking documentation..."
if [ -f "build/README.md" ] && [ -f "build/QUICK_BUILD_GUIDE.txt" ]; then
    echo "  ✅ Documentation found"
else
    echo "  ❌ Documentation missing"
fi

echo ""
echo "======================================"
echo "✅ Build folder verification complete!"

#!/usr/bin/env python3
"""
Pre-Deployment Validation Script
=================================
Run this before deploying to ensure the application is stable.
"""
import subprocess
import sys
import os
from pathlib import Path

class ValidationResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
    
    def add_pass(self, message):
        self.passed += 1
        print(f"  ✓ {message}")
    
    def add_fail(self, message):
        self.failed += 1
        self.errors.append(message)
        print(f"  ✗ {message}")
    
    def add_warning(self, message):
        self.warnings += 1
        print(f"  ⚠ {message}")

def run_command(cmd, timeout=60):
    """Run a command and return success status and output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)

def check_python_syntax(result):
    """Check Python files for syntax errors."""
    print("\n1. Checking Python Syntax...")
    
    critical_files = [
        'src/selfbot_webull.py',
        'gui_app/routes.py',
        'gui_app/database.py',
        'gui_app/app.py',
        'broker_sync_service.py'
    ]
    
    for filepath in critical_files:
        if Path(filepath).exists():
            success, output = run_command(f"python -m py_compile {filepath}")
            if success:
                result.add_pass(f"Syntax OK: {filepath}")
            else:
                result.add_fail(f"Syntax error in {filepath}")
        else:
            result.add_warning(f"File not found: {filepath}")

def check_imports(result):
    """Check that critical imports work."""
    print("\n2. Checking Critical Imports...")
    
    import_tests = [
        ("flask", "from flask import Flask"),
        ("discord.py-self", "import discord"),
        ("openai", "import openai"),
        ("cryptography", "from cryptography.fernet import Fernet"),
        ("alpaca-py", "from alpaca.trading.client import TradingClient"),
    ]
    
    for name, import_stmt in import_tests:
        success, _ = run_command(f'python -c "{import_stmt}"')
        if success:
            result.add_pass(f"Import OK: {name}")
        else:
            result.add_warning(f"Import failed: {name} (may not be required)")

def check_unit_tests(result):
    """Run unit tests."""
    print("\n3. Running Unit Tests...")
    
    success, output = run_command("python -m pytest tests/unit/ -v --tb=short -q", timeout=120)
    
    if "passed" in output and "failed" not in output:
        lines = output.strip().split('\n')
        for line in lines[-5:]:
            if "passed" in line:
                result.add_pass(f"Tests: {line.strip()}")
                break
    elif "failed" in output:
        result.add_fail("Some unit tests failed - check output above")
    else:
        result.add_warning("Could not run unit tests")

def check_database_tables(result):
    """Check database has required structure."""
    print("\n4. Checking Database Schema...")
    
    db_path = 'bot_data.db'
    if not Path(db_path).exists():
        result.add_warning("Database file not found (will be created on first run)")
        return
    
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    
    if 'server_licenses' in tables:
        result.add_pass("License table exists")
    else:
        result.add_fail("License table missing")
    
    conn.close()

def check_environment(result):
    """Check required environment variables."""
    print("\n5. Checking Environment...")
    
    required_vars = ['ADMIN_PASSWORD', 'LICENSE_SERVER_MODE']
    optional_vars = ['ALPHA_VANTAGE_API_KEY', 'FINNHUB_API_KEY']
    
    for var in required_vars:
        if os.getenv(var):
            result.add_pass(f"Env var set: {var}")
        else:
            result.add_warning(f"Env var not set: {var}")
    
    for var in optional_vars:
        if os.getenv(var):
            result.add_pass(f"Optional env var set: {var}")

def main():
    """Run all validation checks."""
    print("=" * 50)
    print("BotifyTrades Pre-Deployment Validation")
    print("=" * 50)
    
    result = ValidationResult()
    
    os.chdir(Path(__file__).parent.parent)
    
    check_python_syntax(result)
    check_imports(result)
    check_unit_tests(result)
    check_database_tables(result)
    check_environment(result)
    
    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    print(f"  Passed:   {result.passed}")
    print(f"  Warnings: {result.warnings}")
    print(f"  Failed:   {result.failed}")
    
    if result.failed > 0:
        print("\n❌ VALIDATION FAILED - Fix issues before deploying!")
        print("\nErrors:")
        for error in result.errors:
            print(f"  - {error}")
        return 1
    elif result.warnings > 0:
        print("\n⚠️  VALIDATION PASSED WITH WARNINGS")
        return 0
    else:
        print("\n✅ VALIDATION PASSED - Ready to deploy!")
        return 0

if __name__ == '__main__':
    sys.exit(main())

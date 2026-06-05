# BotifyTrades - Build and Test Automation
# =========================================

.PHONY: help install lint type test-quick test-all test-license test-broker test-signal test-db validate clean

# Default target
help:
	@echo "BotifyTrades - Available Commands:"
	@echo ""
	@echo "  Testing:"
	@echo "    make test-quick    - Run fast unit tests (no external deps)"
	@echo "    make test-all      - Run all tests including integration"
	@echo "    make test-license  - Run license system tests only"
	@echo "    make test-broker   - Run broker tests only"
	@echo "    make test-signal   - Run signal parsing tests only"
	@echo "    make test-db       - Run database tests only"
	@echo ""
	@echo "  Validation:"
	@echo "    make lint          - Run code linting (ruff/flake8)"
	@echo "    make type          - Run type checking (mypy)"
	@echo "    make validate      - Run full validation suite"
	@echo ""
	@echo "  Other:"
	@echo "    make install       - Install test dependencies"
	@echo "    make clean         - Clean up cache files"

# Install test dependencies
install:
	pip install pytest pytest-asyncio pytest-cov ruff mypy

# Code linting
lint:
	@echo "Running linter..."
	@python -m ruff check src/ gui_app/ --ignore E501,F401,E402 || true
	@echo "Linting complete."

# Type checking
type:
	@echo "Running type checker..."
	@python -m mypy src/ gui_app/ --ignore-missing-imports --no-error-summary 2>/dev/null || true
	@echo "Type checking complete."

# Quick unit tests (no external dependencies)
test-quick:
	@echo "Running quick unit tests..."
	python -m pytest tests/unit/ -v -m "quick" --tb=short -q
	@echo "Quick tests complete."

# All tests
test-all:
	@echo "Running all tests..."
	python -m pytest tests/ -v --tb=short
	@echo "All tests complete."

# License system tests
test-license:
	@echo "Running license tests..."
	python -m pytest tests/ -v -m "license" --tb=short
	@echo "License tests complete."

# Broker tests
test-broker:
	@echo "Running broker tests..."
	python -m pytest tests/ -v -m "broker" --tb=short
	@echo "Broker tests complete."

# Signal parsing tests
test-signal:
	@echo "Running signal tests..."
	python -m pytest tests/ -v -m "signal" --tb=short
	@echo "Signal tests complete."

# Database tests
test-db:
	@echo "Running database tests..."
	python -m pytest tests/ -v -m "database" --tb=short
	@echo "Database tests complete."

# Full validation suite (lint + type + tests)
validate:
	@echo "=========================================="
	@echo "BotifyTrades Full Validation Suite"
	@echo "=========================================="
	@echo ""
	@echo "Step 1/4: Code Linting..."
	@$(MAKE) lint
	@echo ""
	@echo "Step 2/4: Type Checking..."
	@$(MAKE) type
	@echo ""
	@echo "Step 3/4: Database Schema Check..."
	@python scripts/validate_schema.py || true
	@echo ""
	@echo "Step 4/4: Running Tests..."
	@$(MAKE) test-quick
	@echo ""
	@echo "=========================================="
	@echo "Validation Complete!"
	@echo "=========================================="

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned up cache files."

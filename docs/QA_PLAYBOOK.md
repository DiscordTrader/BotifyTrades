# BotifyTrades QA Playbook

## Overview

This document defines the quality assurance standards, testing requirements, and workflows for BotifyTrades. All contributors must follow these guidelines to maintain code quality and prevent regressions.

## Testing Framework

### Directory Structure

```
qa/
├── tests/
│   ├── unit/           # Fast, isolated unit tests
│   │   ├── test_signal_parser.py
│   │   └── ...
│   ├── integration/    # Database, API, and broker tests
│   │   ├── test_database_operations.py
│   │   ├── test_multibroker_routing.py
│   │   ├── test_risk_management.py
│   │   ├── test_conditional_orders.py
│   │   └── test_pnl_tracking.py
│   ├── e2e/           # Full workflow tests
│   │   └── test_strict_routing.py
│   ├── mocks/         # Mock infrastructure
│   │   ├── mock_broker.py
│   │   ├── mock_discord.py
│   │   └── mock_market_data.py
│   ├── fixtures/      # Test data and factories
│   └── conftest.py    # Shared fixtures
```

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit          # Fast unit tests
@pytest.mark.integration   # Integration tests
@pytest.mark.e2e          # End-to-end tests
@pytest.mark.asyncio       # Async tests
```

## Running Tests

### Local Development

```bash
# Run all tests
pytest qa/tests -v

# Run unit tests only
pytest qa/tests/unit -v -m unit

# Run integration tests only
pytest qa/tests/integration -v -m integration

# Run with coverage
pytest qa/tests -v --cov=src --cov=gui_app --cov-report=html

# Run specific test file
pytest qa/tests/unit/test_signal_parser.py -v
```

### CI/CD Pipeline

Tests run automatically on:
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`

Pipeline stages:
1. **Lint** - flake8 syntax and style checks
2. **Unit Tests** - Fast unit tests with coverage
3. **Integration Tests** - Database and API tests
4. **E2E Tests** - Full workflow tests
5. **Coverage Report** - Minimum 50% coverage required

## Coverage Requirements

| Area | Minimum Coverage |
|------|-----------------|
| Signal Parser | 80% |
| Database Operations | 70% |
| Multi-Broker Routing | 80% |
| Risk Management | 70% |
| Overall | 50% |

## Test Requirements by Feature

### Signal Formats

Every signal format MUST have:
- [ ] Unit test for successful parsing
- [ ] Unit test for edge cases
- [ ] Test vector in `SignalTestVectors` class

**Formats requiring tests:**
- BTO/STC (standard)
- Bullwinkle (lotto)
- Jacob (ENTERED LONG)
- Z-scalps
- Jake
- Order Executed
- Bishop (I'M ENTERING)
- EvaPanda
- Conditional (over/above/under/below)

### Multi-Broker Routing

Required tests:
- [ ] STRICT routing: no primary broker fallback
- [ ] Single broker execution
- [ ] Multi-broker execution (all configured brokers)
- [ ] Broker not connected scenario
- [ ] Slow broker connection timing
- [ ] All-or-reject policy verification

### Risk Management

Required tests:
- [ ] Stop loss trigger at threshold
- [ ] Trailing stop activation after profit threshold
- [ ] Trailing stop trigger on pullback
- [ ] Trailing stop NOT on downside (before profit threshold)
- [ ] 4-tier profit targets in sequence
- [ ] Exit strategy modes (signal, risk, hybrid)
- [ ] Leave runner functionality

### Conditional Orders

Required tests:
- [ ] Over/above trigger conditions
- [ ] Under/below trigger conditions
- [ ] Timeout precedence (order → conditional → expiry)
- [ ] Channel settings linkage
- [ ] Order expiration (end of day, minute-based)

### PNL Tracking

Required tests:
- [ ] Open position P&L calculation
- [ ] Closed position P&L calculation
- [ ] FIFO lot matching
- [ ] Slippage tracking
- [ ] Signal vs Execution P&L comparison
- [ ] Entry price priority (intended > executed)

## Adding New Features

### Checklist for New Signal Formats

1. Add test vector to `qa/tests/conftest.py` → `SignalTestVectors`
2. Add unit test in `qa/tests/unit/test_signal_parser.py`
3. Update this playbook with new format
4. Verify all existing tests still pass

### Checklist for New Broker Support

1. Add mock broker in `qa/tests/mocks/mock_broker.py`
2. Add routing tests in `qa/tests/integration/test_multibroker_routing.py`
3. Add to broker readiness tests
4. Update coverage requirements

### Checklist for New Risk Features

1. Add tests in `qa/tests/integration/test_risk_management.py`
2. Verify per-channel settings flow correctly
3. Test interaction with exit strategy modes

## Debugging Test Failures

### Common Issues

1. **Import errors**: Ensure `sys.path` includes project root
2. **Database errors**: Check test_db fixture setup
3. **Async errors**: Use `@pytest.mark.asyncio` decorator
4. **Mock failures**: Verify mock state reset between tests

### Viewing Test Output

```bash
# Verbose output
pytest qa/tests -v

# Show print statements
pytest qa/tests -v -s

# Stop on first failure
pytest qa/tests -v -x

# Show local variables on failure
pytest qa/tests -v -l
```

## Pre-Commit Hooks

Install pre-commit hooks for local validation:

```bash
pip install pre-commit
pre-commit install
```

Pre-commit will run:
- flake8 linting
- Unit tests (fast subset)

## Reporting Issues

When a test fails in CI:
1. Check the GitHub Actions log for details
2. Reproduce locally with same Python version
3. Fix the issue or create a bug report
4. Update tests if behavior changed intentionally

## Maintenance

### Weekly Tasks
- Review test coverage report
- Update test vectors for new signal formats
- Clean up flaky tests

### Monthly Tasks
- Review and update this playbook
- Audit mock implementations
- Check for outdated dependencies

---

**Last Updated**: 2026-01-14
**Version**: 1.0.0

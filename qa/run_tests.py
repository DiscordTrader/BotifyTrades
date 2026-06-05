#!/usr/bin/env python3
"""
QA Test Runner
==============
Runs all QA tests and generates report.
"""

import unittest
import sys
import os
import json
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_unit_tests() -> Dict[str, Any]:
    """Run unit tests and return results"""
    loader = unittest.TestLoader()
    suite = loader.discover('qa/tests/unit', pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    
    return {
        'type': 'unit',
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors),
        'failed': len(result.failures),
        'errors': len(result.errors),
        'success': len(result.failures) == 0 and len(result.errors) == 0
    }


def run_integration_tests() -> Dict[str, Any]:
    """Run integration tests and return results"""
    loader = unittest.TestLoader()
    suite = loader.discover('qa/tests/integration', pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    
    return {
        'type': 'integration',
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors),
        'failed': len(result.failures),
        'errors': len(result.errors),
        'success': len(result.failures) == 0 and len(result.errors) == 0
    }


def run_qa_validation() -> Dict[str, Any]:
    """Run QA registry validation"""
    try:
        from qa.validator import run_qa_validation
        return run_qa_validation()
    except Exception as e:
        return {
            'error': str(e),
            'is_valid': False
        }


def run_all_tests() -> Dict[str, Any]:
    """Run all tests and validations"""
    print("=" * 60)
    print("BotifyTrades QA Test Suite")
    print("=" * 60)
    print()
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'unit_tests': None,
        'integration_tests': None,
        'qa_validation': None,
        'overall_success': True
    }
    
    # Run unit tests
    print("Running unit tests...")
    results['unit_tests'] = run_unit_tests()
    print(f"  Unit: {results['unit_tests']['passed']}/{results['unit_tests']['total']} passed")
    if not results['unit_tests']['success']:
        results['overall_success'] = False
    
    # Run integration tests
    print("Running integration tests...")
    results['integration_tests'] = run_integration_tests()
    print(f"  Integration: {results['integration_tests']['passed']}/{results['integration_tests']['total']} passed")
    if not results['integration_tests']['success']:
        results['overall_success'] = False
    
    # Run QA validation
    print("Running QA registry validation...")
    results['qa_validation'] = run_qa_validation()
    if isinstance(results['qa_validation'], dict):
        is_valid = results['qa_validation'].get('is_valid', False)
        print(f"  QA Validation: {'PASSED' if is_valid else 'FAILED'}")
        if not is_valid:
            results['overall_success'] = False
    
    print()
    print("=" * 60)
    print(f"Overall Result: {'PASSED' if results['overall_success'] else 'FAILED'}")
    print("=" * 60)
    
    return results


def main():
    """Main entry point"""
    results = run_all_tests()
    
    # Save results to file
    with open('qa/test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # Exit with appropriate code
    sys.exit(0 if results['overall_success'] else 1)


if __name__ == '__main__':
    main()

"""
Diagnostics Manager
===================
Orchestrates all diagnostic checks.
"""

import time
from typing import List, Optional, Dict, Any
from datetime import datetime

from .diagnostic_types import CheckResult, CheckStatus, DiagnosticCategory, DiagnosticsSummary
from .checks import get_all_checks


class DiagnosticsManager:
    """Manages and runs all diagnostic checks."""
    
    def __init__(self):
        self._checks = get_all_checks()
        self._last_run: Optional[DiagnosticsSummary] = None
    
    def run_all(self, categories: Optional[List[DiagnosticCategory]] = None) -> DiagnosticsSummary:
        """Run all diagnostic checks and return summary."""
        start_time = time.time()
        results: List[CheckResult] = []
        
        for check_func in self._checks:
            try:
                result = check_func()
                
                if categories and result.category not in categories:
                    continue
                    
                results.append(result)
                print(f"[DIAG] {result.status.value.upper():8} | {result.name}: {result.message}")
            except Exception as e:
                results.append(CheckResult(
                    name=check_func.__name__,
                    category=DiagnosticCategory.SYSTEM,
                    status=CheckStatus.FAIL,
                    message=f"Check crashed: {str(e)}"
                ))
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        summary = DiagnosticsSummary(
            total_checks=len(results),
            passed=sum(1 for r in results if r.status == CheckStatus.PASS),
            warnings=sum(1 for r in results if r.status == CheckStatus.WARN),
            failed=sum(1 for r in results if r.status == CheckStatus.FAIL),
            skipped=sum(1 for r in results if r.status == CheckStatus.SKIP),
            results=results,
            run_time_ms=elapsed_ms
        )
        
        self._last_run = summary
        return summary
    
    def run_category(self, category: DiagnosticCategory) -> DiagnosticsSummary:
        """Run checks for a specific category."""
        return self.run_all(categories=[category])
    
    def get_last_run(self) -> Optional[DiagnosticsSummary]:
        """Get results from last diagnostic run."""
        return self._last_run
    
    def print_summary(self, summary: DiagnosticsSummary):
        """Print a formatted summary to console."""
        print("\n" + "=" * 60)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 60)
        print(f"Total Checks: {summary.total_checks}")
        print(f"  ✓ Passed:   {summary.passed}")
        print(f"  ⚠ Warnings: {summary.warnings}")
        print(f"  ✗ Failed:   {summary.failed}")
        print(f"  ○ Skipped:  {summary.skipped}")
        print(f"Run Time:     {summary.run_time_ms:.1f}ms")
        print(f"Overall:      {summary.overall_status.value.upper()}")
        print("=" * 60)
        
        if summary.failed > 0:
            print("\nFAILED CHECKS:")
            for r in summary.results:
                if r.status == CheckStatus.FAIL:
                    print(f"  ✗ {r.name}: {r.message}")
                    if r.remediation:
                        print(f"    → Fix: {r.remediation}")
        
        if summary.warnings > 0:
            print("\nWARNINGS:")
            for r in summary.results:
                if r.status == CheckStatus.WARN:
                    print(f"  ⚠ {r.name}: {r.message}")
                    if r.remediation:
                        print(f"    → Fix: {r.remediation}")
        
        print()


_manager: Optional[DiagnosticsManager] = None


def get_manager() -> DiagnosticsManager:
    """Get singleton diagnostics manager."""
    global _manager
    if _manager is None:
        _manager = DiagnosticsManager()
    return _manager


def run_all_checks(print_summary: bool = True) -> DiagnosticsSummary:
    """Run all diagnostic checks."""
    manager = get_manager()
    summary = manager.run_all()
    if print_summary:
        manager.print_summary(summary)
    return summary


def get_diagnostics_summary() -> Dict[str, Any]:
    """Get last diagnostic run as dict (for API)."""
    manager = get_manager()
    last_run = manager.get_last_run()
    if last_run:
        return last_run.to_dict()
    
    summary = manager.run_all()
    return summary.to_dict()

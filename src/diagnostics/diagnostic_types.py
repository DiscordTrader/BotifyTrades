"""
Diagnostic Types
================
Data classes for diagnostic check results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime


class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warning"
    FAIL = "fail"
    SKIP = "skipped"


class DiagnosticCategory(Enum):
    DATABASE = "database"
    RISK_MANAGEMENT = "risk_management"
    OPTIONS_CHAIN = "options_chain"
    BROKER_WEBULL = "broker_webull"
    BROKER_ALPACA = "broker_alpaca"
    BROKER_IBKR = "broker_ibkr"
    LICENSE = "license"
    DISCORD = "discord"
    SYSTEM = "system"


@dataclass
class CheckResult:
    name: str
    category: DiagnosticCategory
    status: CheckStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    remediation: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'category': self.category.value,
            'status': self.status.value,
            'message': self.message,
            'details': self.details,
            'remediation': self.remediation,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class DiagnosticsSummary:
    total_checks: int
    passed: int
    warnings: int
    failed: int
    skipped: int
    results: List[CheckResult] = field(default_factory=list)
    run_time_ms: float = 0
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def overall_status(self) -> CheckStatus:
        if self.failed > 0:
            return CheckStatus.FAIL
        elif self.warnings > 0:
            return CheckStatus.WARN
        return CheckStatus.PASS
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_checks': self.total_checks,
            'passed': self.passed,
            'warnings': self.warnings,
            'failed': self.failed,
            'skipped': self.skipped,
            'overall_status': self.overall_status.value,
            'results': [r.to_dict() for r in self.results],
            'run_time_ms': self.run_time_ms,
            'timestamp': self.timestamp.isoformat()
        }

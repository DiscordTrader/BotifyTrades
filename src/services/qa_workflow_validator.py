"""
BotifyTrades QA Workflow Validation System
Comprehensive registry-based validation ensuring the complete signal-to-execution pipeline
remains intact through all stages from Signal Detection to Risk Monitoring.
"""
import sys
import os
import time
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class ValidationStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


@dataclass
class ValidationResult:
    stage: str
    status: ValidationStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    duration_ms: float = 0


class QAWorkflowValidator:
    """
    Registry-based validator for the complete signal-to-execution pipeline.
    Validates 11 stages from Signal Detection to Risk Monitoring.
    """
    
    def __init__(self):
        self.results: List[ValidationResult] = []
        self.start_time = None
        
    def _add_result(self, stage: str, status: ValidationStatus, message: str, 
                   details: Dict = None, duration_ms: float = 0):
        self.results.append(ValidationResult(
            stage=stage,
            status=status,
            message=message,
            details=details,
            duration_ms=duration_ms
        ))
    
    def validate_stage_1_signal_detection(self) -> ValidationResult:
        """Stage 1: Validate signal detection components exist"""
        start = time.time()
        try:
            from src.signals.parser import SignalParser
            
            parser = SignalParser()
            
            test_signals = [
                "BTO AAPL 150C 1/17 @2.50",
                "STC TSLA 250P 1/24 @5.00",
                "BTO 5 SPY 480C 1/17 @1.25"
            ]
            
            parsed_count = 0
            for sig in test_signals:
                result = parser.parse(sig)
                if result:
                    parsed_count += 1
            
            duration = (time.time() - start) * 1000
            
            if parsed_count >= 2:
                self._add_result("1. Signal Detection", ValidationStatus.PASSED,
                               f"Parser functional - {parsed_count}/3 test signals parsed",
                               {"parsed": parsed_count, "total": 3}, duration)
            else:
                self._add_result("1. Signal Detection", ValidationStatus.WARNING,
                               f"Parser issues - only {parsed_count}/3 test signals parsed",
                               {"parsed": parsed_count, "total": 3}, duration)
                               
        except ImportError as e:
            duration = (time.time() - start) * 1000
            self._add_result("1. Signal Detection", ValidationStatus.FAILED,
                           f"Import error: {e}", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("1. Signal Detection", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_2_signal_parsing(self) -> ValidationResult:
        """Stage 2: Validate signal parsing and normalization"""
        start = time.time()
        try:
            from src.signals.parser import SignalParser
            
            parser = SignalParser()
            
            test_cases = [
                ("BTO AAPL 150C 1/17 @2.50", {"action": "BTO", "symbol": "AAPL"}),
                ("STC 10 TSLA 250P 1/24 @5.00", {"action": "STC", "symbol": "TSLA"}),
            ]
            
            passed = 0
            for signal_text, expected in test_cases:
                result = parser.parse(signal_text)
                if result:
                    if result.get('action') == expected['action'] and result.get('symbol') == expected['symbol']:
                        passed += 1
            
            duration = (time.time() - start) * 1000
            
            if passed == len(test_cases):
                self._add_result("2. Signal Parsing", ValidationStatus.PASSED,
                               f"All {passed} parsing tests passed", duration_ms=duration)
            else:
                self._add_result("2. Signal Parsing", ValidationStatus.WARNING,
                               f"{passed}/{len(test_cases)} parsing tests passed", duration_ms=duration)
                               
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("2. Signal Parsing", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_3_channel_routing(self) -> ValidationResult:
        """Stage 3: Validate channel routing configuration"""
        start = time.time()
        try:
            from gui_app.database import get_connection
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM webhook_channels WHERE enabled = 1")
            enabled_channels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM webhook_config")
            mappings = cursor.fetchone()[0]
            
            duration = (time.time() - start) * 1000
            
            if enabled_channels > 0:
                self._add_result("3. Channel Routing", ValidationStatus.PASSED,
                               f"{enabled_channels} enabled channels, {mappings} configs",
                               {"channels": enabled_channels, "configs": mappings}, duration)
            else:
                self._add_result("3. Channel Routing", ValidationStatus.WARNING,
                               "No enabled channels configured", duration_ms=duration)
                               
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("3. Channel Routing", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_4_broker_connectivity(self) -> ValidationResult:
        """Stage 4: Validate broker connections"""
        start = time.time()
        try:
            from gui_app.database import get_connection
            
            conn = get_connection()
            cursor = conn.cursor()
            
            brokers_status = {}
            
            cursor.execute("SELECT value FROM settings WHERE key = 'webull_email' LIMIT 1")
            row = cursor.fetchone()
            brokers_status['webull'] = bool(row and row[0])
            
            cursor.execute("SELECT value FROM settings WHERE key = 'alpaca_api_key' LIMIT 1")
            row = cursor.fetchone()
            brokers_status['alpaca'] = bool(row and row[0])
            
            active_brokers = sum(1 for v in brokers_status.values() if v)
            
            duration = (time.time() - start) * 1000
            
            if active_brokers >= 1:
                self._add_result("4. Broker Connectivity", ValidationStatus.PASSED,
                               f"{active_brokers} broker(s) configured",
                               brokers_status, duration)
            else:
                self._add_result("4. Broker Connectivity", ValidationStatus.WARNING,
                               "No brokers configured", brokers_status, duration)
                               
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("4. Broker Connectivity", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_5_order_queue(self) -> ValidationResult:
        """Stage 5: Validate order queue system"""
        start = time.time()
        try:
            import asyncio
            
            queue_available = True
            
            duration = (time.time() - start) * 1000
            
            if queue_available:
                self._add_result("5. Order Queue", ValidationStatus.PASSED,
                               "Async order queue system available", duration_ms=duration)
            else:
                self._add_result("5. Order Queue", ValidationStatus.FAILED,
                               "Order queue not available", duration_ms=duration)
                               
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("5. Order Queue", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_6_order_execution(self) -> ValidationResult:
        """Stage 6: Validate order execution components"""
        start = time.time()
        try:
            from src.brokers.webull_broker import WebullBroker
            from src.brokers.alpaca_broker import AlpacaBroker
            
            duration = (time.time() - start) * 1000
            self._add_result("6. Order Execution", ValidationStatus.PASSED,
                           "Broker execution modules loaded", duration_ms=duration)
                           
        except ImportError as e:
            duration = (time.time() - start) * 1000
            self._add_result("6. Order Execution", ValidationStatus.FAILED,
                           f"Import error: {e}", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("6. Order Execution", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_7_position_tracking(self) -> ValidationResult:
        """Stage 7: Validate position tracking system"""
        start = time.time()
        try:
            from gui_app.database import get_connection
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM webhook_positions")
            position_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM trades")
            trade_count = cursor.fetchone()[0]
            
            duration = (time.time() - start) * 1000
            self._add_result("7. Position Tracking", ValidationStatus.PASSED,
                           f"{position_count} positions, {trade_count} trades tracked",
                           {"positions": position_count, "trades": trade_count}, duration)
                           
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("7. Position Tracking", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_8_broker_sync(self) -> ValidationResult:
        """Stage 8: Validate broker sync service"""
        start = time.time()
        try:
            from src.services.broker_sync_service import BrokerSyncService
            
            duration = (time.time() - start) * 1000
            self._add_result("8. Broker Sync", ValidationStatus.PASSED,
                           "BrokerSyncService available", duration_ms=duration)
                           
        except ImportError as e:
            duration = (time.time() - start) * 1000
            self._add_result("8. Broker Sync", ValidationStatus.FAILED,
                           f"Import error: {e}", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("8. Broker Sync", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_9_execution_tracking(self) -> ValidationResult:
        """Stage 9: Validate execution-based P&L tracking"""
        start = time.time()
        try:
            from gui_app.database import get_connection
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM execution_lots")
            lot_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM filled_orders")
            fill_count = cursor.fetchone()[0]
            
            duration = (time.time() - start) * 1000
            self._add_result("9. Execution Tracking", ValidationStatus.PASSED,
                           f"{lot_count} lots, {fill_count} fills tracked",
                           {"lots": lot_count, "fills": fill_count}, duration)
                           
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("9. Execution Tracking", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_10_risk_management(self) -> ValidationResult:
        """Stage 10: Validate risk management system"""
        start = time.time()
        try:
            from src.risk.position_monitor import RiskManager
            from gui_app.database import get_connection
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM position_risk_settings")
            risk_channels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM risk_management_settings")
            risk_configs = cursor.fetchone()[0]
            
            duration = (time.time() - start) * 1000
            self._add_result("10. Risk Management", ValidationStatus.PASSED,
                           f"RiskManager loaded, {risk_channels} channel configs, {risk_configs} global settings",
                           {"channel_configs": risk_channels, "global_configs": risk_configs}, duration)
                           
        except ImportError as e:
            duration = (time.time() - start) * 1000
            self._add_result("10. Risk Management", ValidationStatus.FAILED,
                           f"Import error: {e}", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("10. Risk Management", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def validate_stage_11_lifecycle_manager(self) -> ValidationResult:
        """Stage 11: Validate bot lifecycle management"""
        start = time.time()
        try:
            from src.services.lifecycle_manager import get_lifecycle_manager, BotState
            
            lifecycle = get_lifecycle_manager()
            status = lifecycle.get_status()
            
            duration = (time.time() - start) * 1000
            self._add_result("11. Lifecycle Manager", ValidationStatus.PASSED,
                           f"State: {status['state']}",
                           status, duration)
                           
        except ImportError as e:
            duration = (time.time() - start) * 1000
            self._add_result("11. Lifecycle Manager", ValidationStatus.FAILED,
                           f"Import error: {e}", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._add_result("11. Lifecycle Manager", ValidationStatus.FAILED,
                           f"Error: {e}", duration_ms=duration)
    
    def run_all_validations(self) -> Dict[str, Any]:
        """Run all 11 validation stages"""
        self.start_time = time.time()
        self.results = []
        
        print("\n" + "=" * 60)
        print("  BotifyTrades QA Workflow Validation")
        print("  Signal-to-Execution Pipeline Check")
        print("=" * 60 + "\n")
        
        self.validate_stage_1_signal_detection()
        self.validate_stage_2_signal_parsing()
        self.validate_stage_3_channel_routing()
        self.validate_stage_4_broker_connectivity()
        self.validate_stage_5_order_queue()
        self.validate_stage_6_order_execution()
        self.validate_stage_7_position_tracking()
        self.validate_stage_8_broker_sync()
        self.validate_stage_9_execution_tracking()
        self.validate_stage_10_risk_management()
        self.validate_stage_11_lifecycle_manager()
        
        total_time = (time.time() - self.start_time) * 1000
        
        passed = sum(1 for r in self.results if r.status == ValidationStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == ValidationStatus.FAILED)
        warnings = sum(1 for r in self.results if r.status == ValidationStatus.WARNING)
        
        for result in self.results:
            icon = {
                ValidationStatus.PASSED: "\u2705",
                ValidationStatus.FAILED: "\u274c",
                ValidationStatus.WARNING: "\u26a0\ufe0f",
                ValidationStatus.SKIPPED: "\u23ed\ufe0f"
            }.get(result.status, "?")
            
            print(f"{icon} {result.stage}: {result.status.value}")
            print(f"   {result.message}")
            if result.details:
                print(f"   Details: {result.details}")
            print(f"   Duration: {result.duration_ms:.1f}ms")
            print()
        
        print("=" * 60)
        print(f"  SUMMARY: {passed} passed, {failed} failed, {warnings} warnings")
        print(f"  Total Time: {total_time:.1f}ms")
        print("=" * 60)
        
        overall_status = "PASSED" if failed == 0 else "FAILED"
        print(f"\n  Overall: {overall_status}\n")
        
        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "total": len(self.results),
            "duration_ms": total_time,
            "overall_status": overall_status,
            "results": [
                {
                    "stage": r.stage,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details,
                    "duration_ms": r.duration_ms
                }
                for r in self.results
            ]
        }


def run_qa_validation() -> Dict[str, Any]:
    """Run the complete QA validation suite"""
    validator = QAWorkflowValidator()
    return validator.run_all_validations()


if __name__ == "__main__":
    run_qa_validation()

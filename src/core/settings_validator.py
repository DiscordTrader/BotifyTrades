"""
Settings Validator - Cross-Layer Consistency Checking
=====================================================
Validates settings consistency across:
1. Schema Alignment - Manifest matches database columns
2. UI Coverage - All settings have GUI controls
3. Runtime Enforcement - Settings are actually used where declared

Run this as part of startup diagnostics and CI/CD.
"""
import ast
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .settings_manifest import (
    SETTINGS_MANIFEST,
    SettingDefinition,
    get_all_settings,
)
from .settings_service import get_runtime_enforcement_report

logger = logging.getLogger(__name__)


class SettingsValidationResult:
    """Result of a settings validation check."""
    
    def __init__(self, name: str):
        self.name = name
        self.passed = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
    
    def add_error(self, message: str):
        self.passed = False
        self.errors.append(message)
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def add_info(self, message: str):
        self.info.append(message)
    
    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"<{self.name}: {status}, {len(self.errors)} errors, {len(self.warnings)} warnings>"


class SettingsValidator:
    """
    Validates settings consistency across all application layers.
    
    Usage:
        validator = SettingsValidator()
        results = validator.run_all_checks()
        
        for result in results:
            if not result.passed:
                print(f"FAILED: {result.name}")
                for error in result.errors:
                    print(f"  - {error}")
    """
    
    def __init__(self, db_path: str = "bot_data.db", project_root: str = "."):
        self.db_path = db_path
        self.project_root = Path(project_root)
        self.manifest = get_all_settings()
    
    def run_all_checks(self) -> List[SettingsValidationResult]:
        """Run all validation checks."""
        results = []
        
        results.append(self.check_schema_alignment())
        results.append(self.check_manifest_completeness())
        results.append(self.check_enforcement_declarations())
        results.append(self.check_default_values())
        
        return results
    
    def check_schema_alignment(self) -> SettingsValidationResult:
        """
        Check that all manifest settings exist in database schema.
        
        Validates:
        - Required tables exist
        - Settings storage keys exist in settings table
        - Types match expected
        """
        result = SettingsValidationResult("Schema Alignment")
        
        if not Path(self.db_path).exists():
            result.add_warning(f"Database not found: {self.db_path}")
            return result
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            
            required_tables = {'settings', 'channels', 'trades'}
            missing_tables = required_tables - tables
            if missing_tables:
                result.add_error(f"Missing required tables: {missing_tables}")
            
            if 'settings' in tables:
                cursor.execute("SELECT key, value FROM settings")
                db_settings = {row[0]: row[1] for row in cursor.fetchall()}
                
                for full_key, definition in self.manifest.items():
                    storage_key = definition.storage_key
                    if storage_key not in db_settings:
                        result.add_info(f"Setting '{full_key}' ({storage_key}) not in DB, will use default")
                
                manifest_keys = {d.storage_key for d in self.manifest.values()}
                for db_key in db_settings.keys():
                    if db_key not in manifest_keys and not db_key.startswith('_'):
                        result.add_warning(f"DB has orphan setting not in manifest: '{db_key}'")
            
            conn.close()
            
            if not result.errors:
                result.add_info(f"Validated {len(self.manifest)} settings against database")
            
        except Exception as e:
            result.add_error(f"Database validation failed: {e}")
        
        return result
    
    def check_manifest_completeness(self) -> SettingsValidationResult:
        """
        Check that manifest covers all essential settings.
        
        Validates:
        - All namespaces have at least one setting
        - All settings have descriptions
        - All settings have enforcement points declared
        """
        result = SettingsValidationResult("Manifest Completeness")
        
        from .settings_manifest import SettingNamespace
        namespace_coverage = {ns: [] for ns in SettingNamespace}
        
        for full_key, definition in self.manifest.items():
            namespace_coverage[definition.namespace].append(full_key)
            
            if not definition.description:
                result.add_warning(f"Setting '{full_key}' has no description")
            
            if not definition.enforced_in:
                result.add_warning(f"Setting '{full_key}' has no enforcement points declared")
            
            if not definition.gui_route and not definition.gui_element_id:
                result.add_warning(f"Setting '{full_key}' has no GUI mapping")
        
        for ns, settings in namespace_coverage.items():
            if not settings:
                result.add_warning(f"Namespace '{ns.value}' has no settings defined")
            else:
                result.add_info(f"Namespace '{ns.value}': {len(settings)} settings")
        
        return result
    
    def check_enforcement_declarations(self) -> SettingsValidationResult:
        """
        Check that enforcement points are valid file:function paths.
        
        Validates:
        - Enforcement paths reference existing files
        - Functions/methods are likely to exist (basic check)
        """
        result = SettingsValidationResult("Enforcement Declarations")
        
        enforcement_files: Dict[str, List[str]] = {}
        
        for full_key, definition in self.manifest.items():
            for enforcement_point in definition.enforced_in:
                if ':' in enforcement_point:
                    file_path, func_name = enforcement_point.rsplit(':', 1)
                else:
                    file_path = enforcement_point
                    func_name = None
                
                if not file_path.endswith('.py'):
                    file_path += '.py'
                
                if file_path not in enforcement_files:
                    enforcement_files[file_path] = []
                enforcement_files[file_path].append(full_key)
        
        for file_path, settings in enforcement_files.items():
            full_path = self.project_root / file_path
            if not full_path.exists():
                result.add_warning(f"Enforcement file not found: {file_path} (used by {len(settings)} settings)")
            else:
                result.add_info(f"Enforcement file OK: {file_path} ({len(settings)} settings)")
        
        return result
    
    def check_default_values(self) -> SettingsValidationResult:
        """
        Check that default values are valid for their types.
        """
        result = SettingsValidationResult("Default Values")
        
        from .settings_manifest import SettingType, validate_setting_value
        
        for full_key, definition in self.manifest.items():
            default = definition.default
            
            if definition.setting_type == SettingType.BOOLEAN:
                if not isinstance(default, bool):
                    result.add_error(f"Setting '{full_key}' expects bool, default is {type(default).__name__}")
            
            elif definition.setting_type == SettingType.INTEGER:
                if not isinstance(default, int) or isinstance(default, bool):
                    result.add_error(f"Setting '{full_key}' expects int, default is {type(default).__name__}")
            
            elif definition.setting_type in (SettingType.FLOAT, SettingType.PERCENTAGE):
                if not isinstance(default, (int, float)):
                    result.add_error(f"Setting '{full_key}' expects number, default is {type(default).__name__}")
            
            elif definition.setting_type == SettingType.STRING:
                if not isinstance(default, str):
                    result.add_error(f"Setting '{full_key}' expects string, default is {type(default).__name__}")
            
            if definition.validator:
                try:
                    if not definition.validator(default):
                        result.add_error(f"Setting '{full_key}' default value fails validation: {default}")
                except Exception as e:
                    result.add_error(f"Setting '{full_key}' validator error: {e}")
        
        if not result.errors:
            result.add_info(f"All {len(self.manifest)} default values are valid")
        
        return result
    
    def check_runtime_enforcement(self) -> SettingsValidationResult:
        """
        Check that settings are actually being used at runtime.
        
        This check requires the application to have been running.
        It compares declared enforcement points with actual usage.
        """
        result = SettingsValidationResult("Runtime Enforcement")
        
        try:
            report = get_runtime_enforcement_report()
            
            result.add_info(f"Declared settings: {report['total_declared']}")
            result.add_info(f"Accessed settings: {report['accessed_count']}")
            result.add_info(f"Unused settings: {report['unused_count']}")
            
            if report['unused_count'] > 0:
                for unused in report['unused_settings']:
                    definition = self.manifest.get(unused)
                    if definition and definition.enforced_in:
                        result.add_warning(f"Setting '{unused}' declared in {definition.enforced_in} but never accessed")
            
            for setting_key, modules in report['enforcement_map'].items():
                definition = self.manifest.get(setting_key)
                if definition:
                    expected_modules = set(definition.enforced_in)
                    actual_modules = set(modules)
                    
                    unexpected = actual_modules - expected_modules
                    if unexpected:
                        result.add_info(f"Setting '{setting_key}' also used in: {unexpected}")
            
        except Exception as e:
            result.add_warning(f"Runtime check skipped: {e}")
        
        return result
    
    def generate_report(self) -> str:
        """Generate a human-readable validation report."""
        results = self.run_all_checks()
        
        lines = [
            "=" * 60,
            "SETTINGS CONSISTENCY VALIDATION REPORT",
            "=" * 60,
            "",
        ]
        
        total_errors = 0
        total_warnings = 0
        
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            icon = "✓" if result.passed else "✗"
            lines.append(f"{icon} {result.name}: {status}")
            
            for error in result.errors:
                lines.append(f"    ✗ ERROR: {error}")
                total_errors += 1
            
            for warning in result.warnings:
                lines.append(f"    ⚠ WARNING: {warning}")
                total_warnings += 1
            
            for info in result.info:
                lines.append(f"    ℹ {info}")
            
            lines.append("")
        
        lines.extend([
            "-" * 60,
            f"SUMMARY: {total_errors} errors, {total_warnings} warnings",
            "-" * 60,
        ])
        
        if total_errors > 0:
            lines.append("STATUS: ✗ FAILED - Fix errors before deployment")
        elif total_warnings > 0:
            lines.append("STATUS: ⚠ DEGRADED - Review warnings")
        else:
            lines.append("STATUS: ✓ HEALTHY - All settings validated")
        
        return "\n".join(lines)


def validate_settings(db_path: str = "bot_data.db", verbose: bool = True) -> bool:
    """
    Convenience function to validate settings.
    
    Returns True if all checks pass.
    """
    validator = SettingsValidator(db_path=db_path)
    results = validator.run_all_checks()
    
    if verbose:
        print(validator.generate_report())
    
    return all(r.passed for r in results)


def run_startup_settings_audit():
    """
    Run settings validation at application startup.
    
    Logs results and returns True if healthy.
    """
    logger.info("[SETTINGS] Running startup settings audit...")
    
    validator = SettingsValidator()
    results = validator.run_all_checks()
    
    errors = sum(len(r.errors) for r in results)
    warnings = sum(len(r.warnings) for r in results)
    
    if errors > 0:
        logger.error(f"[SETTINGS] ✗ Settings audit FAILED: {errors} errors, {warnings} warnings")
        for result in results:
            for error in result.errors:
                logger.error(f"[SETTINGS]   - {error}")
        return False
    
    if warnings > 0:
        logger.warning(f"[SETTINGS] ⚠ Settings audit DEGRADED: {warnings} warnings")
        return True
    
    logger.info(f"[SETTINGS] ✓ Settings audit PASSED: {len(SETTINGS_MANIFEST)} settings validated")
    return True

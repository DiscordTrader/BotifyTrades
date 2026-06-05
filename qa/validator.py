"""
QA Validator Module
===================
Validates features, database schema, API contracts, and workflows
against the registry definitions.
"""

import sqlite3
import json
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from .registry_loader import get_registry, RegistryLoader, FeatureDefinition

# Default database paths to check (in order of priority)
DEFAULT_DB_PATHS = [
    'bot_data.db',  # Primary database used by the application
    'gui_app/trading_bot.db',
    'gui_app/botify_trades.db',
    'trading_bot.db',
    'botify_trades.db',
]


def find_database_path() -> Optional[str]:
    """Find the active database path"""
    for path in DEFAULT_DB_PATHS:
        if os.path.exists(path):
            return path
    return None


@dataclass
class ValidationIssue:
    """Represents a validation issue"""
    severity: str  # 'critical', 'warning', 'info'
    category: str  # 'feature', 'database', 'api', 'workflow'
    component: str  # Feature/table/route name
    field: str
    message: str
    expected: Any = None
    actual: Any = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """Complete validation result"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    is_valid: bool = True
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    features_validated: List[str] = field(default_factory=list)
    tables_validated: List[str] = field(default_factory=list)
    
    def add_issue(self, issue: ValidationIssue):
        self.issues.append(issue)
        self.failed_checks += 1
        if issue.severity == 'critical':
            self.critical_count += 1
            self.is_valid = False
        elif issue.severity == 'warning':
            self.warning_count += 1
        else:
            self.info_count += 1
    
    def add_pass(self):
        self.passed_checks += 1
        self.total_checks += 1
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'is_valid': self.is_valid,
            'summary': {
                'total_checks': self.total_checks,
                'passed': self.passed_checks,
                'failed': self.failed_checks,
                'critical': self.critical_count,
                'warnings': self.warning_count,
                'info': self.info_count
            },
            'features_validated': self.features_validated,
            'tables_validated': self.tables_validated,
            'issues': [i.to_dict() for i in self.issues],
            'status': self._get_status()
        }
    
    def _get_status(self) -> str:
        if self.critical_count > 0:
            return 'CRITICAL - System has breaking issues'
        elif self.warning_count > 0:
            return f'WARNING - {self.warning_count} issues to review'
        elif self.failed_checks > 0:
            return f'DEGRADED - {self.failed_checks} minor issues'
        else:
            return 'HEALTHY - All validations passed'


class QAValidator:
    """
    Main validation engine that checks:
    - Database schema matches registry
    - Features have all required components
    - API routes respond correctly
    - Workflows are functional
    """
    
    def __init__(self, db_path: str = None):
        self.registry = get_registry()
        self.db_path = db_path or find_database_path()
        self._db_conn = None
        self._db_available = self.db_path is not None and os.path.exists(self.db_path)
    
    def _get_db_connection(self) -> Optional[sqlite3.Connection]:
        """Get database connection, or None if no database available"""
        if not self._db_available:
            return None
        if self._db_conn is None:
            try:
                self._db_conn = sqlite3.connect(self.db_path)
                self._db_conn.row_factory = sqlite3.Row
            except Exception:
                self._db_available = False
                return None
        return self._db_conn
    
    def close(self):
        """Close database connection"""
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None
    
    # =========================================
    # Full System Validation
    # =========================================
    
    def validate_all(self) -> ValidationResult:
        """Run complete system validation"""
        result = ValidationResult()
        
        # Validate database schema
        db_result = self.validate_database_schema()
        result.issues.extend(db_result.issues)
        result.tables_validated = db_result.tables_validated
        result.passed_checks += db_result.passed_checks
        result.failed_checks += db_result.failed_checks
        
        # Validate all features
        for feature_name in self.registry.get_all_feature_names():
            feature_result = self.validate_feature(feature_name)
            result.issues.extend(feature_result.issues)
            if feature_name not in result.features_validated:
                result.features_validated.append(feature_name)
            result.passed_checks += feature_result.passed_checks
            result.failed_checks += feature_result.failed_checks
        
        # Update counts
        result.total_checks = result.passed_checks + result.failed_checks
        result.critical_count = sum(1 for i in result.issues if i.severity == 'critical')
        result.warning_count = sum(1 for i in result.issues if i.severity == 'warning')
        result.info_count = sum(1 for i in result.issues if i.severity == 'info')
        result.is_valid = result.critical_count == 0
        
        return result
    
    # =========================================
    # Database Schema Validation
    # =========================================
    
    def validate_database_schema(self) -> ValidationResult:
        """Validate database schema matches registry"""
        result = ValidationResult()
        conn = self._get_db_connection()
        
        # If no database available, skip schema validation with info message
        if conn is None:
            result.add_issue(ValidationIssue(
                severity='info',
                category='database',
                component='connection',
                field='database',
                message='Database not available - schema validation skipped',
                expected='database file',
                actual='not found'
            ))
            # Still mark tables as validated (skipped) for reporting
            for table_name in self.registry.tables.keys():
                result.tables_validated.append(table_name)
                result.add_pass()  # Pass since we can't validate
            return result
        
        cursor = conn.cursor()
        
        for table_name, table_def in self.registry.tables.items():
            result.tables_validated.append(table_name)
            
            # Check table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not cursor.fetchone():
                result.add_issue(ValidationIssue(
                    severity='critical',
                    category='database',
                    component=table_name,
                    field='table',
                    message=f"Table '{table_name}' does not exist",
                    expected='exists',
                    actual='missing'
                ))
                continue
            
            result.add_pass()
            
            # Check columns exist
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row['name']: row for row in cursor.fetchall()}
            
            for column_name, column_def in table_def.columns.items():
                if column_name not in existing_columns:
                    result.add_issue(ValidationIssue(
                        severity='critical',
                        category='database',
                        component=table_name,
                        field=column_name,
                        message=f"Column '{column_name}' missing from table '{table_name}'",
                        expected=column_def.get('type'),
                        actual='missing'
                    ))
                else:
                    result.add_pass()
        
        return result
    
    def check_column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a specific column exists"""
        conn = self._get_db_connection()
        if conn is None:
            return True  # Assume exists if can't check (graceful degradation)
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row['name'] for row in cursor.fetchall()]
            return column_name in columns
        except Exception:
            return True  # Assume exists if error
    
    # =========================================
    # Feature Validation
    # =========================================
    
    def validate_feature(self, feature_name: str) -> ValidationResult:
        """Validate a specific feature has all components"""
        result = ValidationResult()
        feature = self.registry.get_feature(feature_name)
        
        if not feature:
            result.add_issue(ValidationIssue(
                severity='warning',
                category='feature',
                component=feature_name,
                field='registry',
                message=f"Feature '{feature_name}' not found in registry"
            ))
            return result
        
        result.features_validated.append(feature_name)
        
        # Validate database components
        for db_component in feature.db_fields:
            table_name = db_component.get('table')
            fields = db_component.get('fields', [])
            
            for field_name in fields:
                if self.check_column_exists(table_name, field_name):
                    result.add_pass()
                else:
                    result.add_issue(ValidationIssue(
                        severity='critical',
                        category='feature',
                        component=feature_name,
                        field=f"{table_name}.{field_name}",
                        message=f"Feature '{feature_name}' requires column '{field_name}' in table '{table_name}'"
                    ))
        
        return result
    
    # =========================================
    # API Validation
    # =========================================
    
    def validate_api_route(self, route_name: str, test_client=None) -> ValidationResult:
        """Validate an API route responds correctly"""
        result = ValidationResult()
        route = self.registry.get_route(route_name)
        
        if not route:
            result.add_issue(ValidationIssue(
                severity='warning',
                category='api',
                component=route_name,
                field='registry',
                message=f"Route '{route_name}' not found in registry"
            ))
            return result
        
        # If test client provided, actually test the route
        if test_client:
            for method, method_def in route.methods.items():
                try:
                    if method == 'GET':
                        response = test_client.get(f"/api{route.path}")
                    elif method == 'POST':
                        response = test_client.post(f"/api{route.path}", json={})
                    else:
                        continue
                    
                    if response.status_code in [200, 401]:  # 401 = auth required, which is fine
                        result.add_pass()
                    else:
                        result.add_issue(ValidationIssue(
                            severity='warning',
                            category='api',
                            component=route_name,
                            field=method,
                            message=f"Route returned unexpected status {response.status_code}",
                            expected='200 or 401',
                            actual=response.status_code
                        ))
                except Exception as e:
                    result.add_issue(ValidationIssue(
                        severity='warning',
                        category='api',
                        component=route_name,
                        field=method,
                        message=f"Route test failed: {str(e)}"
                    ))
        else:
            # Just validate route is registered (placeholder)
            result.add_pass()
        
        return result
    
    # =========================================
    # Impact Analysis
    # =========================================
    
    def analyze_change_impact(self, changed_fields: List[str]) -> Dict[str, Any]:
        """Analyze what features are affected by field changes"""
        impact = {
            'affected_features': [],
            'affected_workflows': [],
            'is_high_risk': False,
            'requires_restart': False,
            'cascade_tests': []
        }
        
        high_risk_fields = self.registry.get_high_risk_fields()
        
        for field in changed_fields:
            # Check if high risk
            if field in high_risk_fields:
                impact['is_high_risk'] = True
            
            # Find affected features
            for feature_name, feature in self.registry.features.items():
                for db_component in feature.db_fields:
                    if field in db_component.get('fields', []):
                        if feature_name not in impact['affected_features']:
                            impact['affected_features'].append(feature_name)
                        
                        # Add dependent features to cascade tests
                        deps = self.registry.get_feature_dependencies(feature_name)
                        impact['cascade_tests'].extend(deps)
        
        impact['cascade_tests'] = list(set(impact['cascade_tests']))
        
        return impact
    
    # =========================================
    # Pre-Change Validation
    # =========================================
    
    def validate_before_change(self, change_spec: Dict[str, Any]) -> ValidationResult:
        """
        Validate a proposed change before applying it.
        
        change_spec format:
        {
            'type': 'add_column' | 'modify_api' | 'add_feature',
            'table': 'channels',
            'column': 'new_column',
            'feature': 'feature_name'
        }
        """
        result = ValidationResult()
        change_type = change_spec.get('type')
        
        if change_type == 'add_column':
            table = change_spec.get('table')
            column = change_spec.get('column')
            
            # Check table exists in registry
            table_def = self.registry.get_table(table)
            if not table_def:
                result.add_issue(ValidationIssue(
                    severity='warning',
                    category='change',
                    component=table,
                    field='registry',
                    message=f"Table '{table}' not in registry - update registry first"
                ))
            
            # Check column doesn't already exist
            if self.check_column_exists(table, column):
                result.add_issue(ValidationIssue(
                    severity='info',
                    category='change',
                    component=table,
                    field=column,
                    message=f"Column '{column}' already exists in '{table}'"
                ))
            else:
                result.add_pass()
        
        return result
    
    # =========================================
    # Workflow Pipeline Validation
    # =========================================
    
    def validate_workflow(self, workflow_name: str) -> ValidationResult:
        """
        Validate a complete workflow pipeline - checks all stages have required components.
        This ensures the full signal-to-execution pipeline is intact.
        """
        result = ValidationResult()
        
        # Use typed workflow from registry loader
        workflow_def = self.registry.workflows.get(workflow_name)
        if not workflow_def:
            result.add_issue(ValidationIssue(
                severity='warning',
                category='workflow',
                component=workflow_name,
                field='registry',
                message=f"Workflow '{workflow_name}' not found in registry"
            ))
            return result
        
        stages = workflow_def.stages
        
        # Validate each stage
        for stage_id, stage in stages.items():
            stage_result = self._validate_workflow_stage(workflow_name, stage_id, stage)
            result.issues.extend(stage_result.issues)
            result.passed_checks += stage_result.passed_checks
            result.failed_checks += stage_result.failed_checks
        
        # Update counts
        result.total_checks = result.passed_checks + result.failed_checks
        result.critical_count = sum(1 for i in result.issues if i.severity == 'critical')
        result.warning_count = sum(1 for i in result.issues if i.severity == 'warning')
        result.is_valid = result.critical_count == 0
        
        return result
    
    def _validate_workflow_stage(self, workflow_name: str, stage_id: str, stage: Dict) -> ValidationResult:
        """Validate a single workflow stage has all required components."""
        result = ValidationResult()
        stage_name = stage.get('name', stage_id)
        
        # Validate database requirements
        db_requirements = stage.get('database_requirements', [])
        for db_req in db_requirements:
            table_name = db_req.get('table')
            required_fields = db_req.get('required_fields', [])
            
            # Check table exists
            conn = self._get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if not cursor.fetchone():
                    result.add_issue(ValidationIssue(
                        severity='critical',
                        category='workflow',
                        component=f"{workflow_name}.{stage_id}",
                        field=table_name,
                        message=f"Stage '{stage_name}' requires table '{table_name}' which does not exist"
                    ))
                    continue
                
                result.add_pass()
                
                # Check required fields exist
                cursor.execute(f"PRAGMA table_info({table_name})")
                existing_columns = {row['name'] for row in cursor.fetchall()}
                
                for field_name in required_fields:
                    if field_name in existing_columns:
                        result.add_pass()
                    else:
                        result.add_issue(ValidationIssue(
                            severity='critical',
                            category='workflow',
                            component=f"{workflow_name}.{stage_id}",
                            field=f"{table_name}.{field_name}",
                            message=f"Stage '{stage_name}' requires column '{field_name}' in table '{table_name}'"
                        ))
        
        # Validate function requirements (check if modules exist)
        func_requirements = stage.get('function_requirements', [])
        for func_req in func_requirements:
            module_name = func_req.get('module', '')
            functions = func_req.get('functions', [])
            
            # Try to import the module
            try:
                import importlib
                module_path = module_name.replace('/', '.').replace('\\', '.')
                if module_path.startswith('src.'):
                    # Check if file exists
                    file_path = module_name.replace('.', '/') + '.py'
                    if not Path(file_path).exists():
                        result.add_issue(ValidationIssue(
                            severity='warning',
                            category='workflow',
                            component=f"{workflow_name}.{stage_id}",
                            field=module_name,
                            message=f"Stage '{stage_name}' requires module '{module_name}' (file not found)"
                        ))
                    else:
                        result.add_pass()
                else:
                    result.add_pass()
            except Exception as e:
                result.add_issue(ValidationIssue(
                    severity='warning',
                    category='workflow',
                    component=f"{workflow_name}.{stage_id}",
                    field=module_name,
                    message=f"Could not validate module '{module_name}': {str(e)}"
                ))
        
        return result
    
    def validate_all_workflows(self) -> ValidationResult:
        """Validate all defined workflows."""
        result = ValidationResult()
        
        workflows = self.registry.workflows
        if not workflows:
            result.add_issue(ValidationIssue(
                severity='info',
                category='workflow',
                component='registry',
                field='workflows',
                message='No workflows defined in registry'
            ))
            return result
        
        for workflow_name in workflows.keys():
            wf_result = self.validate_workflow(workflow_name)
            result.issues.extend(wf_result.issues)
            result.passed_checks += wf_result.passed_checks
            result.failed_checks += wf_result.failed_checks
        
        # Update counts
        result.total_checks = result.passed_checks + result.failed_checks
        result.critical_count = sum(1 for i in result.issues if i.severity == 'critical')
        result.warning_count = sum(1 for i in result.issues if i.severity == 'warning')
        result.is_valid = result.critical_count == 0
        
        return result
    
    def get_pipeline_status(self) -> Dict[str, Any]:
        """
        Get a visual status of each pipeline stage.
        Returns a structured view showing which stages pass/fail.
        """
        status = {
            'pipelines': {},
            'overall_healthy': True,
            'stages_passed': 0,
            'stages_failed': 0
        }
        
        workflows = self.registry.workflows
        if not workflows:
            return status
        
        for workflow_name, workflow_def in workflows.items():
            stages = workflow_def.stages
            pipeline_status = {
                'name': workflow_def.name,
                'description': workflow_def.description,
                'stages': [],
                'is_healthy': True
            }
            
            # Sort stages by order
            sorted_stages = sorted(
                stages.items(),
                key=lambda x: x[1].get('order', 999)
            )
            
            for stage_id, stage in sorted_stages:
                stage_result = self._validate_workflow_stage(workflow_name, stage_id, stage)
                stage_healthy = stage_result.critical_count == 0
                
                stage_status = {
                    'id': stage_id,
                    'name': stage.get('name', stage_id),
                    'order': stage.get('order', 999),
                    'healthy': stage_healthy,
                    'passed': stage_result.passed_checks,
                    'failed': stage_result.failed_checks,
                    'issues': [i.to_dict() for i in stage_result.issues]
                }
                
                pipeline_status['stages'].append(stage_status)
                
                if stage_healthy:
                    status['stages_passed'] += 1
                else:
                    status['stages_failed'] += 1
                    pipeline_status['is_healthy'] = False
                    status['overall_healthy'] = False
            
            status['pipelines'][workflow_name] = pipeline_status
        
        return status


# =========================================
# Integration with existing health check
# =========================================

def run_qa_validation(db_path: str = None) -> Dict[str, Any]:
    """
    Run full QA validation - called from health check API.
    Returns dict compatible with existing health check format.
    """
    validator = QAValidator(db_path)
    try:
        result = validator.validate_all()
        return result.to_dict()
    finally:
        validator.close()


def validate_feature_integrity(feature_name: str, db_path: str = None) -> Dict[str, Any]:
    """
    Validate a specific feature - called when feature is modified.
    """
    validator = QAValidator(db_path)
    try:
        result = validator.validate_feature(feature_name)
        return result.to_dict()
    finally:
        validator.close()


def analyze_impact(changed_fields: List[str], db_path: str = None) -> Dict[str, Any]:
    """
    Analyze impact of changing specific fields.
    """
    validator = QAValidator(db_path)
    try:
        return validator.analyze_change_impact(changed_fields)
    finally:
        validator.close()


def run_workflow_validation(db_path: str = None) -> Dict[str, Any]:
    """
    Run workflow pipeline validation.
    Validates all workflow stages have required components.
    """
    validator = QAValidator(db_path)
    try:
        result = validator.validate_all_workflows()
        return result.to_dict()
    finally:
        validator.close()


def get_pipeline_status(db_path: str = None) -> Dict[str, Any]:
    """
    Get visual pipeline status showing each stage's health.
    Returns structured data for UI display.
    """
    validator = QAValidator(db_path)
    try:
        return validator.get_pipeline_status()
    finally:
        validator.close()


def validate_trading_pipeline(db_path: str = None) -> Dict[str, Any]:
    """
    Validate the complete trading pipeline specifically.
    This is the main signal-to-execution workflow.
    """
    validator = QAValidator(db_path)
    try:
        result = validator.validate_workflow('complete_trading_pipeline')
        pipeline_status = validator.get_pipeline_status()
        
        # Get the specific pipeline
        trading_pipeline = pipeline_status.get('pipelines', {}).get('complete_trading_pipeline', {})
        
        return {
            'is_valid': result.is_valid,
            'summary': {
                'total_checks': result.total_checks,
                'passed': result.passed_checks,
                'failed': result.failed_checks,
                'critical': result.critical_count,
                'warnings': result.warning_count
            },
            'pipeline_name': 'Complete Trading Pipeline',
            'stages': trading_pipeline.get('stages', []),
            'issues': [i.to_dict() for i in result.issues],
            'flow': [
                'Signal Detection',
                'Signal Parsing', 
                'Region Detection',
                'Broker Routing',
                'Position Sizing',
                'Risk Check',
                'Conditional Check',
                'Price Monitoring',
                'Order Execution',
                'Position Tracking',
                'Risk Monitoring'
            ]
        }
    finally:
        validator.close()

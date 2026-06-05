"""
Registry Loader Module
======================
Loads and parses YAML registry files for validation.
"""

import os
import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_DIR = Path(__file__).parent / 'registry'


@dataclass
class FeatureDefinition:
    """Represents a feature from the registry"""
    name: str
    version: str
    description: str
    status: str
    added_date: str
    components: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    
    @property
    def db_fields(self) -> List[Dict[str, Any]]:
        """Get all database fields for this feature"""
        return self.components.get('database', [])
    
    @property
    def api_routes(self) -> List[Dict[str, Any]]:
        """Get all API routes for this feature"""
        return self.components.get('api_routes', [])
    
    @property
    def selfbot_functions(self) -> List[str]:
        """Get all selfbot functions for this feature"""
        return self.components.get('selfbot_functions', [])
    
    @property
    def js_files(self) -> List[str]:
        """Get all JavaScript files for this feature"""
        return self.components.get('js_files', [])


@dataclass
class TableDefinition:
    """Represents a database table from the schema registry"""
    name: str
    description: str
    primary_key: str
    columns: Dict[str, Dict[str, Any]]
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_column(self, column_name: str) -> Optional[Dict[str, Any]]:
        """Get column definition by name"""
        return self.columns.get(column_name)
    
    def has_column(self, column_name: str) -> bool:
        """Check if column exists"""
        return column_name in self.columns


@dataclass
class APIRouteDefinition:
    """Represents an API route from the registry"""
    path: str
    methods: Dict[str, Dict[str, Any]]
    
    def get_method(self, method: str) -> Optional[Dict[str, Any]]:
        """Get method definition"""
        return self.methods.get(method.upper())
    
    @property
    def critical_fields(self) -> List[str]:
        """Get critical fields that require validation"""
        fields = []
        for method_def in self.methods.values():
            fields.extend(method_def.get('critical_fields', []))
        return fields


@dataclass  
class WorkflowDefinition:
    """Represents a workflow from the registry"""
    name: str
    description: str
    priority: str
    stages: Dict[str, Dict[str, Any]]
    test_scenarios: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def steps(self) -> Dict[str, Dict[str, Any]]:
        """Alias for backwards compatibility"""
        return self.stages


class RegistryLoader:
    """Loads and provides access to all registry files"""
    
    def __init__(self, registry_dir: Path = None):
        self.registry_dir = registry_dir or REGISTRY_DIR
        self._features: Dict[str, FeatureDefinition] = {}
        self._tables: Dict[str, TableDefinition] = {}
        self._routes: Dict[str, APIRouteDefinition] = {}
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._dependencies: Dict[str, Any] = {}
        self._loaded = False
    
    def load_all(self) -> bool:
        """Load all registry files"""
        try:
            self._load_features()
            self._load_database_schema()
            self._load_api_routes()
            self._load_workflows()
            self._load_dependencies()
            self._loaded = True
            return True
        except Exception as e:
            print(f"[QA] Error loading registry: {e}")
            return False
    
    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        """Load a YAML file from registry"""
        filepath = self.registry_dir / filename
        if not filepath.exists():
            return {}
        with open(filepath, 'r') as f:
            return yaml.safe_load(f) or {}
    
    def _load_features(self):
        """Load features.yaml"""
        data = self._load_yaml('features.yaml')
        features = data.get('features', {})
        
        for name, feature_data in features.items():
            self._features[name] = FeatureDefinition(
                name=name,
                version=feature_data.get('version', '1.0'),
                description=feature_data.get('description', ''),
                status=feature_data.get('status', 'active'),
                added_date=feature_data.get('added_date', ''),
                components=feature_data.get('components', {}),
                dependencies=feature_data.get('dependencies', [])
            )
    
    def _load_database_schema(self):
        """Load database_schema.yaml"""
        data = self._load_yaml('database_schema.yaml')
        tables = data.get('tables', {})
        
        for name, table_data in tables.items():
            self._tables[name] = TableDefinition(
                name=name,
                description=table_data.get('description', ''),
                primary_key=table_data.get('primary_key', 'id'),
                columns=table_data.get('columns', {}),
                indexes=table_data.get('indexes', [])
            )
    
    def _load_api_routes(self):
        """Load api_routes.yaml"""
        data = self._load_yaml('api_routes.yaml')
        routes = data.get('routes', {})
        
        for name, route_data in routes.items():
            self._routes[name] = APIRouteDefinition(
                path=route_data.get('path', ''),
                methods=route_data.get('methods', {})
            )
    
    def _load_workflows(self):
        """Load workflows.yaml"""
        data = self._load_yaml('workflows.yaml')
        workflows = data.get('workflows', {})
        
        for name, workflow_data in workflows.items():
            stages = workflow_data.get('stages', workflow_data.get('steps', {}))
            self._workflows[name] = WorkflowDefinition(
                name=workflow_data.get('name', name),
                description=workflow_data.get('description', ''),
                priority=workflow_data.get('priority', 'normal'),
                stages=stages,
                test_scenarios=workflow_data.get('test_scenarios', [])
            )
    
    def _load_dependencies(self):
        """Load dependencies.yaml"""
        self._dependencies = self._load_yaml('dependencies.yaml')
    
    # =========================================
    # Public Access Methods
    # =========================================
    
    @property
    def features(self) -> Dict[str, FeatureDefinition]:
        if not self._loaded:
            self.load_all()
        return self._features
    
    @property
    def tables(self) -> Dict[str, TableDefinition]:
        if not self._loaded:
            self.load_all()
        return self._tables
    
    @property
    def routes(self) -> Dict[str, APIRouteDefinition]:
        if not self._loaded:
            self.load_all()
        return self._routes
    
    @property
    def workflows(self) -> Dict[str, WorkflowDefinition]:
        if not self._loaded:
            self.load_all()
        return self._workflows
    
    def get_feature(self, name: str) -> Optional[FeatureDefinition]:
        """Get a feature by name"""
        return self.features.get(name)
    
    def get_table(self, name: str) -> Optional[TableDefinition]:
        """Get a table definition by name"""
        return self.tables.get(name)
    
    def get_route(self, name: str) -> Optional[APIRouteDefinition]:
        """Get an API route by name"""
        return self.routes.get(name)
    
    def get_feature_dependencies(self, feature_name: str) -> List[str]:
        """Get features that depend on this feature"""
        deps = self._dependencies.get('dependencies', {})
        feature_deps = deps.get(feature_name, {})
        return feature_deps.get('required_by', [])
    
    def get_high_risk_fields(self) -> List[str]:
        """Get list of high-risk database fields"""
        impact_rules = self._dependencies.get('impact_rules', {})
        return impact_rules.get('high_risk_changes', [])
    
    def get_all_feature_names(self) -> List[str]:
        """Get list of all feature names"""
        return list(self.features.keys())
    
    def get_all_table_names(self) -> List[str]:
        """Get list of all table names"""
        return list(self.tables.keys())
    
    def get_critical_workflows(self) -> List[WorkflowDefinition]:
        """Get workflows marked as critical priority"""
        return [w for w in self.workflows.values() if w.priority == 'critical']
    
    def get_workflows(self) -> Dict[str, Any]:
        """
        Get raw workflow data including new stage-based pipelines.
        Returns the raw YAML data for workflow validation.
        """
        if not self._loaded:
            self.load_all()
        return self._load_yaml('workflows.yaml').get('workflows', {})


# Singleton instance
_registry = None

def get_registry() -> RegistryLoader:
    """Get the singleton registry instance"""
    global _registry
    if _registry is None:
        _registry = RegistryLoader()
        _registry.load_all()
    return _registry

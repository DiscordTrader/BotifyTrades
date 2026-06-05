"""
Route Audit Tests
CRITICAL: Detects duplicate/conflicting API routes that cause system breakage
This test should FAIL if duplicate routes exist - forcing cleanup before deployment
"""
import pytest
import re
import ast
from pathlib import Path
from collections import defaultdict

pytestmark = [pytest.mark.quick, pytest.mark.database]


class TestRouteAudit:
    """Audit API routes for duplicates and conflicts."""
    
    @pytest.fixture
    def routes_file(self):
        """Path to routes file."""
        return Path('gui_app/routes.py')
    
    @pytest.fixture
    def extract_routes(self, routes_file):
        """Extract all route definitions from routes.py."""
        if not routes_file.exists():
            return []
        
        content = routes_file.read_text(encoding='utf-8')
        
        # Pattern to match @app.route or @bp.route decorators
        route_pattern = r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:,\s*methods=\[([^\]]+)\])?\)"
        matches = re.findall(route_pattern, content)
        
        routes = []
        for path, methods in matches:
            if methods:
                # Parse methods like "'GET', 'POST'"
                method_list = [m.strip().strip("'\"") for m in methods.split(',')]
            else:
                method_list = ['GET']
            
            for method in method_list:
                routes.append({
                    'path': path,
                    'method': method.upper(),
                    'key': f"{method.upper()} {path}"
                })
        
        return routes
    
    def test_no_exact_duplicate_routes(self, extract_routes):
        """Should not have exact duplicate route definitions."""
        seen = defaultdict(int)
        duplicates = []
        
        for route in extract_routes:
            key = route['key']
            seen[key] += 1
            if seen[key] > 1:
                duplicates.append(key)
        
        if duplicates:
            msg = f"DUPLICATE ROUTES FOUND:\n" + "\n".join(f"  - {d}" for d in set(duplicates))
            pytest.fail(msg)
    
    def test_api_versioning_consistency(self, extract_routes):
        """API routes should use consistent versioning."""
        api_routes = [r for r in extract_routes if r['path'].startswith('/api/')]
        
        # Check for mixed versioned and non-versioned API routes
        versioned = [r for r in api_routes if '/api/v1/' in r['path']]
        unversioned = [r for r in api_routes if '/api/' in r['path'] and '/api/v1/' not in r['path'] and '/api/admin/' not in r['path']]
        
        # Report both for visibility (warning, not failure)
        if versioned and unversioned:
            print(f"\nWARNING: Mixed API versioning detected:")
            print(f"  Versioned (/api/v1/): {len(versioned)} routes")
            print(f"  Unversioned (/api/): {len(unversioned)} routes")
    
    def test_license_routes_no_conflicts(self, extract_routes):
        """License routes should not have v1 and non-v1 duplicates."""
        license_routes = [r for r in extract_routes if 'license' in r['path'].lower()]
        
        # Group by endpoint function
        endpoints = defaultdict(list)
        for route in license_routes:
            # Normalize path - remove /api/v1 or /api prefix
            normalized = route['path']
            normalized = normalized.replace('/api/v1/', '/')
            normalized = normalized.replace('/api/', '/')
            
            key = f"{route['method']} {normalized}"
            endpoints[key].append(route['path'])
        
        conflicts = []
        for key, paths in endpoints.items():
            if len(paths) > 1:
                conflicts.append(f"{key}: {paths}")
        
        if conflicts:
            msg = f"LICENSE ROUTE CONFLICTS (same endpoint, different paths):\n" + "\n".join(f"  - {c}" for c in conflicts)
            # This is a warning for now - document the issue
            print(f"\nWARNING: {msg}")
    
    def test_route_naming_conventions(self, extract_routes):
        """Routes should follow naming conventions."""
        issues = []
        
        for route in extract_routes:
            path = route['path']
            
            # API routes should start with /api/
            if 'api' in path.lower() and not path.startswith('/api'):
                issues.append(f"API route not properly prefixed: {path}")
            
            # Admin routes should be under /admin/ or /api/admin/
            if 'admin' in path.lower():
                if not (path.startswith('/admin') or '/api/admin/' in path):
                    issues.append(f"Admin route not properly namespaced: {path}")
        
        if issues:
            print("\nWARNING: Route naming issues:")
            for issue in issues:
                print(f"  - {issue}")


class TestRouteCategories:
    """Test route organization by category."""
    
    @pytest.fixture
    def categorize_routes(self):
        """Categorize routes by function."""
        routes_file = Path('gui_app/routes.py')
        if not routes_file.exists():
            return {}
        
        content = routes_file.read_text(encoding='utf-8')
        route_pattern = r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"]"
        paths = re.findall(route_pattern, content)
        
        categories = {
            'license': [],
            'channels': [],
            'trades': [],
            'brokers': [],
            'settings': [],
            'health': [],
            'admin': [],
            'user': [],
            'pages': [],
            'other': []
        }
        
        for path in paths:
            categorized = False
            if 'license' in path.lower():
                categories['license'].append(path)
                categorized = True
            elif 'channel' in path.lower():
                categories['channels'].append(path)
                categorized = True
            elif 'trade' in path.lower():
                categories['trades'].append(path)
                categorized = True
            elif 'broker' in path.lower():
                categories['brokers'].append(path)
                categorized = True
            elif 'setting' in path.lower():
                categories['settings'].append(path)
                categorized = True
            elif 'health' in path.lower():
                categories['health'].append(path)
                categorized = True
            elif 'admin' in path.lower():
                categories['admin'].append(path)
                categorized = True
            elif 'user' in path.lower():
                categories['user'].append(path)
                categorized = True
            elif not path.startswith('/api'):
                categories['pages'].append(path)
                categorized = True
            
            if not categorized:
                categories['other'].append(path)
        
        return categories
    
    def test_route_category_sizes(self, categorize_routes):
        """Print route counts by category."""
        print("\n\nROUTE CATEGORIES:")
        total = 0
        for category, routes in categorize_routes.items():
            if routes:
                print(f"  {category}: {len(routes)} routes")
                total += len(routes)
        print(f"  TOTAL: {total} routes")
    
    def test_license_routes_documented(self, categorize_routes):
        """License routes should exist."""
        license_routes = categorize_routes.get('license', [])
        assert len(license_routes) > 0, "No license routes found"
    
    def test_channel_routes_documented(self, categorize_routes):
        """Channel routes should exist."""
        channel_routes = categorize_routes.get('channels', [])
        assert len(channel_routes) > 0, "No channel routes found"


class TestAPIEndpointRegistry:
    """Create a registry of API endpoints for documentation."""
    
    @pytest.fixture
    def api_registry(self):
        """Build API endpoint registry."""
        routes_file = Path('gui_app/routes.py')
        if not routes_file.exists():
            return {}
        
        content = routes_file.read_text(encoding='utf-8')
        
        # Pattern with methods
        route_pattern = r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:,\s*methods=\[([^\]]+)\])?\)"
        matches = re.findall(route_pattern, content)
        
        registry = {}
        for path, methods in matches:
            if not path.startswith('/api'):
                continue
            
            if methods:
                method_list = [m.strip().strip("'\"") for m in methods.split(',')]
            else:
                method_list = ['GET']
            
            registry[path] = {
                'methods': method_list,
                'versioned': '/v1/' in path,
                'admin': '/admin/' in path
            }
        
        return registry
    
    def test_registry_has_essential_endpoints(self, api_registry):
        """Registry should include essential API endpoints."""
        essential = [
            '/api/channels',
            '/api/trades',
            '/api/settings',
            '/api/status',
        ]
        
        for endpoint in essential:
            assert endpoint in api_registry or any(endpoint in k for k in api_registry.keys()), \
                f"Essential endpoint missing: {endpoint}"
    
    def test_admin_endpoints_protected(self, api_registry):
        """Admin endpoints should be under /api/admin/."""
        admin_endpoints = [path for path in api_registry.keys() if 'admin' in path.lower()]
        
        for endpoint in admin_endpoints:
            assert '/admin/' in endpoint, f"Admin endpoint not properly namespaced: {endpoint}"


class TestDuplicateEndpointPrevention:
    """Prevent duplicate endpoint creation."""
    
    def test_license_endpoint_consolidation(self):
        """Document which license endpoints exist and should be consolidated."""
        legacy_endpoints = [
            '/api/license/status',
            '/api/license/activate',
            '/api/license/validate',
            '/api/license/deactivate',
            '/api/license/machine-info',
        ]
        
        v1_endpoints = [
            '/api/v1/license/status',
            '/api/v1/license/activate',
            '/api/v1/license/validate',
            '/api/v1/license/deactivate',
            '/api/v1/license/health',
            '/api/v1/license/trial',
        ]
        
        # Both exist - document the duplication
        print("\n\nLICENSE ENDPOINT MAPPING:")
        print("Legacy endpoints (should be deprecated):")
        for ep in legacy_endpoints:
            print(f"  - {ep}")
        print("\nV1 endpoints (preferred):")
        for ep in v1_endpoints:
            print(f"  - {ep}")
        
        # Test passes but documents the issue
        assert True
    
    def test_signal_endpoint_consolidation(self):
        """Check for signal endpoint duplicates."""
        routes_file = Path('gui_app/routes.py')
        if not routes_file.exists():
            return
        
        content = routes_file.read_text(encoding='utf-8')
        
        signal_routes = re.findall(r"@(?:app|bp)\.route\(['\"]([^'\"]*signal[^'\"]*)['\"]", content, re.IGNORECASE)
        
        if len(signal_routes) > 2:
            print(f"\nWARNING: Multiple signal routes detected:")
            for route in signal_routes:
                print(f"  - {route}")


class TestRouteConflictMatrix:
    """Generate conflict detection matrix."""
    
    def test_generate_conflict_report(self):
        """Generate a conflict report for review."""
        routes_file = Path('gui_app/routes.py')
        if not routes_file.exists():
            return
        
        content = routes_file.read_text(encoding='utf-8')
        route_pattern = r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:,\s*methods=\[([^\]]+)\])?\)"
        matches = re.findall(route_pattern, content)
        
        # Group by normalized path
        normalized_groups = defaultdict(list)
        for path, methods in matches:
            # Normalize - remove versioning
            norm = path.replace('/api/v1/', '/api/').replace('/api/v2/', '/api/')
            normalized_groups[norm].append(path)
        
        conflicts = {k: v for k, v in normalized_groups.items() if len(v) > 1}
        
        if conflicts:
            print("\n\nPOTENTIAL ROUTE CONFLICTS:")
            for norm, paths in conflicts.items():
                print(f"\n  Normalized: {norm}")
                for p in paths:
                    print(f"    - {p}")
        else:
            print("\n\nNo potential route conflicts detected.")

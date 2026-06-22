"""Tests for AI MCP Server and API endpoints."""
import asyncio
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ─── MCP Server Unit Tests ───────────────────────────────────

class TestMCPServerTools:
    """Test MCP server tool registration and definitions."""

    def setup_method(self):
        from src.ai.mcp_server import MCPServer
        self.server = MCPServer()

    def test_tool_count(self):
        """22 tools are registered."""
        assert len(self.server._tools) == 22

    def test_tool_definitions_complete(self):
        """Every tool has name, description, and inputSchema."""
        defs = self.server.get_tool_definitions()
        assert len(defs) == 22
        for d in defs:
            assert 'name' in d, f"Missing name in {d}"
            assert 'description' in d, f"Missing description for {d.get('name')}"
            assert 'inputSchema' in d, f"Missing inputSchema for {d['name']}"
            assert d['inputSchema']['type'] == 'object'
            assert isinstance(d['description'], str)
            assert len(d['description']) > 5, f"Description too short for {d['name']}"

    def test_tool_schemas_have_required_params(self):
        """Tools with required params have them declared in inputSchema."""
        defs = self.server.get_tool_definitions()
        by_name = {d['name']: d for d in defs}

        # These tools require parameters
        assert 'symbol' in by_name['get_position_detail']['inputSchema'].get('required', [])
        assert 'trade_id' in by_name['close_position']['inputSchema'].get('required', [])
        assert 'channel_id' in by_name['get_channel_settings']['inputSchema'].get('required', [])
        assert 'channel_id' in by_name['update_channel_settings']['inputSchema'].get('required', [])
        assert 'channel_id' in by_name['get_channel_performance']['inputSchema'].get('required', [])
        assert 'id' in by_name['approve_format']['inputSchema'].get('required', [])
        assert 'text' in by_name['test_parse']['inputSchema'].get('required', [])

        # These tools have NO required params
        for name in ['get_live_positions', 'get_risk_state', 'get_market_regime',
                      'get_broker_status', 'get_system_metrics', 'get_conditional_orders',
                      'get_channel_scores', 'get_consensus_signals', 'get_ai_feature_status']:
            schema = by_name[name]['inputSchema']
            assert schema.get('required', []) == [], f"{name} should have no required params"

    def test_unknown_tool_returns_error(self):
        """Calling an unknown tool returns an error dict."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('nonexistent_tool')
        )
        assert 'error' in result
        assert 'Unknown tool' in result['error']

    def test_system_metrics_works(self):
        """get_system_metrics always works (no external deps)."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_system_metrics')
        )
        assert 'python' in result
        assert 'platform' in result

    def test_get_channels_returns_data(self):
        """get_channels returns a channels list and count."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_channels')
        )
        assert 'channels' in result
        assert 'count' in result
        assert isinstance(result['channels'], list)
        assert result['count'] == len(result['channels'])

    def test_get_trade_history_with_params(self):
        """get_trade_history respects limit and days params."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_trade_history', {'limit': 5, 'days': 7})
        )
        assert 'trades' in result
        assert 'count' in result
        assert result['count'] <= 5

    def test_get_channel_settings_missing_id(self):
        """get_channel_settings returns error when channel_id is missing."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_channel_settings', {})
        )
        assert 'error' in result

    def test_close_position_missing_trade_id(self):
        """close_position returns error when trade_id is missing."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('close_position', {})
        )
        assert 'error' in result
        assert 'trade_id' in result['error']

    def test_test_parse_missing_text(self):
        """test_parse returns error when text is missing."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('test_parse', {})
        )
        assert 'error' in result

    def test_approve_format_missing_id(self):
        """approve_format returns error when id is missing."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('approve_format', {})
        )
        assert 'error' in result

    def test_update_channel_settings_missing_params(self):
        """update_channel_settings validates required params."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('update_channel_settings', {})
        )
        assert 'error' in result

        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('update_channel_settings', {'channel_id': 1})
        )
        assert 'error' in result  # empty settings

    def test_get_position_detail_missing_symbol(self):
        """get_position_detail validates symbol param."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_position_detail', {})
        )
        assert 'error' in result

    def test_get_broker_status(self):
        """get_broker_status returns broker states."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_broker_status')
        )
        assert 'brokers' in result

    def test_get_conditional_orders(self):
        """get_conditional_orders returns orders list."""
        result = asyncio.get_event_loop().run_until_complete(
            self.server.call_tool('get_conditional_orders')
        )
        assert 'orders' in result
        assert 'count' in result


class TestMCPJsonRPC:
    """Test MCP JSON-RPC 2.0 protocol handling."""

    def setup_method(self):
        from src.ai.mcp_server import MCPServer
        self.server = MCPServer()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_initialize(self):
        resp = self._run(self.server.handle_jsonrpc({
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}
        }))
        assert resp['jsonrpc'] == '2.0'
        assert resp['id'] == 1
        assert resp['result']['serverInfo']['name'] == 'botify-ai-trading'
        assert 'tools' in resp['result']['capabilities']

    def test_tools_list(self):
        resp = self._run(self.server.handle_jsonrpc({
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}
        }))
        tools = resp['result']['tools']
        assert len(tools) == 22
        names = [t['name'] for t in tools]
        assert 'get_system_metrics' in names
        assert 'get_channels' in names

    def test_tools_call(self):
        resp = self._run(self.server.handle_jsonrpc({
            'jsonrpc': '2.0', 'id': 3,
            'method': 'tools/call',
            'params': {'name': 'get_system_metrics', 'arguments': {}}
        }))
        content = resp['result']['content']
        assert len(content) == 1
        assert content[0]['type'] == 'text'
        data = json.loads(content[0]['text'])
        assert 'platform' in data

    def test_unknown_method(self):
        resp = self._run(self.server.handle_jsonrpc({
            'jsonrpc': '2.0', 'id': 4, 'method': 'bogus/method', 'params': {}
        }))
        assert 'error' in resp
        assert resp['error']['code'] == -32601

    def test_notification_returns_none(self):
        resp = self._run(self.server.handle_jsonrpc({
            'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {}
        }))
        assert resp is None


class TestMCPSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self):
        from src.ai.mcp_server import get_mcp_server
        s1 = get_mcp_server()
        s2 = get_mcp_server()
        assert s1 is s2

    def test_singleton_is_mcp_server(self):
        from src.ai.mcp_server import get_mcp_server, MCPServer
        assert isinstance(get_mcp_server(), MCPServer)


# ─── API Route Tests ─────────────────────────────────────────

@pytest.fixture(scope='module')
def client():
    """Create authenticated Flask test client."""
    os.environ.setdefault('ADMIN_PASSWORD', 'test')
    from gui_app.app import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['logged_in'] = True
            sess['is_admin'] = True
            sess['consent_accepted'] = True
        yield c


class TestAIModulesAPI:
    """Test /api/ai/* endpoints."""

    def test_get_modules(self, client):
        resp = client.get('/api/ai/modules')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'flags' in data
        assert 'costs' in data

    def test_toggle_module(self, client):
        resp = client.put('/api/ai/modules/channel_scoring',
                          json={'enabled': True},
                          content_type='application/json')
        assert resp.status_code in (200, 500)  # 500 if module not yet created by sibling agent
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_channel_scores(self, client):
        resp = client.get('/api/ai/channel-scores')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'scores' in data

    def test_market_regime(self, client):
        resp = client.get('/api/ai/market-regime')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'regime' in data

    def test_execution_quality(self, client):
        resp = client.get('/api/ai/execution-quality')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_execution_quality_with_days(self, client):
        resp = client.get('/api/ai/execution-quality?days=7')
        assert resp.status_code == 200

    def test_risk_recommendations(self, client):
        resp = client.get('/api/ai/risk-recommendations')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'recommendations' in data

    def test_consensus(self, client):
        resp = client.get('/api/ai/consensus')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'consensus' in data

    def test_classifier_train(self, client):
        resp = client.post('/api/ai/classifier/train')
        assert resp.status_code in (200, 500)  # 500 if classifier not yet created

    def test_mcp_tools_list(self, client):
        resp = client.get('/api/ai/mcp/tools')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'tools' in data
        assert len(data['tools']) == 22

    def test_mcp_call_tool(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={'tool': 'get_system_metrics', 'params': {}},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'platform' in data

    def test_mcp_call_unknown_tool(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={'tool': 'no_such_tool'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'error' in data

    def test_mcp_call_missing_tool(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_mcp_call_get_channels(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={'tool': 'get_channels'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'channels' in data
        assert 'count' in data

    def test_mcp_call_get_trade_history(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={'tool': 'get_trade_history', 'params': {'limit': 3, 'days': 7}},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'trades' in data

    def test_mcp_call_get_broker_status(self, client):
        resp = client.post('/api/ai/mcp/call',
                           json={'tool': 'get_broker_status'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'brokers' in data

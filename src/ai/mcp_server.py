"""MCP Server for AI Trading Intelligence.

Provides 22 tools for Claude Desktop and Dashboard chat integration.
Transport: stdio (Claude Desktop) or HTTP (Dashboard chat fallback via /api/ai/mcp/call).

All tool implementations are fire-and-forget safe with full try/except wrapping.
Lazy imports keep the module lightweight — nothing is loaded until a tool is called.
"""
import json
import sys
import time
from typing import Any, Dict, List, Optional


# ─── Tool metadata for MCP protocol ──────────────────────────

_TOOL_SCHEMAS: Dict[str, dict] = {
    'get_live_positions': {
        'description': 'Get all currently open positions across all brokers with live P&L',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_position_detail': {
        'description': 'Get detailed info for a specific position by ticker symbol',
        'inputSchema': {
            'type': 'object',
            'properties': {'symbol': {'type': 'string', 'description': 'Ticker symbol (e.g. AAPL, SPY)'}},
            'required': ['symbol'],
        },
    },
    'close_position': {
        'description': 'Close an open position by trade ID. Delegates to the appropriate broker.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'trade_id': {'type': 'integer', 'description': 'Database trade ID to close'},
            },
            'required': ['trade_id'],
        },
    },
    'get_channels': {
        'description': 'List all configured signal channels with their settings',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_channel_settings': {
        'description': 'Get full settings for a specific channel by ID',
        'inputSchema': {
            'type': 'object',
            'properties': {'channel_id': {'type': 'integer', 'description': 'Channel database ID'}},
            'required': ['channel_id'],
        },
    },
    'update_channel_settings': {
        'description': 'Update one or more settings for a channel',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'channel_id': {'type': 'integer', 'description': 'Channel database ID'},
                'settings': {'type': 'object', 'description': 'Key-value pairs of settings to update'},
            },
            'required': ['channel_id', 'settings'],
        },
    },
    'get_channel_performance': {
        'description': 'Get trade performance stats for a channel over N days',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'channel_id': {'type': 'integer', 'description': 'Channel database ID'},
                'days': {'type': 'integer', 'description': 'Lookback window in days (default 30)', 'default': 30},
            },
            'required': ['channel_id'],
        },
    },
    'get_risk_state': {
        'description': 'Get current portfolio risk state — open position count, total unrealized P&L, best/worst positions',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_trade_history': {
        'description': 'Query closed trade history with optional filters',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer', 'description': 'Max trades to return (default 50)', 'default': 50},
                'symbol': {'type': 'string', 'description': 'Filter by ticker symbol'},
                'channel': {'type': 'string', 'description': 'Filter by channel ID'},
                'days': {'type': 'integer', 'description': 'Lookback window in days (default 30)', 'default': 30},
            },
        },
    },
    'get_market_regime': {
        'description': 'Get current market regime classification (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE)',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_ai_recommendations': {
        'description': 'Get pending AI risk-tuning recommendations for human review',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_format_candidates': {
        'description': 'Get pending AI-detected signal format candidates awaiting approval',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'approve_format': {
        'description': 'Approve a signal format candidate by ID',
        'inputSchema': {
            'type': 'object',
            'properties': {'id': {'type': 'integer', 'description': 'Format candidate ID'}},
            'required': ['id'],
        },
    },
    'test_parse': {
        'description': 'Test parsing a signal message through registry, local classifier, and AI parser',
        'inputSchema': {
            'type': 'object',
            'properties': {'text': {'type': 'string', 'description': 'Signal message text to parse'}},
            'required': ['text'],
        },
    },
    'get_broker_status': {
        'description': 'Get connection status for all configured brokers',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_system_metrics': {
        'description': 'Get system resource metrics — CPU, memory, uptime, Python version',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_conditional_orders': {
        'description': 'Get active conditional orders (PENDING or MONITORING status)',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_channel_scores': {
        'description': 'Get AI-computed reliability scores for all channels',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_consensus_signals': {
        'description': 'Get active multi-channel consensus signals',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_execution_quality': {
        'description': 'Get execution quality metrics per broker — slippage, fill rates, latency',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': 'Lookback window in days (default 30)', 'default': 30},
            },
        },
    },
    'get_ai_feature_status': {
        'description': 'Get enabled/disabled status of all AI intelligence modules',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    'get_cost_report': {
        'description': 'Get AI API usage and cost summary over N days',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': 'Lookback window in days (default 30)', 'default': 30},
            },
        },
    },
}


class MCPServer:
    """MCP JSON-RPC server exposing AI trading intelligence tools.

    Supports two transports:
    - stdio: for Claude Desktop integration (run as subprocess)
    - HTTP: via /api/ai/mcp/call endpoint for Dashboard chat
    """

    def __init__(self):
        self._tools: Dict[str, Any] = {}
        self._register_tools()

    def _register_tools(self):
        """Register all tool implementations by name."""
        self._tools['get_live_positions'] = self._get_live_positions
        self._tools['get_position_detail'] = self._get_position_detail
        self._tools['close_position'] = self._close_position
        self._tools['get_channels'] = self._get_channels
        self._tools['get_channel_settings'] = self._get_channel_settings
        self._tools['update_channel_settings'] = self._update_channel_settings
        self._tools['get_channel_performance'] = self._get_channel_performance
        self._tools['get_risk_state'] = self._get_risk_state
        self._tools['get_trade_history'] = self._get_trade_history
        self._tools['get_market_regime'] = self._get_market_regime
        self._tools['get_ai_recommendations'] = self._get_ai_recommendations
        self._tools['get_format_candidates'] = self._get_format_candidates
        self._tools['approve_format'] = self._approve_format
        self._tools['test_parse'] = self._test_parse
        self._tools['get_broker_status'] = self._get_broker_status
        self._tools['get_system_metrics'] = self._get_system_metrics
        self._tools['get_conditional_orders'] = self._get_conditional_orders
        self._tools['get_channel_scores'] = self._get_channel_scores
        self._tools['get_consensus_signals'] = self._get_consensus_signals
        self._tools['get_execution_quality'] = self._get_execution_quality
        self._tools['get_ai_feature_status'] = self._get_ai_feature_status
        self._tools['get_cost_report'] = self._get_cost_report

    # ─── Position Tools ───────────────────────────────────────

    async def _get_live_positions(self, params: dict = None) -> dict:
        """Get all currently open positions across all brokers."""
        try:
            from gui_app.live_snapshot import get_live_snapshot
            snapshot = get_live_snapshot()
            if not snapshot:
                return {'positions': [], 'count': 0}
            positions = snapshot.get('positions', [])
            return {'positions': positions, 'count': len(positions)}
        except Exception as e:
            return {'error': str(e), 'positions': [], 'count': 0}

    async def _get_position_detail(self, params: dict) -> dict:
        """Get detail for a single position by symbol."""
        symbol = (params.get('symbol') or '').upper()
        if not symbol:
            return {'error': 'symbol is required'}
        try:
            from gui_app.live_snapshot import get_live_snapshot
            snapshot = get_live_snapshot()
            for pos in (snapshot or {}).get('positions', []):
                if (pos.get('symbol') or '').upper() == symbol:
                    return pos
            return {'error': f'Position {symbol} not found'}
        except Exception as e:
            return {'error': str(e)}

    async def _close_position(self, params: dict) -> dict:
        """Close a position by trade ID. Delegates to the existing close-by-id route logic."""
        trade_id = params.get('trade_id')
        if not trade_id:
            return {'error': 'trade_id is required'}
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id, symbol, status, broker FROM trades WHERE id = ?', (trade_id,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return {'error': f'Trade {trade_id} not found'}
            if row[2] != 'OPEN':
                return {'error': f'Trade {trade_id} is not OPEN (status: {row[2]})'}
            return {
                'action': 'close_requested',
                'trade_id': trade_id,
                'symbol': row[1],
                'broker': row[3],
                'note': 'Use /api/trades/<id>/close endpoint to execute the close',
            }
        except Exception as e:
            return {'error': str(e)}

    # ─── Channel Tools ────────────────────────────────────────

    async def _get_channels(self, params: dict = None) -> dict:
        """List all configured signal channels."""
        try:
            from gui_app.database import get_channels
            channels = get_channels()
            return {'channels': channels, 'count': len(channels)}
        except Exception as e:
            return {'error': str(e)}

    async def _get_channel_settings(self, params: dict) -> dict:
        """Get full settings for a channel."""
        channel_id = params.get('channel_id')
        if channel_id is None:
            return {'error': 'channel_id is required'}
        try:
            from gui_app.database import get_channel_by_id
            ch = get_channel_by_id(channel_id)
            return ch if ch else {'error': f'Channel {channel_id} not found'}
        except Exception as e:
            return {'error': str(e)}

    async def _update_channel_settings(self, params: dict) -> dict:
        """Update channel settings."""
        channel_id = params.get('channel_id')
        settings = params.get('settings', {})
        if channel_id is None:
            return {'error': 'channel_id is required'}
        if not settings:
            return {'error': 'settings object is required'}
        try:
            from gui_app.database import update_channel
            update_channel(channel_id, **settings)
            return {'success': True, 'channel_id': channel_id, 'updated_fields': list(settings.keys())}
        except Exception as e:
            return {'error': str(e)}

    async def _get_channel_performance(self, params: dict) -> dict:
        """Get trade performance stats for a channel."""
        channel_id = params.get('channel_id')
        if channel_id is None:
            return {'error': 'channel_id is required'}
        days = params.get('days', 30)
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       AVG(pnl_percent) as avg_pnl_pct,
                       SUM(pnl) as total_pnl
                FROM trades
                WHERE channel_id = ? AND status = 'CLOSED'
                AND closed_at > datetime('now', ? || ' days')
            ''', (str(channel_id), f'-{days}'))
            row = cursor.fetchone()
            conn.close()
            total = row[0] or 0
            wins = row[1] or 0
            return {
                'channel_id': channel_id,
                'days': days,
                'total_trades': total,
                'wins': wins,
                'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
                'avg_pnl_pct': round(row[2] or 0, 2),
                'total_pnl': round(row[3] or 0, 2),
            }
        except Exception as e:
            return {'error': str(e)}

    # ─── Risk Tools ───────────────────────────────────────────

    async def _get_risk_state(self, params: dict = None) -> dict:
        """Get current portfolio risk summary."""
        try:
            from gui_app.live_snapshot import get_live_snapshot
            snapshot = get_live_snapshot()
            positions = (snapshot or {}).get('positions', [])
            total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
            return {
                'open_positions': len(positions),
                'total_unrealized_pnl': round(total_unrealized, 2),
                'worst_position': min(positions, key=lambda p: p.get('pnl_pct', 0)) if positions else None,
                'best_position': max(positions, key=lambda p: p.get('pnl_pct', 0)) if positions else None,
            }
        except Exception as e:
            return {'error': str(e)}

    async def _get_trade_history(self, params: dict = None) -> dict:
        """Query closed trade history."""
        params = params or {}
        limit = params.get('limit', 50)
        symbol = params.get('symbol')
        channel = params.get('channel')
        days = params.get('days', 30)
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            conn.row_factory = _dict_factory
            cursor = conn.cursor()
            query = "SELECT * FROM trades WHERE status = 'CLOSED' AND closed_at > datetime('now', ? || ' days')"
            args: list = [f'-{days}']
            if symbol:
                query += ' AND symbol = ?'
                args.append(symbol.upper())
            if channel:
                query += ' AND channel_id = ?'
                args.append(str(channel))
            query += ' ORDER BY closed_at DESC LIMIT ?'
            args.append(limit)
            cursor.execute(query, args)
            rows = cursor.fetchall()
            conn.close()
            return {'trades': rows, 'count': len(rows)}
        except Exception as e:
            return {'error': str(e)}

    async def _get_market_regime(self, params: dict = None) -> dict:
        """Get current market regime classification."""
        try:
            from src.ai.market_regime import get_current_regime
            return get_current_regime()
        except Exception as e:
            return {'regime': 'UNKNOWN', 'error': str(e)}

    async def _get_ai_recommendations(self, params: dict = None) -> dict:
        """Get pending AI risk-tuning recommendations."""
        try:
            from src.ai.risk_tuning import get_pending_recommendations
            return {'recommendations': get_pending_recommendations()}
        except Exception as e:
            return {'error': str(e)}

    # ─── Format Tools ─────────────────────────────────────────

    async def _get_format_candidates(self, params: dict = None) -> dict:
        """Get pending AI format candidates."""
        try:
            from gui_app.database import get_pending_ai_format_candidates
            return {'candidates': get_pending_ai_format_candidates()}
        except Exception as e:
            return {'error': str(e)}

    async def _approve_format(self, params: dict) -> dict:
        """Approve a format candidate."""
        candidate_id = params.get('id')
        if candidate_id is None:
            return {'error': 'id is required'}
        try:
            from gui_app.database import update_ai_format_candidate_status
            update_ai_format_candidate_status(candidate_id, 'approved')
            return {'success': True, 'id': candidate_id}
        except Exception as e:
            return {'error': str(e)}

    async def _test_parse(self, params: dict) -> dict:
        """Test parsing a signal message through all available parsers."""
        text = params.get('text', '')
        if not text:
            return {'error': 'text is required'}
        results = []
        # Try signal format registry
        try:
            from src.services.signal_format_registry import parse_all_with_registry
            r = parse_all_with_registry(text)
            if r:
                results.append({'source': 'registry', 'format': r[0].get('_format_name'), 'result': r[0]})
        except Exception:
            pass
        # Try local classifier
        try:
            from src.ai.signal_classifier import get_classifier
            c = get_classifier()
            r = c.predict(text)
            if r:
                results.append({'source': 'local_classifier', 'confidence': r.get('confidence'), 'result': r})
        except Exception:
            pass
        # Try AI API parser
        try:
            from src.services.ai_signal_parser import parse_signal_with_ai
            r = await parse_signal_with_ai(text)
            if r:
                results.append({'source': 'ai_api', 'confidence': r.get('confidence'), 'result': r})
        except Exception:
            pass
        return {'text': text, 'results': results, 'match_count': len(results)}

    # ─── System Tools ─────────────────────────────────────────

    async def _get_broker_status(self, params: dict = None) -> dict:
        """Get broker connection states."""
        try:
            from gui_app.database import get_all_broker_states
            states = get_all_broker_states()
            return {'brokers': states}
        except Exception as e:
            return {'error': str(e)}

    async def _get_system_metrics(self, params: dict = None) -> dict:
        """Get system resource metrics."""
        import platform
        import os
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            return {
                'cpu_pct': proc.cpu_percent(),
                'memory_mb': round(proc.memory_info().rss / 1024 / 1024, 1),
                'uptime_hours': round((time.time() - proc.create_time()) / 3600, 2),
                'python': platform.python_version(),
                'platform': platform.system(),
            }
        except Exception:
            return {'python': platform.python_version(), 'platform': platform.system()}

    async def _get_conditional_orders(self, params: dict = None) -> dict:
        """Get active conditional orders."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            conn.row_factory = _dict_factory
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM conditional_orders WHERE status IN ('PENDING','MONITORING') "
                "ORDER BY created_at DESC LIMIT 50"
            )
            rows = cursor.fetchall()
            conn.close()
            return {'orders': rows, 'count': len(rows)}
        except Exception as e:
            return {'error': str(e)}

    # ─── Intelligence Tools ───────────────────────────────────

    async def _get_channel_scores(self, params: dict = None) -> dict:
        """Get AI channel reliability scores."""
        try:
            from src.ai.channel_scoring import get_all_scores
            return {'scores': get_all_scores()}
        except Exception as e:
            return {'error': str(e)}

    async def _get_consensus_signals(self, params: dict = None) -> dict:
        """Get active multi-channel consensus signals."""
        try:
            from src.ai.consensus import get_active_consensus
            return {'consensus': get_active_consensus()}
        except Exception as e:
            return {'error': str(e)}

    async def _get_execution_quality(self, params: dict = None) -> dict:
        """Get execution quality metrics per broker."""
        days = (params or {}).get('days', 30)
        try:
            from src.ai.execution_quality import get_broker_stats
            return get_broker_stats(days)
        except Exception as e:
            return {'error': str(e)}

    async def _get_ai_feature_status(self, params: dict = None) -> dict:
        """Get status of all AI feature flags."""
        try:
            from src.ai.feature_flags import get_all_flags
            return {'flags': get_all_flags()}
        except Exception as e:
            return {'error': str(e)}

    async def _get_cost_report(self, params: dict = None) -> dict:
        """Get AI API usage and cost summary."""
        days = (params or {}).get('days', 30)
        try:
            from src.ai.cost_tracker import get_usage_summary
            return get_usage_summary(days)
        except Exception as e:
            return {'error': str(e)}

    # ─── MCP Protocol ─────────────────────────────────────────

    def get_tool_definitions(self) -> list:
        """Return MCP-compliant tool definitions for Claude Desktop."""
        defs = []
        for name in self._tools:
            schema = _TOOL_SCHEMAS.get(name, {})
            defs.append({
                'name': name,
                'description': schema.get('description', name.replace('_', ' ')),
                'inputSchema': schema.get('inputSchema', {'type': 'object', 'properties': {}}),
            })
        return defs

    async def call_tool(self, name: str, params: dict = None) -> dict:
        """Execute an MCP tool by name. Returns a dict (always JSON-serializable)."""
        func = self._tools.get(name)
        if not func:
            return {'error': f'Unknown tool: {name}'}
        try:
            return await func(params or {})
        except Exception as e:
            return {'error': f'{name} failed: {e}'}

    # ─── stdio transport (Claude Desktop) ─────────────────────

    async def handle_jsonrpc(self, message: dict) -> dict:
        """Handle a single JSON-RPC 2.0 request."""
        method = message.get('method', '')
        msg_id = message.get('id')
        params = message.get('params', {})

        if method == 'initialize':
            return _jsonrpc_result(msg_id, {
                'protocolVersion': '2024-11-05',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'botify-ai-trading', 'version': '1.0.0'},
            })
        elif method == 'notifications/initialized':
            return None  # notification, no response
        elif method == 'tools/list':
            return _jsonrpc_result(msg_id, {'tools': self.get_tool_definitions()})
        elif method == 'tools/call':
            tool_name = params.get('name', '')
            tool_args = params.get('arguments', {})
            result = await self.call_tool(tool_name, tool_args)
            return _jsonrpc_result(msg_id, {
                'content': [{'type': 'text', 'text': json.dumps(result, default=str)}],
            })
        else:
            return _jsonrpc_error(msg_id, -32601, f'Method not found: {method}')

    async def run_stdio(self):
        """Run the MCP server over stdin/stdout (for Claude Desktop)."""
        import asyncio
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        # Write to stdout
        transport, _ = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_event_loop())

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode('utf-8').strip())
                response = await self.handle_jsonrpc(message)
                if response is not None:
                    out = json.dumps(response) + '\n'
                    writer.write(out.encode('utf-8'))
                    await writer.drain()
            except json.JSONDecodeError:
                err = _jsonrpc_error(None, -32700, 'Parse error')
                writer.write((json.dumps(err) + '\n').encode('utf-8'))
                await writer.drain()
            except Exception as e:
                err = _jsonrpc_error(None, -32603, str(e))
                writer.write((json.dumps(err) + '\n').encode('utf-8'))
                await writer.drain()


# ─── Helpers ──────────────────────────────────────────────────

def _dict_factory(cursor, row):
    """SQLite row factory that returns dicts."""
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _jsonrpc_result(msg_id, result: Any) -> dict:
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def _jsonrpc_error(msg_id, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


# ─── Singleton ────────────────────────────────────────────────

_server: Optional[MCPServer] = None


def get_mcp_server() -> MCPServer:
    """Get or create the singleton MCP server instance."""
    global _server
    if _server is None:
        _server = MCPServer()
    return _server


# ─── CLI entry point for Claude Desktop ──────────────────────

if __name__ == '__main__':
    import asyncio
    server = get_mcp_server()
    asyncio.run(server.run_stdio())

import asyncio
import json
import time
import traceback
from typing import Optional, Any

HEARTBEAT_INTERVAL = 30
STATUS_INTERVAL = 15
POSITIONS_INTERVAL = 5
CONDITIONAL_INTERVAL = 15
RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 300

_relay_instance: Optional['RelayClient'] = None


def get_relay_client() -> Optional['RelayClient']:
    return _relay_instance


def set_relay_client(client: Optional['RelayClient']):
    global _relay_instance
    _relay_instance = client


class RelayClient:
    def __init__(self, bot_token: str, server_url: str, bot_instance=None, permissions: Optional[dict] = None):
        self._token = bot_token
        self._url = f"{server_url}?token={bot_token}"
        self._bot = bot_instance
        self._ws = None
        self._connected = False
        self._reconnect_delay = RECONNECT_BASE_DELAY
        self._should_run = True
        self._tasks: list = []
        self._permissions = permissions or {
            'allow_pause': True,
            'allow_close': False,
            'allow_close_all': False,
        }

    @property
    def connected(self) -> bool:
        return self._connected

    def update_permissions(self, permissions: dict):
        self._permissions = permissions

    async def connect(self):
        try:
            import websockets
        except ImportError:
            print("[RELAY] ❌ websockets package not installed — relay disabled")
            return

        while self._should_run:
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = RECONNECT_BASE_DELAY
                    print("[RELAY] ✅ Connected to relay server")

                    self._tasks = [
                        asyncio.create_task(self._heartbeat_loop()),
                        asyncio.create_task(self._status_loop()),
                        asyncio.create_task(self._positions_loop()),
                        asyncio.create_task(self._conditional_orders_loop()),
                    ]

                    await self._receive_loop()

            except Exception as e:
                err_str = str(e)
                if '4001' in err_str or '403' in err_str or 'invalid' in err_str.lower() or 'forbidden' in err_str.lower():
                    print(f"[RELAY] Auth rejected ({e}) -- check bot token in Remote Access settings")
                    self._should_run = False
                    return
                print(f"[RELAY] Connection error: {e}")
            finally:
                self._connected = False
                self._ws = None
                for task in self._tasks:
                    task.cancel()
                self._tasks.clear()

            if self._should_run:
                print(f"[RELAY] Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX_DELAY)

    async def disconnect(self):
        self._should_run = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        print("[RELAY] Disconnected from relay server")

    # ─── Receive loop ───

    async def _receive_loop(self):
        import websockets
        try:
            async for message in self._ws:
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    if msg_type == "command":
                        await self._handle_command(msg)
                    elif msg_type == "heartbeat_ack":
                        pass
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"[RELAY] Error handling message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass

    # ─── Background push loops ───

    async def _heartbeat_loop(self):
        while self._connected:
            try:
                await self._send({"type": "heartbeat", "version": self._get_bot_version(), "ts": int(time.time())})
            except Exception:
                break
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _status_loop(self):
        await asyncio.sleep(2)
        loop = asyncio.get_event_loop()
        while self._connected:
            try:
                status = await loop.run_in_executor(None, self._build_status)
                if status:
                    await self.send_status(status)
            except Exception as e:
                print(f"[RELAY] Status push error: {e}")
            await asyncio.sleep(STATUS_INTERVAL)

    async def _positions_loop(self):
        await asyncio.sleep(3)
        loop = asyncio.get_event_loop()
        while self._connected:
            try:
                positions = await loop.run_in_executor(None, self._build_positions)
                if positions:
                    await self.send_positions(positions)
            except Exception as e:
                print(f"[RELAY] Positions push error: {e}")
            await asyncio.sleep(POSITIONS_INTERVAL)

    async def _conditional_orders_loop(self):
        await asyncio.sleep(4)
        loop = asyncio.get_event_loop()
        while self._connected:
            try:
                orders = await loop.run_in_executor(None, self._build_conditional_orders)
                if orders:
                    await self.send_conditional_orders(orders)
            except Exception as e:
                print(f"[RELAY] Conditional orders push error: {e}")
            await asyncio.sleep(CONDITIONAL_INTERVAL)

    # ─── Send methods ───

    async def _send(self, data: dict):
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(data))
            except Exception:
                pass

    async def send_status(self, status: dict):
        await self._send({"type": "status", "data": status})

    async def send_positions(self, positions: list):
        await self._send({"type": "positions", "data": positions})

    async def send_alert(self, alert: dict):
        await self._send({"type": "alert", "data": alert})

    async def send_trade(self, trade: dict):
        await self._send({"type": "trade", "data": trade})

    async def send_conditional_orders(self, orders: list):
        await self._send({"type": "conditional_orders", "data": orders})

    async def send_command_ack(self, action: str, success: bool, message: str = ""):
        await self._send({
            "type": "command_ack",
            "action": action,
            "success": success,
            "message": message,
        })

    # ─── Build data from bot state (runs in executor thread) ───

    def _build_status(self) -> Optional[dict]:
        try:
            snapshot = self._get_snapshot()
            if not snapshot:
                return None

            positions = snapshot.get('positions', [])
            broker_status = snapshot.get('broker_status', {})
            risk_states = snapshot.get('risk_states', {})

            total_pnl = 0.0
            for pos in positions:
                total_pnl += float(pos.get('unrealized_pnl', 0) or 0)

            brokers = []
            for name, info in broker_status.items():
                brokers.append({
                    'name': name,
                    'connected': bool(info.get('connected') or info.get('is_connected')),
                    'positions': info.get('position_count', 0),
                })

            paused = False
            try:
                from gui_app.database import get_global_risk_settings
                settings = get_global_risk_settings()
                paused = bool(settings.get('trading_paused', 0))
            except Exception:
                pass

            return {
                'running': True,
                'version': self._get_bot_version(),
                'trading_paused': paused,
                'positions': len(positions),
                'positions_count': len(positions),
                'pnl': round(total_pnl, 2),
                'risk_active': len(risk_states) > 0,
                'brokers': brokers,
            }
        except Exception as e:
            print(f"[RELAY] Error building status: {e}")
            return None

    def _build_positions(self) -> list:
        try:
            snapshot = self._get_snapshot()
            if not snapshot:
                return []

            positions = snapshot.get('positions', [])
            risk_states = snapshot.get('risk_states', {})

            result = []
            for pos in positions:
                symbol = pos.get('symbol', '')
                broker = pos.get('broker', '')
                qty = pos.get('quantity', 0) or pos.get('qty', 0)
                entry = float(pos.get('avg_price', 0) or pos.get('entry_price', 0) or 0)
                current = float(pos.get('current_price', 0) or pos.get('last_price', 0) or 0)
                pnl = float(pos.get('unrealized_pnl', 0) or 0)

                sl = None
                pt = None
                for rk, rs in risk_states.items():
                    if rs.get('position_key', '').startswith(symbol):
                        sl = rs.get('stop_loss_price') or rs.get('effective_sl_price')
                        pt = rs.get('profit_target_price')
                        break

                pnl_pct = round(((current - entry) / entry) * 100, 2) if entry > 0 else 0.0
                side = pos.get('side', 'long')

                result.append({
                    'symbol': symbol,
                    'side': side,
                    'quantity': qty,
                    'qty': qty,
                    'entry_price': round(entry, 2) if entry else 0,
                    'avg_price': round(entry, 2) if entry else 0,
                    'current_price': round(current, 2) if current else 0,
                    'last_price': round(current, 2) if current else 0,
                    'pnl': round(pnl, 2),
                    'unrealized_pnl': round(pnl, 2),
                    'pnl_pct': pnl_pct,
                    'unrealized_pnl_pct': pnl_pct,
                    'broker': broker,
                    'stop_loss': round(sl, 2) if sl else None,
                    'profit_target': round(pt, 2) if pt else None,
                })

            return result
        except Exception as e:
            print(f"[RELAY] Error building positions: {e}")
            return []

    def _build_conditional_orders(self) -> list:
        try:
            from gui_app.database import get_active_conditional_orders
            orders = get_active_conditional_orders()
            result = []
            for o in orders:
                trigger_type = o.get('trigger_type', '')
                tt_lower = trigger_type.lower()
                if 'above' in tt_lower:
                    order_type = 'Buy Above'
                elif 'below' in tt_lower:
                    order_type = 'Buy Below'
                else:
                    order_type = trigger_type or 'Conditional'

                result.append({
                    'id': o.get('id'),
                    'symbol': o.get('symbol', ''),
                    'order_type': order_type,
                    'type': order_type,
                    'trigger_type': trigger_type,
                    'trigger_price': float(o.get('adjusted_trigger_price') or o.get('trigger_price', 0) or 0),
                    'trigger': float(o.get('trigger_price', 0) or 0),
                    'quantity': o.get('calculated_qty') or o.get('qty_value'),
                    'qty': o.get('calculated_qty') or o.get('qty_value'),
                    'broker': o.get('broker_primary', ''),
                    'status': o.get('status', ''),
                    'asset_type': o.get('asset_type', 'stock'),
                })
            return result
        except Exception as e:
            print(f"[RELAY] Error building conditional orders: {e}")
            return []

    def _get_snapshot(self) -> Optional[dict]:
        try:
            from gui_app.live_snapshot import get_live_snapshot
            return get_live_snapshot()
        except Exception:
            return None

    def _get_bot_version(self) -> str:
        try:
            from upgrade.version import APP_VERSION
            return APP_VERSION
        except Exception:
            return "unknown"

    # ─── Command handlers ───

    async def _handle_command(self, msg: dict):
        action = msg.get("action")
        data = msg.get("data", {})
        print(f"[RELAY] 📥 Received command: {action}")

        try:
            if action == "pause_trading":
                if not self._permissions.get('allow_pause'):
                    await self.send_command_ack(action, False, "Pause not permitted")
                    return
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._do_set_trading_paused, True)
                await self.send_command_ack(action, True, "Trading paused")

            elif action == "resume_trading":
                if not self._permissions.get('allow_pause'):
                    await self.send_command_ack(action, False, "Resume not permitted")
                    return
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._do_set_trading_paused, False)
                await self.send_command_ack(action, True, "Trading resumed")

            elif action == "close_position":
                if not self._permissions.get('allow_close'):
                    await self.send_command_ack(action, False, "Position close not permitted")
                    return
                symbol = data.get("symbol")
                broker = data.get("broker")
                success, result_msg = await self._close_position(symbol, broker)
                await self.send_command_ack(action, success, result_msg)

            elif action == "close_all":
                if not self._permissions.get('allow_close_all'):
                    await self.send_command_ack(action, False, "Close all not permitted")
                    return
                success, result_msg = await self._close_all_positions()
                await self.send_command_ack(action, success, result_msg)

            elif action == "emergency_stop":
                cancelled, closed_count, result_msg = await self._emergency_stop()
                await self.send_command_ack(action, True, result_msg)
                await self.send_alert({
                    'alert_type': 'emergency_stop',
                    'level': 'critical',
                    'msg': result_msg,
                    'ts': time.time(),
                })

            elif action == "cancel_conditional":
                order_id = data.get("order_id")
                loop = asyncio.get_event_loop()
                success, result_msg = await loop.run_in_executor(None, self._do_cancel_conditional, order_id)
                await self.send_command_ack(action, success, result_msg)

            elif action == "request_status":
                loop = asyncio.get_event_loop()
                status = await loop.run_in_executor(None, self._build_status)
                if status:
                    await self.send_status(status)

            elif action == "request_positions":
                loop = asyncio.get_event_loop()
                positions = await loop.run_in_executor(None, self._build_positions)
                await self.send_positions(positions)

            else:
                await self.send_command_ack(action, False, f"Unknown action: {action}")

        except Exception as e:
            print(f"[RELAY] ❌ Command '{action}' failed: {e}")
            await self.send_command_ack(action, False, str(e))

    def _do_set_trading_paused(self, paused: bool):
        from gui_app.database import get_connection
        from datetime import datetime
        conn = get_connection()
        cursor = conn.cursor()
        if paused:
            cursor.execute(
                'UPDATE global_risk_settings SET trading_paused = 1, trading_paused_at = ? WHERE id = 1',
                (datetime.now().isoformat(),)
            )
            print("[RELAY] ⏸️ Trading PAUSED via mobile")
        else:
            cursor.execute(
                'UPDATE global_risk_settings SET trading_paused = 0, trading_paused_at = NULL WHERE id = 1',
            )
            print("[RELAY] ▶️ Trading RESUMED via mobile")
        conn.commit()

    def _do_cancel_conditional(self, order_id: int) -> tuple:
        if not order_id:
            return False, "Missing order_id"
        try:
            from gui_app.database import cancel_conditional_order
            cancel_conditional_order(order_id, reason="Cancelled via mobile app")
            print(f"[RELAY] ✅ Cancelled conditional order #{order_id}")
            return True, f"Order #{order_id} cancelled"
        except Exception as e:
            return False, str(e)

    async def _close_position(self, symbol: str, broker: str) -> tuple:
        if not symbol or not broker:
            return False, "Missing symbol or broker"

        if not self._bot:
            return False, "Bot instance not available"

        try:
            snapshot = self._get_snapshot()
            qty = 0
            if snapshot:
                for pos in snapshot.get('positions', []):
                    if pos.get('symbol') == symbol and pos.get('broker', '').upper().startswith(broker.upper()):
                        qty = int(pos.get('quantity', 0) or pos.get('qty', 0) or 0)
                        break

            if qty <= 0:
                return False, f"No open position found for {symbol} on {broker}"

            broker_obj = self._get_broker_by_name(broker)
            if not broker_obj:
                return False, f"Broker '{broker}' not found"

            if hasattr(broker_obj, 'place_stock_order'):
                result = await broker_obj.place_stock_order(symbol, 'STC', qty)
                if result:
                    print(f"[RELAY] ✅ Closed {symbol} qty={qty} on {broker}")
                    return True, f"Closed {symbol} ({qty} shares)"
                return False, f"Failed to close {symbol}"
            return False, f"Broker {broker} doesn't support close"
        except Exception as e:
            return False, str(e)

    async def _close_all_positions(self) -> tuple:
        if not self._bot:
            return False, "Bot instance not available"

        try:
            snapshot = self._get_snapshot()
            if not snapshot:
                return False, "No snapshot available"

            positions = snapshot.get('positions', [])
            if not positions:
                return True, "No open positions"

            closed = 0
            failed = 0
            for pos in positions:
                symbol = pos.get('symbol', '')
                broker = pos.get('broker', '')
                if symbol and broker:
                    success, _ = await self._close_position(symbol, broker)
                    if success:
                        closed += 1
                    else:
                        failed += 1

            msg = f"Closed {closed} positions"
            if failed:
                msg += f", {failed} failed"
            return failed == 0, msg
        except Exception as e:
            return False, str(e)

    def _get_broker_by_name(self, broker_name: str) -> Optional[Any]:
        if not self._bot:
            return None
        name = broker_name.upper().strip()
        broker_map = {
            'SCHWAB': 'schwab_broker',
            'ALPACA': 'broker',
            'WEBULL_OFFICIAL': 'webull_official_broker',
            'WEBULL': 'broker',
            'IBKR': 'ibkr_broker',
            'TASTYTRADE': 'tastytrade_broker',
            'ROBINHOOD': 'robinhood_broker',
            'TRADING212': 'trading212_broker',
        }
        for prefix, attr in broker_map.items():
            if name.startswith(prefix):
                return getattr(self._bot, attr, None)
        return None

    def _get_all_broker_instances(self) -> list:
        if not self._bot:
            return []
        broker_attrs = [
            'schwab_broker', 'paper_broker', 'broker', 'ibkr_broker',
            'tastytrade_broker', 'robinhood_broker', 'trading212_broker',
            'webull_official_broker',
        ]
        seen = set()
        result = []
        for attr in broker_attrs:
            inst = getattr(self._bot, attr, None)
            if inst and id(inst) not in seen:
                seen.add(id(inst))
                result.append(inst)
        return result

    async def _cancel_all_broker_orders(self) -> int:
        cancelled = 0
        loop = asyncio.get_event_loop()
        for broker in self._get_all_broker_instances():
            try:
                broker_name = getattr(broker, 'name', type(broker).__name__)
                orders = []
                if hasattr(broker, 'get_pending_orders'):
                    fn = broker.get_pending_orders
                    if asyncio.iscoroutinefunction(fn):
                        orders = await fn()
                    else:
                        orders = await loop.run_in_executor(None, fn)
                elif hasattr(broker, 'get_open_orders'):
                    fn = broker.get_open_orders
                    if asyncio.iscoroutinefunction(fn):
                        orders = await fn()
                    else:
                        orders = await loop.run_in_executor(None, fn)

                if not orders:
                    continue

                is_robinhood = 'Robinhood' in type(broker).__name__
                for order in orders:
                    oid = order.get('order_id') or order.get('broker_order_id')
                    if not oid:
                        continue
                    try:
                        if is_robinhood:
                            o_type = 'option' if order.get('asset_type') == 'option' else 'stock'
                            await broker.cancel_order(str(oid), order_type=o_type)
                        elif asyncio.iscoroutinefunction(broker.cancel_order):
                            await broker.cancel_order(str(oid))
                        else:
                            await loop.run_in_executor(None, broker.cancel_order, str(oid))
                        cancelled += 1
                        print(f"[RELAY] EMERGENCY: Cancelled order {oid} on {broker_name}")
                    except Exception as ce:
                        print(f"[RELAY] EMERGENCY: Failed to cancel {oid} on {broker_name}: {ce}")
            except Exception as e:
                print(f"[RELAY] EMERGENCY: Error cancelling orders on {getattr(broker, 'name', '?')}: {e}")
        return cancelled

    async def _emergency_stop(self) -> tuple:
        print("[RELAY] 🚨 EMERGENCY STOP initiated from mobile")

        cancelled = await self._cancel_all_broker_orders()
        print(f"[RELAY] 🚨 Phase 1: Cancelled {cancelled} broker orders")

        closed_count = 0
        close_success, close_msg = await self._close_all_positions()
        if close_success:
            import re
            m = re.search(r'Closed (\d+)', close_msg)
            closed_count = int(m.group(1)) if m else 0
        print(f"[RELAY] 🚨 Phase 2: {close_msg}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._do_set_trading_paused, True)
        print("[RELAY] 🚨 Phase 3: Trading PAUSED")

        msg = f"Emergency stop: {cancelled} orders cancelled, {close_msg}, trading paused"
        print(f"[RELAY] 🚨 COMPLETE: {msg}")
        return cancelled, closed_count, msg

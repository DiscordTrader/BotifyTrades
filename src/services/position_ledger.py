"""
Position Ledger Service
========================
Single Source of Truth for all signal-based positions across channels and brokers.

Features:
- Unified position tracking across spy-sniper, manual signals, and broker positions
- Per-broker/account position records with separate quantities
- Partial exit tracking with running P&L calculations
- Restart recovery with broker sync reconciliation
- Exit Arbiter with per-option locks to prevent double-sells
- Staleness tracking for live price data
"""

import asyncio
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


class PositionStatus(Enum):
    """Position lifecycle status."""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"
    EXPIRED = "expired"


class ExitReason(Enum):
    """Reason for position exit."""
    SIGNAL = "signal"
    PT1 = "pt1"
    PT2 = "pt2"
    PT3 = "pt3"
    PT4 = "pt4"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    GIVEBACK_GUARD = "giveback_guard"
    EARLY_TRAILING = "early_trailing"
    EMA_EXIT = "ema_exit"
    MANUAL = "manual"
    EXPIRED = "expired"


@dataclass
class PartialExit:
    """Record of a partial or full exit from a position."""
    id: Optional[int] = None
    position_id: int = 0
    exit_qty: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""
    exit_pnl_dollar: float = 0.0
    exit_pnl_pct: float = 0.0
    exit_time: str = ""
    message_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerPosition:
    """A position tracked in the ledger."""
    id: Optional[int] = None
    option_key: str = ""
    symbol: str = ""
    expiry: str = ""
    strike: float = 0.0
    option_type: str = ""
    
    channel_id: str = ""
    broker_id: str = ""
    account_id: str = ""
    
    entry_qty: int = 0
    remaining_qty: int = 0
    entry_price: float = 0.0
    signal_entry_price: float = 0.0
    initial_mark_price: float = 0.0
    current_price: float = 0.0
    price_updated_at: str = ""
    price_staleness_sec: int = 0
    
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    
    status: str = "open"
    entry_time: str = ""
    last_exit_time: str = ""
    close_time: str = ""
    
    entry_message_id: str = ""
    source_type: str = "spy_sniper"
    routing_mapping_id: Optional[int] = None  # Signal routing discriminator for risk engine
    
    pt_levels_hit: str = "[]"
    max_pnl_seen: float = 0.0
    trailing_stop_active: bool = False
    
    dynamic_sl_price: Optional[float] = None
    giveback_guard_active: bool = False
    
    early_trailing_active: bool = False
    early_stop_price: Optional[float] = None
    early_steps_locked: int = 0
    ema_no_trend_count: int = 0
    
    partial_exits: List[PartialExit] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['partial_exits'] = [e.to_dict() for e in self.partial_exits]
        return d
    
    def calculate_unrealized_pnl(self) -> Tuple[float, float]:
        """Calculate unrealized P&L based on current price.
        
        Uses initial_mark_price (first live quote) for P&L calculations,
        NOT entry_price (signal price which is for forwarding only).
        Falls back to entry_price if initial_mark_price not yet set.
        """
        if self.remaining_qty <= 0 or self.current_price <= 0:
            return 0.0, 0.0
        
        cost_basis_price = self.initial_mark_price if self.initial_mark_price > 0 else self.entry_price
        cost_basis = cost_basis_price * self.remaining_qty * 100
        current_value = self.current_price * self.remaining_qty * 100
        
        pnl_dollar = current_value - cost_basis
        pnl_pct = (pnl_dollar / cost_basis * 100) if cost_basis > 0 else 0.0
        
        return pnl_dollar, pnl_pct
    
    def calculate_total_pnl(self) -> Tuple[float, float]:
        """Calculate total P&L (realized + unrealized)."""
        unrealized_dollar, _ = self.calculate_unrealized_pnl()
        total_dollar = self.realized_pnl + unrealized_dollar
        
        total_cost = self.entry_price * self.entry_qty * 100
        total_pct = (total_dollar / total_cost * 100) if total_cost > 0 else 0.0
        
        return total_dollar, total_pct


class ExitArbiter:
    """
    Prevents double-exits by maintaining per-position locks.
    
    Uses threading.Lock for cross-thread safety (risk management threads +
    asyncio signal handlers can both trigger exits concurrently).
    
    Lock key includes:
    - option_key: The option contract identifier
    - broker_id: Broker isolation
    - account_id: Account isolation  
    - routing_mapping_id: Multi-mapping isolation (same symbol routed to multiple destinations)
    
    This ensures only one exit operation runs at a time for each unique position.
    """
    
    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._sync_lock = threading.Lock()
    
    def _get_lock_key(
        self, 
        option_key: str, 
        broker_id: str = "", 
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ) -> str:
        """Generate lock key with full position isolation."""
        mapping_str = str(routing_mapping_id) if routing_mapping_id else "0"
        return f"{option_key}_{broker_id}_{account_id}_{mapping_str}"
    
    def get_lock(
        self, 
        option_key: str, 
        broker_id: str = "", 
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ) -> threading.Lock:
        """Get or create a lock for the given position key."""
        key = self._get_lock_key(option_key, broker_id, account_id, routing_mapping_id)
        with self._sync_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]
    
    def release_lock(
        self, 
        option_key: str, 
        broker_id: str = "", 
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ):
        """Remove lock when position is fully closed."""
        key = self._get_lock_key(option_key, broker_id, account_id, routing_mapping_id)
        with self._sync_lock:
            self._locks.pop(key, None)
    
    async def acquire_exit_lock(
        self, 
        option_key: str, 
        broker_id: str = "", 
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ) -> bool:
        """Attempt to acquire exit lock. Returns False if already locked (non-blocking)."""
        lock = self.get_lock(option_key, broker_id, account_id, routing_mapping_id)
        return lock.acquire(blocking=False)
    
    def acquire_exit_lock_sync(
        self,
        option_key: str,
        broker_id: str = "",
        account_id: str = "",
        routing_mapping_id: Optional[int] = None,
        timeout: float = 0.1
    ) -> bool:
        """Synchronous version for use from monitoring threads."""
        lock = self.get_lock(option_key, broker_id, account_id, routing_mapping_id)
        return lock.acquire(blocking=True, timeout=timeout)
    
    def release_exit_lock(
        self,
        option_key: str,
        broker_id: str = "",
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ):
        """Release exit lock after exit operation completes."""
        key = self._get_lock_key(option_key, broker_id, account_id, routing_mapping_id)
        with self._sync_lock:
            lock = self._locks.get(key)
            if lock and lock.locked():
                try:
                    lock.release()
                except RuntimeError:
                    pass


class PositionLedger:
    """
    Single Source of Truth for all positions.
    
    Provides:
    - Position CRUD with SQLite persistence
    - Partial exit tracking
    - P&L calculations
    - Broker sync reconciliation
    - Exit arbitration
    """
    
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.exit_arbiter = ExitArbiter()
        self._init_tables()
    
    _MAX_DB_RETRIES = 3
    _DB_RETRY_BASE_DELAY = 0.1

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory, WAL mode, and busy timeout."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _execute_with_retry(self, conn, sql, params=None, commit=False):
        """Execute SQL with retry on OperationalError (database locked)."""
        import time as _t
        import random as _r
        for attempt in range(self._MAX_DB_RETRIES):
            try:
                cursor = conn.execute(sql, params or ())
                if commit:
                    conn.commit()
                return cursor
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < self._MAX_DB_RETRIES - 1:
                    delay = self._DB_RETRY_BASE_DELAY * (2 ** attempt) + _r.uniform(0, 0.05)
                    print(f"[LEDGER] ⚠️ DB locked (attempt {attempt+1}/{self._MAX_DB_RETRIES}), retrying in {delay:.2f}s...")
                    _t.sleep(delay)
                else:
                    raise
    
    def _init_tables(self):
        """Initialize ledger tables if they don't exist."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS position_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    option_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    expiry TEXT,
                    strike REAL,
                    option_type TEXT,
                    channel_id TEXT,
                    broker_id TEXT,
                    account_id TEXT,
                    entry_qty INTEGER NOT NULL,
                    remaining_qty INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL DEFAULT 0,
                    price_updated_at TEXT,
                    price_staleness_sec INTEGER DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    total_pnl_pct REAL DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    entry_time TEXT NOT NULL,
                    last_exit_time TEXT,
                    close_time TEXT,
                    entry_message_id TEXT,
                    source_type TEXT DEFAULT 'spy_sniper',
                    routing_mapping_id INTEGER,
                    pt_levels_hit TEXT DEFAULT '[]',
                    max_pnl_seen REAL DEFAULT 0,
                    trailing_stop_active INTEGER DEFAULT 0,
                    dynamic_sl_price REAL,
                    giveback_guard_active INTEGER DEFAULT 0,
                    UNIQUE(option_key, broker_id, account_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS partial_exits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    exit_qty INTEGER NOT NULL,
                    exit_price REAL NOT NULL,
                    exit_reason TEXT,
                    exit_pnl_dollar REAL DEFAULT 0,
                    exit_pnl_pct REAL DEFAULT 0,
                    exit_time TEXT NOT NULL,
                    message_id TEXT,
                    FOREIGN KEY (position_id) REFERENCES position_ledger(id)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_option_key 
                ON position_ledger(option_key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_status 
                ON position_ledger(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_channel 
                ON position_ledger(channel_id)
            """)
            
            # ===== UNIQUE INDEX FOR EXIT IDEMPOTENCY =====
            # Prevents race condition where two concurrent exits insert before either commits
            # message_id stores the dedupe_key (position_id:exit_reason:exit_qty hash)
            try:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_routing_unique
                    ON position_ledger(option_key, broker_id, account_id, routing_mapping_id)
                """)
            except Exception:
                pass
            
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_partial_exits_dedupe
                ON partial_exits(position_id, message_id)
                WHERE message_id IS NOT NULL AND message_id != ''
            """)
            
            # Migrations: Add columns if missing (for existing tables)
            migrations = [
                ("routing_mapping_id", "ALTER TABLE position_ledger ADD COLUMN routing_mapping_id INTEGER"),
                ("signal_entry_price", "ALTER TABLE position_ledger ADD COLUMN signal_entry_price REAL DEFAULT 0"),
                ("initial_mark_price", "ALTER TABLE position_ledger ADD COLUMN initial_mark_price REAL DEFAULT 0"),
                ("dynamic_sl_price", "ALTER TABLE position_ledger ADD COLUMN dynamic_sl_price REAL"),
                ("giveback_guard_active", "ALTER TABLE position_ledger ADD COLUMN giveback_guard_active INTEGER DEFAULT 0"),
                ("early_trailing_active", "ALTER TABLE position_ledger ADD COLUMN early_trailing_active INTEGER DEFAULT 0"),
                ("early_stop_price", "ALTER TABLE position_ledger ADD COLUMN early_stop_price REAL"),
                ("early_steps_locked", "ALTER TABLE position_ledger ADD COLUMN early_steps_locked INTEGER DEFAULT 0"),
                ("ema_no_trend_count", "ALTER TABLE position_ledger ADD COLUMN ema_no_trend_count INTEGER DEFAULT 0"),
            ]
            
            for col_name, sql in migrations:
                try:
                    conn.execute(f"SELECT {col_name} FROM position_ledger LIMIT 1")
                except sqlite3.OperationalError:
                    print(f"[LEDGER] Adding {col_name} column...")
                    conn.execute(sql)
            
            conn.commit()
            print("[LEDGER] ✓ Position ledger tables initialized")
        finally:
            conn.close()
    
    def create_position(self, position: LedgerPosition) -> int:
        """Create a new position in the ledger. Returns position ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("""
                INSERT INTO position_ledger (
                    option_key, symbol, expiry, strike, option_type,
                    channel_id, broker_id, account_id,
                    entry_qty, remaining_qty, entry_price,
                    signal_entry_price, initial_mark_price,
                    current_price, price_updated_at,
                    status, entry_time, entry_message_id, source_type,
                    routing_mapping_id, pt_levels_hit, max_pnl_seen, trailing_stop_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.option_key, position.symbol, position.expiry,
                position.strike, position.option_type,
                position.channel_id, position.broker_id, position.account_id,
                position.entry_qty, position.remaining_qty, position.entry_price,
                position.signal_entry_price or position.entry_price,
                position.initial_mark_price or 0.0,
                position.current_price, position.price_updated_at,
                position.status, position.entry_time, position.entry_message_id,
                position.source_type, position.routing_mapping_id, position.pt_levels_hit,
                position.max_pnl_seen, 1 if position.trailing_stop_active else 0
            ))
            conn.commit()
            position_id = cursor.lastrowid if cursor.lastrowid else 0
            print(f"[LEDGER] ✓ Created position {position.option_key} (ID: {position_id})")
            return position_id
        except sqlite3.IntegrityError:
            print(f"[LEDGER] Position already exists: {position.option_key}")
            existing = self.get_position_by_key(
                position.option_key, 
                position.broker_id, 
                position.account_id,
                routing_mapping_id=position.routing_mapping_id
            )
            return existing.id if existing and existing.id else 0
        finally:
            conn.close()
    
    def get_position(self, position_id: int) -> Optional[LedgerPosition]:
        """Get position by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM position_ledger WHERE id = ?",
                (position_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_position(row, conn)
        finally:
            conn.close()
    
    def get_position_by_key(
        self, 
        option_key: str, 
        broker_id: str = "", 
        account_id: str = "",
        routing_mapping_id: Optional[int] = None
    ) -> Optional[LedgerPosition]:
        """Get position by option key and broker/account, optionally filtered by routing_mapping_id."""
        conn = self._get_conn()
        try:
            if routing_mapping_id is not None:
                row = conn.execute("""
                    SELECT * FROM position_ledger 
                    WHERE option_key = ? AND broker_id = ? AND account_id = ?
                    AND routing_mapping_id = ?
                    AND status IN ('open', 'partially_closed')
                """, (option_key, broker_id, account_id, routing_mapping_id)).fetchone()
            else:
                row = conn.execute("""
                    SELECT * FROM position_ledger 
                    WHERE option_key = ? AND broker_id = ? AND account_id = ?
                    AND status IN ('open', 'partially_closed')
                """, (option_key, broker_id, account_id)).fetchone()
            
            if not row:
                return None
            
            return self._row_to_position(row, conn)
        finally:
            conn.close()
    
    def get_open_positions(
        self, 
        channel_id: Optional[str] = None,
        broker_id: Optional[str] = None,
        source_type: Optional[str] = None
    ) -> List[LedgerPosition]:
        """Get all open positions, optionally filtered by channel, broker, or source_type."""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM position_ledger WHERE status IN ('open', 'partially_closed')"
            params: List[Any] = []
            
            if channel_id:
                query += " AND channel_id = ?"
                params.append(channel_id)
            
            if broker_id:
                query += " AND broker_id = ?"
                params.append(broker_id)
            
            if source_type:
                query += " AND source_type = ?"
                params.append(source_type)
            
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_position(row, conn) for row in rows]
        finally:
            conn.close()
    
    def get_closed_positions(self, limit: int = 100) -> List[LedgerPosition]:
        """Get closed positions for P&L summary."""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM position_ledger WHERE status = 'closed' ORDER BY id DESC LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()
            return [self._row_to_position(row, conn) for row in rows]
        finally:
            conn.close()
    
    def _row_to_position(self, row: sqlite3.Row, conn: sqlite3.Connection) -> LedgerPosition:
        """Convert database row to LedgerPosition."""
        signal_entry = row['signal_entry_price'] if 'signal_entry_price' in row.keys() else 0.0
        initial_mark = row['initial_mark_price'] if 'initial_mark_price' in row.keys() else 0.0
        routing_id = row['routing_mapping_id'] if 'routing_mapping_id' in row.keys() else None
        
        position = LedgerPosition(
            id=row['id'],
            option_key=row['option_key'],
            symbol=row['symbol'],
            expiry=row['expiry'] or "",
            strike=row['strike'] or 0.0,
            option_type=row['option_type'] or "",
            channel_id=row['channel_id'] or "",
            broker_id=row['broker_id'] or "",
            account_id=row['account_id'] or "",
            entry_qty=row['entry_qty'],
            remaining_qty=row['remaining_qty'],
            entry_price=row['entry_price'],
            signal_entry_price=signal_entry or 0.0,
            initial_mark_price=initial_mark or 0.0,
            current_price=row['current_price'] or 0.0,
            price_updated_at=row['price_updated_at'] or "",
            price_staleness_sec=row['price_staleness_sec'] or 0,
            realized_pnl=row['realized_pnl'] or 0.0,
            unrealized_pnl=row['unrealized_pnl'] or 0.0,
            total_pnl_pct=row['total_pnl_pct'] or 0.0,
            status=row['status'],
            entry_time=row['entry_time'],
            last_exit_time=row['last_exit_time'] or "",
            close_time=row['close_time'] or "",
            entry_message_id=row['entry_message_id'] or "",
            source_type=row['source_type'] or "spy_sniper",
            routing_mapping_id=routing_id,
            pt_levels_hit=row['pt_levels_hit'] or "[]",
            max_pnl_seen=row['max_pnl_seen'] or 0.0,
            trailing_stop_active=bool(row['trailing_stop_active']),
            dynamic_sl_price=row['dynamic_sl_price'] if 'dynamic_sl_price' in row.keys() else None,
            giveback_guard_active=bool(row['giveback_guard_active']) if 'giveback_guard_active' in row.keys() else False,
            early_trailing_active=bool(row['early_trailing_active']) if 'early_trailing_active' in row.keys() else False,
            early_stop_price=row['early_stop_price'] if 'early_stop_price' in row.keys() else None,
            early_steps_locked=row['early_steps_locked'] if 'early_steps_locked' in row.keys() else 0,
            ema_no_trend_count=row['ema_no_trend_count'] if 'ema_no_trend_count' in row.keys() else 0
        )
        
        exit_rows = conn.execute(
            "SELECT * FROM partial_exits WHERE position_id = ? ORDER BY exit_time",
            (position.id,)
        ).fetchall()
        
        position.partial_exits = [
            PartialExit(
                id=er['id'],
                position_id=er['position_id'],
                exit_qty=er['exit_qty'],
                exit_price=er['exit_price'],
                exit_reason=er['exit_reason'] or "",
                exit_pnl_dollar=er['exit_pnl_dollar'] or 0.0,
                exit_pnl_pct=er['exit_pnl_pct'] or 0.0,
                exit_time=er['exit_time'],
                message_id=er['message_id'] or ""
            )
            for er in exit_rows
        ]
        
        return position
    
    def update_price(
        self, 
        position_id: int, 
        current_price: float,
        staleness_sec: int = 0
    ):
        """Update current price for a position.
        
        Also sets initial_mark_price on first price update (when it's 0).
        This enables accurate P&L tracking using market price vs signal price.
        """
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            
            row = conn.execute(
                "SELECT entry_price, remaining_qty, initial_mark_price FROM position_ledger WHERE id = ?",
                (position_id,)
            ).fetchone()
            
            if not row:
                return
            
            entry_price = row['entry_price']
            remaining_qty = row['remaining_qty']
            initial_mark = row['initial_mark_price'] if 'initial_mark_price' in row.keys() else 0.0
            
            cost_basis_price = initial_mark if (initial_mark and initial_mark > 0) else entry_price
            cost_basis = cost_basis_price * remaining_qty * 100
            current_value = current_price * remaining_qty * 100
            unrealized_pnl = current_value - cost_basis
            
            if initial_mark is None or initial_mark == 0:
                conn.execute("""
                    UPDATE position_ledger SET
                        current_price = ?,
                        price_updated_at = ?,
                        price_staleness_sec = ?,
                        unrealized_pnl = ?,
                        initial_mark_price = ?
                    WHERE id = ?
                """, (current_price, now, staleness_sec, unrealized_pnl, current_price, position_id))
                print(f"[LEDGER] ✓ Initial mark price set: ${current_price:.2f} for position {position_id}")
            else:
                conn.execute("""
                    UPDATE position_ledger SET
                        current_price = ?,
                        price_updated_at = ?,
                        price_staleness_sec = ?,
                        unrealized_pnl = ?
                    WHERE id = ?
                """, (current_price, now, staleness_sec, unrealized_pnl, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_trailing_state(
        self,
        position_id: int,
        trailing_active: bool,
        max_pnl_seen: float
    ):
        """Update trailing stop state for a position."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET
                    trailing_stop_active = ?,
                    max_pnl_seen = ?
                WHERE id = ?
            """, (1 if trailing_active else 0, max_pnl_seen, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_dynamic_sl(self, position_id: int, dynamic_sl_price: float):
        """Update dynamic stop loss price after PT hit."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET dynamic_sl_price = ?
                WHERE id = ?
            """, (dynamic_sl_price, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_giveback_guard(self, position_id: int, active: bool, max_pnl_seen: float):
        """Update giveback guard state and max P&L seen."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET
                    giveback_guard_active = ?,
                    max_pnl_seen = MAX(max_pnl_seen, ?)
                WHERE id = ?
            """, (1 if active else 0, max_pnl_seen, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_early_trailing_state(
        self, position_id: int, active: bool, 
        stop_price: Optional[float] = None, steps_locked: int = 0
    ):
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET
                    early_trailing_active = ?,
                    early_stop_price = ?,
                    early_steps_locked = ?
                WHERE id = ?
            """, (1 if active else 0, stop_price, steps_locked, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_max_pnl(self, position_id: int, max_pnl: float):
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET max_pnl_seen = MAX(max_pnl_seen, ?)
                WHERE id = ?
            """, (max_pnl, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_ema_no_trend_count(self, position_id: int, count: int):
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET ema_no_trend_count = ?
                WHERE id = ?
            """, (count, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_pt_levels(self, position_id: int, pt_levels: list):
        """Update profit target levels hit for a position."""
        import json
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET
                    pt_levels_hit = ?
                WHERE id = ?
            """, (json.dumps(pt_levels), position_id))
            conn.commit()
        finally:
            conn.close()
    
    def record_partial_exit(
        self,
        position_id: int,
        exit_qty: int,
        exit_price: float,
        exit_reason: str,
        message_id: str = "",
        dedupe_key: str = ""
    ) -> Optional[PartialExit]:
        """
        Record a partial or full exit from a position with idempotency.
        
        Uses dedupe_key to prevent duplicate exits. If dedupe_key is provided and
        an exit with same key exists, returns the existing exit instead of creating new.
        """
        conn = self._get_conn()
        try:
            # ===== IDEMPOTENCY CHECK =====
            # Check if exit with same dedupe_key already exists (prevents duplicates)
            if dedupe_key:
                existing = conn.execute(
                    "SELECT * FROM partial_exits WHERE position_id = ? AND message_id = ?",
                    (position_id, dedupe_key)
                ).fetchone()
                if existing:
                    print(f"[LEDGER] ⏭️ Duplicate exit blocked (dedupe_key: {dedupe_key[:16]}...)")
                    return PartialExit(
                        id=existing['id'],
                        position_id=existing['position_id'],
                        exit_qty=existing['exit_qty'],
                        exit_price=existing['exit_price'],
                        exit_reason=existing['exit_reason'],
                        exit_pnl_dollar=existing['exit_pnl_dollar'],
                        exit_pnl_pct=existing['exit_pnl_pct'],
                        exit_time=existing['exit_time'],
                        message_id=existing['message_id']
                    )
            # ===== END IDEMPOTENCY CHECK =====
            
            row = conn.execute(
                "SELECT * FROM position_ledger WHERE id = ?",
                (position_id,)
            ).fetchone()
            
            if not row:
                print(f"[LEDGER] Position {position_id} not found")
                return None
            
            remaining = row['remaining_qty']
            entry_price = row['entry_price']
            initial_mark = row['initial_mark_price'] if 'initial_mark_price' in row.keys() else 0.0
            
            actual_exit_qty = min(exit_qty, remaining)
            if actual_exit_qty <= 0:
                print(f"[LEDGER] No remaining quantity to exit for position {position_id}")
                return None
            
            cost_basis_price = initial_mark if (initial_mark and initial_mark > 0) else entry_price
            cost_basis = cost_basis_price * actual_exit_qty * 100
            exit_value = exit_price * actual_exit_qty * 100
            exit_pnl_dollar = exit_value - cost_basis
            exit_pnl_pct = (exit_pnl_dollar / cost_basis * 100) if cost_basis > 0 else 0.0
            
            now = datetime.now().isoformat()
            
            # Use dedupe_key as message_id for idempotency tracking
            stored_message_id = dedupe_key if dedupe_key else message_id
            
            # ===== RACE-SAFE INSERT WITH UNIQUE CONSTRAINT =====
            # If unique index violation occurs, another thread already inserted
            try:
                cursor = self._execute_with_retry(conn, """
                    INSERT INTO partial_exits (
                        position_id, exit_qty, exit_price, exit_reason,
                        exit_pnl_dollar, exit_pnl_pct, exit_time, message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position_id, actual_exit_qty, exit_price, exit_reason,
                    exit_pnl_dollar, exit_pnl_pct, now, stored_message_id
                ))
            except sqlite3.IntegrityError:
                # Race condition: another thread already inserted this exit
                print(f"[LEDGER] ⏭️ Duplicate exit blocked by unique constraint: {stored_message_id[:16] if stored_message_id else 'N/A'}...")
                return None
            # ===== END RACE-SAFE INSERT =====
            
            new_remaining = remaining - actual_exit_qty
            new_realized = (row['realized_pnl'] or 0) + exit_pnl_dollar
            new_status = "closed" if new_remaining <= 0 else "partially_closed"
            close_time = now if new_remaining <= 0 else None
            
            self._execute_with_retry(conn, """
                UPDATE position_ledger SET
                    remaining_qty = ?,
                    realized_pnl = ?,
                    status = ?,
                    last_exit_time = ?,
                    close_time = ?
                WHERE id = ?
            """, (new_remaining, new_realized, new_status, now, close_time, position_id),
                commit=True)
            
            print(f"[LEDGER] ✓ Exit recorded: {actual_exit_qty} @ ${exit_price:.2f} ({exit_reason}) "
                  f"P&L: ${exit_pnl_dollar:.2f} ({exit_pnl_pct:.1f}%)")
            
            if new_remaining <= 0:
                # Release lock with full position key including routing_mapping_id
                routing_id = row['routing_mapping_id'] if 'routing_mapping_id' in row.keys() else None
                self.exit_arbiter.release_lock(
                    row['option_key'],
                    row['broker_id'],
                    row['account_id'],
                    routing_mapping_id=routing_id
                )
            
            return PartialExit(
                id=cursor.lastrowid,
                position_id=position_id,
                exit_qty=actual_exit_qty,
                exit_price=exit_price,
                exit_reason=exit_reason,
                exit_pnl_dollar=exit_pnl_dollar,
                exit_pnl_pct=exit_pnl_pct,
                exit_time=now,
                message_id=message_id
            )
        finally:
            conn.close()
    
    def update_pt_hit(self, position_id: int, pt_level: str):
        """Record that a profit target level was hit."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT pt_levels_hit FROM position_ledger WHERE id = ?",
                (position_id,)
            ).fetchone()
            
            if not row:
                return
            
            try:
                levels = json.loads(row['pt_levels_hit'] or "[]")
            except json.JSONDecodeError:
                levels = []
            
            if pt_level not in levels:
                levels.append(pt_level)
                conn.execute(
                    "UPDATE position_ledger SET pt_levels_hit = ? WHERE id = ?",
                    (json.dumps(levels), position_id)
                )
                conn.commit()
        finally:
            conn.close()
    
    def update_max_pnl(self, position_id: int, current_pnl_pct: float):
        """Update max P&L seen for giveback guard."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE position_ledger SET max_pnl_seen = MAX(max_pnl_seen, ?)
                WHERE id = ?
            """, (current_pnl_pct, position_id))
            conn.commit()
        finally:
            conn.close()
    
    def get_position_summary(self, position_id: int) -> Dict[str, Any]:
        """Get a summary of position with all partial exits."""
        position = self.get_position(position_id)
        if not position:
            return {}
        
        total_exited_qty = sum(e.exit_qty for e in position.partial_exits)
        total_realized = sum(e.exit_pnl_dollar for e in position.partial_exits)
        
        unrealized_dollar, unrealized_pct = position.calculate_unrealized_pnl()
        total_dollar, total_pct = position.calculate_total_pnl()
        
        return {
            "position": position.to_dict(),
            "summary": {
                "entry_qty": position.entry_qty,
                "remaining_qty": position.remaining_qty,
                "total_exited_qty": total_exited_qty,
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "realized_pnl": total_realized,
                "unrealized_pnl": unrealized_dollar,
                "total_pnl_dollar": total_dollar,
                "total_pnl_pct": total_pct,
                "num_exits": len(position.partial_exits),
                "status": position.status
            }
        }
    
    def reconcile_with_broker(
        self, 
        broker_positions: List[Dict[str, Any]],
        broker_id: str
    ):
        """
        Reconcile ledger with broker positions on startup.
        Handles positions that may have been opened/closed while bot was offline.
        """
        conn = self._get_conn()
        try:
            ledger_positions = self.get_open_positions(broker_id=broker_id)
            
            broker_keys = {p.get('option_key', p.get('symbol', '')) for p in broker_positions}
            ledger_keys = {p.option_key for p in ledger_positions}
            
            orphaned = ledger_keys - broker_keys
            for key in orphaned:
                print(f"[LEDGER] ⚠️ Orphaned position (closed externally?): {key}")
            
            missing = broker_keys - ledger_keys
            for key in missing:
                print(f"[LEDGER] ⚠️ Untracked broker position: {key}")
            
            print(f"[LEDGER] Reconciliation complete: {len(ledger_positions)} ledger, "
                  f"{len(broker_positions)} broker, {len(orphaned)} orphaned, {len(missing)} missing")
        finally:
            conn.close()


_ledger_instance: Optional[PositionLedger] = None


def get_position_ledger() -> PositionLedger:
    """Get the global position ledger instance."""
    global _ledger_instance
    if _ledger_instance is None:
        _ledger_instance = PositionLedger()
    return _ledger_instance

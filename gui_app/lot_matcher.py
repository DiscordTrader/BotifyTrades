"""
FIFO Lot Matching Service
Matches BTO/STC signals and calculates PNL
"""
from datetime import datetime
from typing import Optional, Dict, List
from . import database as db


class LotMatcher:
    """FIFO lot matching for signal-based PNL tracking"""
    
    def __init__(self):
        pass
    
    def process_signal(self, signal: Dict) -> Optional[List[int]]:
        """
        Process a BTO or STC signal and update lots
        Returns list of closure IDs if STC, lot ID if BTO, None on error
        """
        if signal['action'] == 'BTO':
            return [self._create_lot(signal)]
        elif signal['action'] == 'STC':
            return self._close_lots(signal)
        return None
    
    def _create_lot(self, signal: Dict) -> int:
        """Create a new lot from BTO signal"""
        # Get channel_id (use db_channel_id if available, otherwise lookup)
        channel_id = signal.get('db_channel_id')
        
        if not channel_id:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', (str(signal.get('channel_id')),))
            channel = cursor.fetchone()
            
            if not channel:
                print(f"[LOT_MATCHER] Warning: Channel {signal.get('channel_id')} not found")
                return None
            
            channel_id = channel['id']
        
        # Create lot (with author and user attribution)
        lot_id = db.create_signal_lot(
            channel_id=channel_id,
            signal_id=signal.get('signal_id'),
            asset_type=signal['asset'],
            symbol=signal['symbol'],
            quantity=signal['qty'],
            open_price=signal['price'],
            opened_at=signal.get('received_at', datetime.now()),
            strike=signal.get('strike'),
            expiry=signal.get('expiry'),
            call_put=signal.get('opt_type'),
            author_name=signal.get('author_name'),
            user_id=signal.get('user_id')
        )
        
        print(f"[LOT_MATCHER] ✓ Created lot {lot_id} for {signal['symbol']} BTO {signal['qty']} @ ${signal['price']}")
        return lot_id
    
    def _close_lots(self, signal: Dict) -> List[int]:
        """Close lots using FIFO matching from STC signal"""
        # Get channel_id (use db_channel_id if available, otherwise lookup)
        channel_id = signal.get('db_channel_id')
        
        if not channel_id:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', (str(signal.get('channel_id')),))
            channel = cursor.fetchone()
            
            if not channel:
                print(f"[LOT_MATCHER] Warning: Channel {signal.get('channel_id')} not found")
                return []
            
            channel_id = channel['id']
        
        # Get open lots for this symbol (FIFO order)
        open_lots = db.get_open_lots(
            channel_id=channel_id,
            asset_type=signal['asset'],
            symbol=signal['symbol'],
            strike=signal.get('strike'),
            expiry=signal.get('expiry'),
            call_put=signal.get('opt_type')
        )
        
        if not open_lots:
            print(f"[LOT_MATCHER] ⚠ No open lots found for {signal['symbol']} STC")
            return []
        
        # If qty is None, close ALL open positions for this symbol
        if signal.get('qty') is None:
            total_open = sum(lot['remaining_qty'] for lot in open_lots)
            remaining_qty = total_open
            print(f"[LOT_MATCHER] STC without qty - closing all {total_open} open contracts")
        else:
            remaining_qty = signal['qty']
        
        closure_ids = []
        closed_at = signal.get('received_at', datetime.now())
        
        # Match lots FIFO
        for lot in open_lots:
            if remaining_qty <= 0:
                break
            
            close_qty = min(remaining_qty, lot['remaining_qty'])
            
            closure_id = db.close_lot(
                lot_id=lot['id'],
                channel_id=channel_id,
                signal_id=signal.get('signal_id'),
                close_qty=close_qty,
                close_price=signal['price'],
                closed_at=closed_at
            )
            
            if closure_id:
                closure_ids.append(closure_id)
                remaining_qty -= close_qty
                print(f"[LOT_MATCHER] ✓ Closed {close_qty} of lot {lot['id']} @ ${signal['price']}")
        
        if remaining_qty > 0:
            print(f"[LOT_MATCHER] ⚠ Orphaned STC: {remaining_qty} shares of {signal['symbol']} have no matching BTO")
        
        return closure_ids


# Global instance
_matcher = None

def get_matcher() -> LotMatcher:
    """Get global lot matcher instance"""
    global _matcher
    if _matcher is None:
        _matcher = LotMatcher()
    return _matcher

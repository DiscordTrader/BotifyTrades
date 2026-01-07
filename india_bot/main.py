"""
India Bot - Main Entry Point
Standalone trading bot for Indian markets (NSE/BSE/MCX)
Supports: Upstox, Zerodha, DhanQ
"""

import os
import sys
import asyncio
import threading
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, 'src'))

print("=" * 60)
print("INDIA BOT - Trading Bot for Indian Markets")
print("=" * 60)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

from gui_app import database as db
from gui_app.app import app, set_bot_instance, run_app

try:
    from src.brokers.upstox_broker import UpstoxBroker
    UPSTOX_AVAILABLE = True
except ImportError as e:
    UPSTOX_AVAILABLE = False
    print(f"[UPSTOX] Not available: {e}")

try:
    from src.brokers.zerodha_broker import ZerodhaBroker
    ZERODHA_AVAILABLE = True
except ImportError as e:
    ZERODHA_AVAILABLE = False
    print(f"[ZERODHA] Not available: {e}")

try:
    from src.brokers.dhanq_broker import DhanQBroker
    DHANQ_AVAILABLE = True
except ImportError as e:
    DHANQ_AVAILABLE = False
    print(f"[DHANQ] Not available: {e}")

try:
    from src.services.conditional_orders.india_service import IndiaConditionalOrderService
    CONDITIONAL_ORDERS_AVAILABLE = True
except ImportError as e:
    CONDITIONAL_ORDERS_AVAILABLE = False
    print(f"[CONDITIONAL] Not available: {e}")


class IndiaTradingBot:
    """Main India trading bot class"""
    
    def __init__(self):
        self.upstox_broker = None
        self.zerodha_broker = None
        self.dhanq_broker = None
        self.conditional_service = None
        self.running = False
        self.signal_queue = asyncio.Queue()
        self.event_loop = None  # Store event loop for thread-safe async calls
    
    def get_event_loop(self):
        """Get the bot's event loop for thread-safe async calls"""
        return self.event_loop
    
    async def initialize_brokers(self):
        """Initialize all Indian brokers"""
        print("\n[INIT] Initializing brokers...")
        
        if UPSTOX_AVAILABLE:
            try:
                creds = db.get_broker_credentials('upstox')
                if creds:
                    print("[UPSTOX] Connecting...")
                    self.upstox_broker = UpstoxBroker(creds)
                    connected = await self.upstox_broker.connect()
                    if connected:
                        print(f"[UPSTOX] ✓ Connected - User: {self.upstox_broker.user_id}")
                        db.update_broker_connection_status('upstox', True, f"Connected - {self.upstox_broker.user_id}")
                    else:
                        print("[UPSTOX] ❌ Connection failed")
                else:
                    print("[UPSTOX] No credentials configured")
            except Exception as e:
                print(f"[UPSTOX] Error: {e}")
        
        if ZERODHA_AVAILABLE:
            try:
                creds = db.get_broker_credentials('zerodha')
                if creds:
                    print("[ZERODHA] Connecting...")
                    self.zerodha_broker = ZerodhaBroker(creds)
                    connected = await self.zerodha_broker.connect()
                    if connected:
                        print("[ZERODHA] ✓ Connected")
                        db.update_broker_connection_status('zerodha', True, "Connected")
                    else:
                        print("[ZERODHA] ❌ Connection failed")
                else:
                    print("[ZERODHA] No credentials configured")
            except Exception as e:
                print(f"[ZERODHA] Error: {e}")
        
        if DHANQ_AVAILABLE:
            try:
                creds = db.get_broker_credentials('dhanq')
                if creds:
                    print("[DHANQ] Connecting...")
                    self.dhanq_broker = DhanQBroker(creds)
                    connected = await self.dhanq_broker.connect()
                    if connected:
                        print("[DHANQ] ✓ Connected")
                        db.update_broker_connection_status('dhanq', True, "Connected")
                    else:
                        print("[DHANQ] ❌ Connection failed")
                else:
                    print("[DHANQ] No credentials configured")
            except Exception as e:
                print(f"[DHANQ] Error: {e}")
    
    async def initialize_services(self):
        """Initialize services"""
        print("\n[INIT] Initializing services...")
        
        if CONDITIONAL_ORDERS_AVAILABLE:
            try:
                self.conditional_service = IndiaConditionalOrderService()
                if self.upstox_broker and self.upstox_broker.connected:
                    self.conditional_service.register_broker('upstox', self.upstox_broker)
                if self.zerodha_broker and self.zerodha_broker.connected:
                    self.conditional_service.register_broker('zerodha', self.zerodha_broker)
                if self.dhanq_broker and self.dhanq_broker.connected:
                    self.conditional_service.register_broker('dhanq', self.dhanq_broker)
                self.conditional_service.start()
                print("[CONDITIONAL] ✓ Service started")
            except Exception as e:
                print(f"[CONDITIONAL] Error: {e}")
    
    async def process_signal(self, signal: dict):
        """Process a trading signal"""
        print(f"[SIGNAL] Processing: {signal.get('action')} {signal.get('symbol')}")
        
        broker_name = signal.get('broker', 'upstox').lower()
        broker = None
        
        if broker_name == 'upstox' and self.upstox_broker:
            broker = self.upstox_broker
        elif broker_name == 'zerodha' and self.zerodha_broker:
            broker = self.zerodha_broker
        elif broker_name == 'dhanq' and self.dhanq_broker:
            broker = self.dhanq_broker
        
        if not broker or not broker.connected:
            print(f"[SIGNAL] ❌ Broker {broker_name} not connected")
            return
        
        try:
            lots = signal.get('lots', 1)
            if signal.get('asset', 'option') == 'option':
                # India brokers use different parameter names than US brokers
                # UpstoxBroker: action, qty, symbol, strike, opt_type, expiry_mmdd, limit_price, lots
                result = await broker.place_option_order(
                    action=signal.get('action'),
                    qty=signal.get('qty', 1),
                    symbol=signal['symbol'],
                    strike=signal.get('strike'),
                    opt_type=signal.get('opt_type'),
                    expiry_mmdd=signal.get('expiry'),
                    limit_price=signal.get('price'),
                    lots=lots
                )
            else:
                result = await broker.place_stock_order(
                    symbol=signal['symbol'],
                    action=signal.get('action'),
                    quantity=signal.get('qty', 1),
                    price=signal.get('price')
                )
            
            if result.success:
                print(f"[SIGNAL] ✓ Order placed: {result.order_id}")
                db.save_signal({**signal, 'order_id': result.order_id, 'status': 'EXECUTED'})
            else:
                print(f"[SIGNAL] ❌ Order failed: {result.message}")
                db.save_signal({**signal, 'status': 'FAILED', 'error': result.message})
        
        except Exception as e:
            print(f"[SIGNAL] Error: {e}")
            db.save_signal({**signal, 'status': 'ERROR', 'error': str(e)})
    
    async def signal_worker(self):
        """Worker to process signals from queue"""
        print("[WORKER] Signal worker started")
        while self.running:
            try:
                signal = await asyncio.wait_for(self.signal_queue.get(), timeout=1.0)
                await self.process_signal(signal)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[WORKER] Error: {e}")
    
    async def run(self):
        """Main run loop"""
        self.running = True
        self.event_loop = asyncio.get_running_loop()  # Store for thread-safe async calls
        
        await self.initialize_brokers()
        await self.initialize_services()
        
        set_bot_instance(self)
        
        web_thread = threading.Thread(target=run_app, daemon=True)
        web_thread.start()
        print("\n[INIT] ✓ Web server started on http://0.0.0.0:5000")
        
        print("\n[INIT] ✓ India Bot is ready!")
        print("=" * 60)
        
        await self.signal_worker()
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        print("[SHUTDOWN] Stopping India Bot...")


def main():
    """Main entry point"""
    bot = IndiaTradingBot()
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Received keyboard interrupt")
        bot.stop()
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()

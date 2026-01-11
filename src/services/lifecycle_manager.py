"""
BotifyTrades Lifecycle Manager
Centralized control for bot start/stop/restart operations
"""
import os
import sys
import signal
import threading
import time
from typing import Optional, Callable, Dict, Any
from enum import Enum


class BotState(Enum):
    """Bot lifecycle states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    ERROR = "error"


class BotLifecycleManager:
    """
    Centralized lifecycle manager for BotifyTrades.
    Provides unified start/stop/restart operations for both
    system tray and web GUI.
    """
    
    _instance: Optional['BotLifecycleManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._state = BotState.STOPPED
        self._state_lock = threading.Lock()
        self._discord_thread: Optional[threading.Thread] = None
        self._telegram_thread: Optional[threading.Thread] = None
        self._flask_thread: Optional[threading.Thread] = None
        self._discord_shutdown_event: Optional[threading.Event] = None
        self._telegram_shutdown_event: Optional[threading.Event] = None
        self._gui_port: int = 5000
        self._qt_app = None
        self._on_state_change_callbacks: list = []
        self._shutdown_in_progress = False
        self._progress_callbacks: list = []
    
    @property
    def state(self) -> BotState:
        with self._state_lock:
            return self._state
    
    @state.setter
    def state(self, new_state: BotState):
        with self._state_lock:
            old_state = self._state
            self._state = new_state
        if old_state != new_state:
            self._notify_state_change(new_state)
    
    def _notify_state_change(self, new_state: BotState):
        """Notify all registered callbacks of state change"""
        for callback in self._on_state_change_callbacks:
            try:
                callback(new_state)
            except Exception as e:
                print(f"[LIFECYCLE] State change callback error: {e}")
    
    def on_state_change(self, callback: Callable[[BotState], None]):
        """Register a callback for state changes"""
        self._on_state_change_callbacks.append(callback)
    
    def register_threads(self, 
                        discord_thread: Optional[threading.Thread],
                        telegram_thread: Optional[threading.Thread],
                        discord_shutdown: Optional[threading.Event],
                        telegram_shutdown: Optional[threading.Event],
                        gui_port: int = 5000):
        """Register the bot threads for lifecycle management"""
        self._discord_thread = discord_thread
        self._telegram_thread = telegram_thread
        self._discord_shutdown_event = discord_shutdown
        self._telegram_shutdown_event = telegram_shutdown
        self._gui_port = gui_port
        self.state = BotState.RUNNING
    
    def register_qt_app(self, app):
        """Register Qt application for proper shutdown"""
        self._qt_app = app
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bot status for API"""
        return {
            'state': self.state.value,
            'discord_running': self._discord_thread.is_alive() if self._discord_thread else False,
            'telegram_running': self._telegram_thread.is_alive() if self._telegram_thread else False,
            'gui_port': self._gui_port,
            'shutdown_in_progress': self._shutdown_in_progress
        }
    
    def stop(self, force: bool = False) -> bool:
        """
        Stop the bot gracefully.
        
        Args:
            force: If True, force kill after timeout
            
        Returns:
            True if stopped successfully
        """
        if self._shutdown_in_progress:
            print("[LIFECYCLE] Shutdown already in progress")
            return False
        
        self._shutdown_in_progress = True
        self.state = BotState.STOPPING
        print("[LIFECYCLE] Initiating graceful shutdown...")
        
        try:
            # Signal shutdown events
            if self._discord_shutdown_event is not None:
                print("[LIFECYCLE] Signaling Discord thread to stop...")
                self._discord_shutdown_event.set()
            else:
                print("[LIFECYCLE] No Discord shutdown event registered")
            
            if self._telegram_shutdown_event is not None:
                print("[LIFECYCLE] Signaling Telegram thread to stop...")
                self._telegram_shutdown_event.set()
            else:
                print("[LIFECYCLE] No Telegram shutdown event registered")
            
            timeout = 10 if not force else 3
            
            # Wait for threads with safety checks
            if self._discord_thread is not None:
                try:
                    if self._discord_thread.is_alive():
                        print(f"[LIFECYCLE] Waiting for Discord thread (timeout: {timeout}s)...")
                        self._discord_thread.join(timeout=timeout)
                        if self._discord_thread.is_alive():
                            print("[LIFECYCLE] Discord thread did not stop in time")
                        else:
                            print("[LIFECYCLE] Discord thread stopped")
                except Exception as e:
                    print(f"[LIFECYCLE] Error waiting for Discord thread: {e}")
            else:
                print("[LIFECYCLE] No Discord thread registered")
            
            if self._telegram_thread is not None:
                try:
                    if self._telegram_thread.is_alive():
                        print(f"[LIFECYCLE] Waiting for Telegram thread (timeout: {timeout}s)...")
                        self._telegram_thread.join(timeout=timeout)
                        if self._telegram_thread.is_alive():
                            print("[LIFECYCLE] Telegram thread did not stop in time")
                        else:
                            print("[LIFECYCLE] Telegram thread stopped")
                except Exception as e:
                    print(f"[LIFECYCLE] Error waiting for Telegram thread: {e}")
            else:
                print("[LIFECYCLE] No Telegram thread registered")
            
            self.state = BotState.STOPPED
            print("[LIFECYCLE] Bot stopped successfully")
            
            if self._qt_app:
                print("[LIFECYCLE] Quitting Qt application...")
                self._qt_app.quit()
            
            return True
            
        except Exception as e:
            print(f"[LIFECYCLE] Error during shutdown: {e}")
            import traceback
            traceback.print_exc()
            self.state = BotState.ERROR
            return False
        finally:
            self._shutdown_in_progress = False
    
    def exit(self, exit_code: int = 0):
        """
        Full exit - stop bot and terminate process.
        """
        print("[LIFECYCLE] Full exit requested...")
        self.stop(force=True)
        
        time.sleep(0.5)
        
        print(f"[LIFECYCLE] Terminating process with code {exit_code}")
        os._exit(exit_code)
    
    def _is_replit_environment(self) -> bool:
        """Check if running in Replit cloud environment"""
        return os.environ.get('REPL_ID') is not None or os.environ.get('REPLIT_DEPLOYMENT') is not None
    
    def restart(self) -> bool:
        """
        Restart the bot by launching a new process and exiting current one.
        
        For PyInstaller frozen builds, we use a delayed restart approach:
        - Create a batch/shell script that waits, then launches new instance
        - Exit immediately to release temp folder locks
        
        Returns:
            True if restart initiated (process will exit)
        """
        self.state = BotState.RESTARTING
        print("[LIFECYCLE] Initiating restart...")
        
        try:
            # In Replit environment, just exit cleanly - workflow will auto-restart
            if self._is_replit_environment():
                print("[LIFECYCLE] Replit environment detected - using clean exit (workflow will auto-restart)")
                self.stop(force=True)
                print("[LIFECYCLE] Exiting for workflow restart...")
                time.sleep(0.5)
                os._exit(0)
                return True
            
            # For local/packaged environments, spawn new process
            self.stop(force=True)
            
            print("[LIFECYCLE] Launching new instance...")
            
            import subprocess
            import tempfile
            
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller frozen executable - restart the exe itself
                exe_path = sys.executable
                print(f"[LIFECYCLE] Frozen build - restarting: {exe_path}")
                
                if sys.platform == 'win32':
                    # Windows: Create a batch script that waits then launches
                    # This ensures the old process fully exits before new one starts
                    # which prevents temp folder conflicts
                    batch_content = f'''@echo off
timeout /t 2 /nobreak >nul
start "" "{exe_path}"
del "%~f0"
'''
                    # Write batch file to user's temp directory (not PyInstaller's temp)
                    batch_path = os.path.join(tempfile.gettempdir(), f"botify_restart_{os.getpid()}.bat")
                    with open(batch_path, 'w') as f:
                        f.write(batch_content)
                    
                    print(f"[LIFECYCLE] Created restart script: {batch_path}")
                    
                    # Launch batch script with hidden window, fully detached
                    CREATE_NO_WINDOW = 0x08000000
                    DETACHED_PROCESS = 0x00000008
                    subprocess.Popen(
                        ['cmd', '/c', batch_path],
                        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                        close_fds=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print("[LIFECYCLE] Restart script launched, exiting immediately...")
                    
                elif sys.platform == 'darwin':
                    # macOS: use open command for app bundles or direct exec with delay
                    if '.app' in exe_path:
                        app_path = exe_path.split('.app')[0] + '.app'
                        # Use shell script with delay
                        subprocess.Popen(
                            ['bash', '-c', f'sleep 2 && open -n "{app_path}"'],
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    else:
                        subprocess.Popen(
                            ['bash', '-c', f'sleep 2 && "{exe_path}"'],
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                else:
                    # Linux: Use bash with delay
                    subprocess.Popen(
                        ['bash', '-c', f'sleep 2 && "{exe_path}"'],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
            else:
                # Development mode - restart with python (direct is fine here)
                python_exe = sys.executable
                script = os.path.abspath(sys.argv[0])
                print(f"[LIFECYCLE] Dev mode - restarting: {python_exe} {script}")
                subprocess.Popen([python_exe, script] + sys.argv[1:],
                               start_new_session=True,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               cwd=os.path.dirname(script) or '.')
                time.sleep(1)
            
            print("[LIFECYCLE] Exiting current process for restart...")
            os._exit(0)
            
        except Exception as e:
            print(f"[LIFECYCLE] Restart failed: {e}")
            import traceback
            traceback.print_exc()
            self.state = BotState.ERROR
            return False
        
        return True


_lifecycle_manager: Optional[BotLifecycleManager] = None


def get_lifecycle_manager() -> BotLifecycleManager:
    """Get the global lifecycle manager instance"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = BotLifecycleManager()
    return _lifecycle_manager

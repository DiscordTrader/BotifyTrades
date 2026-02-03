"""
Thread Manager - Thread and async coordination for bot components
Manages the Discord bot thread, Flask web server, and background workers
"""

import threading
import asyncio
from typing import Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor

_discord_thread: Optional[threading.Thread] = None
_discord_loop: Optional[asyncio.AbstractEventLoop] = None
_flask_thread: Optional[threading.Thread] = None
_executor: Optional[ThreadPoolExecutor] = None


def get_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    """
    Get or create the shared thread pool executor.
    
    Args:
        max_workers: Maximum number of worker threads
        
    Returns:
        ThreadPoolExecutor instance
    """
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max_workers)
    return _executor


def start_discord_thread(target: Callable, daemon: bool = True, name: str = "DiscordBot") -> threading.Thread:
    """
    Start the Discord bot in a separate thread.
    
    Args:
        target: Function to run in the thread
        daemon: Whether to run as daemon thread
        name: Thread name for identification
        
    Returns:
        The started thread
    """
    global _discord_thread
    
    _discord_thread = threading.Thread(target=target, daemon=daemon, name=name)
    _discord_thread.start()
    
    print(f"[THREAD] Started {name} thread (daemon={daemon})")
    return _discord_thread


def start_flask_thread(target: Callable, daemon: bool = True, name: str = "FlaskWeb") -> threading.Thread:
    """
    Start the Flask web server in a separate thread.
    
    Args:
        target: Function to run in the thread
        daemon: Whether to run as daemon thread
        name: Thread name for identification
        
    Returns:
        The started thread
    """
    global _flask_thread
    
    _flask_thread = threading.Thread(target=target, daemon=daemon, name=name)
    _flask_thread.start()
    
    print(f"[THREAD] Started {name} thread (daemon={daemon})")
    return _flask_thread


def set_discord_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Store the Discord bot's event loop for cross-thread scheduling."""
    global _discord_loop
    _discord_loop = loop


def get_discord_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Get the Discord bot's event loop."""
    return _discord_loop


def schedule_in_discord_loop(coro: Any) -> None:
    """
    Schedule a coroutine to run in the Discord event loop from another thread.
    
    Args:
        coro: Coroutine to schedule
    """
    loop = get_discord_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        print("[THREAD] Warning: Discord loop not available for scheduling")


def is_discord_thread_alive() -> bool:
    """Check if the Discord bot thread is still running."""
    return _discord_thread is not None and _discord_thread.is_alive()


def is_flask_thread_alive() -> bool:
    """Check if the Flask web server thread is still running."""
    return _flask_thread is not None and _flask_thread.is_alive()


def wait_for_discord_thread(timeout: Optional[float] = None) -> None:
    """Wait for the Discord bot thread to complete."""
    if _discord_thread is not None:
        _discord_thread.join(timeout)


def wait_for_flask_thread(timeout: Optional[float] = None) -> None:
    """Wait for the Flask web server thread to complete."""
    if _flask_thread is not None:
        _flask_thread.join(timeout)


def shutdown_executor(wait: bool = True) -> None:
    """Shutdown the thread pool executor."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
        print("[THREAD] Executor shutdown complete")


def create_isolated_event_loop() -> asyncio.AbstractEventLoop:
    """
    Create a new isolated event loop for a thread.
    This is used when running async code in a separate thread.
    
    Returns:
        New event loop
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


class ThreadSafeCounter:
    """Thread-safe counter for tracking concurrent operations."""
    
    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock = threading.Lock()
    
    def increment(self) -> int:
        with self._lock:
            self._value += 1
            return self._value
    
    def decrement(self) -> int:
        with self._lock:
            self._value -= 1
            return self._value
    
    @property
    def value(self) -> int:
        with self._lock:
            return self._value


class ThreadSafeFlag:
    """Thread-safe boolean flag."""
    
    def __init__(self, initial: bool = False):
        self._value = initial
        self._lock = threading.Lock()
    
    def set(self) -> None:
        with self._lock:
            self._value = True
    
    def clear(self) -> None:
        with self._lock:
            self._value = False
    
    def is_set(self) -> bool:
        with self._lock:
            return self._value


def shutdown_executor(wait: bool = False) -> None:
    """
    Shutdown the thread pool executor gracefully.
    
    Args:
        wait: Whether to wait for pending tasks to complete
    """
    global _executor
    if _executor is not None:
        try:
            _executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:
            # Python < 3.9 doesn't support cancel_futures
            _executor.shutdown(wait=wait)
        except Exception:
            pass
        _executor = None


def cleanup_all_threads() -> None:
    """
    Clean up all managed threads and resources.
    Call this during application shutdown to prevent segfaults on macOS.
    """
    global _discord_thread, _flask_thread, _discord_loop
    
    # Shutdown executor first
    shutdown_executor(wait=False)
    
    # Clear loop reference
    _discord_loop = None
    
    # Note: daemon threads will be terminated when main thread exits
    # We just clear the references to allow garbage collection
    _discord_thread = None
    _flask_thread = None

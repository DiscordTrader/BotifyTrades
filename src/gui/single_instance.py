"""
Single Instance Detection
Prevents multiple instances of BotifyTrades from running simultaneously.
Uses Windows mutex on Windows and file lock on other platforms.
"""
import sys
import os
import atexit

_lock_handle = None
_lock_file = None

def check_single_instance(app_name: str = "BotifyTrades") -> bool:
    """
    Check if another instance is already running.
    
    Returns:
        True if this is the only instance (safe to proceed)
        False if another instance is already running
    """
    global _lock_handle, _lock_file
    
    if sys.platform == 'win32':
        return _check_windows_mutex(app_name)
    else:
        return _check_file_lock(app_name)


def _check_windows_mutex(app_name: str) -> bool:
    """Windows: Use named mutex for single instance detection"""
    global _lock_handle
    
    try:
        import ctypes
        from ctypes import wintypes
        
        kernel32 = ctypes.windll.kernel32
        
        mutex_name = f"Global\\{app_name}_SingleInstance_Mutex_V2"
        
        ERROR_ALREADY_EXISTS = 183
        
        kernel32.SetLastError(0)
        
        _lock_handle = kernel32.CreateMutexW(
            None,
            ctypes.c_bool(True),
            ctypes.c_wchar_p(mutex_name)
        )
        
        last_error = kernel32.GetLastError()
        
        if _lock_handle is None or _lock_handle == 0:
            print(f"[SINGLE INSTANCE] Failed to create mutex (error: {last_error})")
            return False
        
        if last_error == ERROR_ALREADY_EXISTS:
            print(f"[SINGLE INSTANCE] ⚠️ Another instance is already running!")
            kernel32.CloseHandle(_lock_handle)
            _lock_handle = None
            return False
        
        print(f"[SINGLE INSTANCE] ✓ Mutex acquired - single instance verified")
        atexit.register(_cleanup_windows_mutex)
        return True
        
    except Exception as e:
        print(f"[SINGLE INSTANCE] Windows mutex check failed: {e}")
        return False


def _check_file_lock(app_name: str) -> bool:
    """Unix/Linux: Use file lock for single instance detection"""
    global _lock_file
    
    try:
        import fcntl
        
        lock_path = os.path.join(os.path.expanduser("~"), f".{app_name.lower()}.lock")
        
        _lock_file = open(lock_path, 'w')
        
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_file.write(str(os.getpid()))
            _lock_file.flush()
            atexit.register(_cleanup_file_lock)
            return True
        except (IOError, OSError):
            _lock_file.close()
            _lock_file = None
            return False
            
    except ImportError:
        return True
    except Exception as e:
        print(f"[SINGLE INSTANCE] File lock check failed: {e}")
        return True


def _cleanup_windows_mutex():
    """Release Windows mutex on exit"""
    global _lock_handle
    if _lock_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(_lock_handle)
            ctypes.windll.kernel32.CloseHandle(_lock_handle)
        except:
            pass
        _lock_handle = None


def _cleanup_file_lock():
    """Release file lock on exit"""
    global _lock_file
    if _lock_file:
        try:
            import fcntl
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
            _lock_file.close()
        except:
            pass
        _lock_file = None


def show_already_running_dialog():
    """Show a dialog indicating another instance is running"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon
        
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        msg = QMessageBox()
        msg.setWindowTitle("BotifyTrades")
        msg.setIcon(QMessageBox.Warning)
        msg.setText("Another instance is already running")
        msg.setInformativeText(
            "BotifyTrades is already running in the background.\n\n"
            "Please check your system tray or task manager.\n"
            "Only one instance can run at a time."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
        
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1a1a2e;
                color: #ffffff;
            }
            QMessageBox QLabel {
                color: #ffffff;
                font-size: 12px;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4facfe, stop:1 #00f2fe);
                color: #1a1a2e;
                border: none;
                padding: 8px 24px;
                border-radius: 6px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00f2fe, stop:1 #4facfe);
            }
        """)
        
        msg.exec()
        
    except Exception as e:
        print(f"[SINGLE INSTANCE] Could not show dialog: {e}")
        print("Another instance of BotifyTrades is already running.")

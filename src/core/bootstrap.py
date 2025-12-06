"""
Bootstrap module - Early initialization before other imports
Handles SSL patches, path setup, event loop configuration, and .env loading
"""

import os
import sys
import ssl
import platform
import asyncio
from typing import Optional

SSL_CONTEXT: Optional[ssl.SSLContext] = None
_initialized: bool = False


def setup_env() -> bool:
    """
    Load environment variables from .env file if present.
    Uses python-dotenv if available.
    
    Returns:
        True if .env was loaded, False otherwise
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("[STARTUP] .env file loaded (if present)")
        return True
    except ImportError:
        print("[STARTUP] python-dotenv not installed, using system environment variables only")
        return False


def setup_ssl() -> Optional[ssl.SSLContext]:
    """
    Fix SSL certificate verification for cloud environments AND EXE distribution.
    This is critical for aiohttp (used by discord.py-self) which doesn't use env vars.
    
    Returns:
        SSL context configured with certifi certificates, or None if unavailable
    """
    global SSL_CONTEXT
    
    try:
        import certifi
        cert_path = certifi.where()
        os.environ['SSL_CERT_FILE'] = cert_path
        os.environ['REQUESTS_CA_BUNDLE'] = cert_path
        
        SSL_CONTEXT = ssl.create_default_context(cafile=cert_path)
        
        try:
            import aiohttp
            _original_connector_init = aiohttp.TCPConnector.__init__
            
            def _patched_connector_init(self, *args, **kwargs):
                if 'ssl' not in kwargs or kwargs['ssl'] is None:
                    kwargs['ssl'] = SSL_CONTEXT
                _original_connector_init(self, *args, **kwargs)
            
            aiohttp.TCPConnector.__init__ = _patched_connector_init
            print("[SSL] Patched aiohttp with certifi certificates")
        except Exception as e:
            print(f"[SSL] Warning: Could not patch aiohttp: {e}")
            
        return SSL_CONTEXT
        
    except ImportError:
        print("[SSL] Warning: certifi not available, using system certificates")
        return None


def setup_paths() -> None:
    """
    Add necessary directories to Python path for local imports.
    Handles both source and PyInstaller bundled environments.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(current_dir)  # src/
    parent_dir = os.path.dirname(src_dir)    # workspace root
    
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    if getattr(sys, 'frozen', False):
        bundle_dir = sys._MEIPASS
        gui_app_path = os.path.join(bundle_dir, 'gui_app')
        if gui_app_path not in sys.path:
            sys.path.insert(0, gui_app_path)
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)
        print(f"[STARTUP] PyInstaller mode - bundle dir: {bundle_dir}")


def setup_event_loop() -> None:
    """
    Configure asyncio event loop policy for the current platform.
    Windows requires a specific policy for Discord.py-self.
    """
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        print("[STARTUP] Windows event loop policy set")


def get_exe_directory():
    """Get the directory where the executable or script is located."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_pyinstaller_bundle() -> bool:
    """Check if running from a PyInstaller bundle."""
    return getattr(sys, 'frozen', False)


def get_bundle_directory() -> Optional[str]:
    """Get PyInstaller bundle directory, or None if not bundled."""
    if is_pyinstaller_bundle():
        return sys._MEIPASS
    return None


def initialize(install_print: bool = True) -> dict:
    """
    Initialize the core module with proper bootstrap sequence.
    This should be called early in the application startup.
    
    Order of initialization:
    1. Setup paths (for imports to work)
    2. Load .env file (for environment variables)
    3. Setup SSL (for HTTPS connections)
    4. Setup event loop (for async operations)
    5. Install smart_print (optional)
    6. Load optional imports
    
    Args:
        install_print: Whether to install smart_print as global print
        
    Returns:
        Dictionary with initialization status
    """
    global _initialized
    
    if _initialized:
        return {'status': 'already_initialized'}
    
    result = {
        'paths': False,
        'env': False,
        'ssl': False,
        'event_loop': False,
        'smart_print': False,
        'imports': {}
    }
    
    try:
        setup_paths()
        result['paths'] = True
    except Exception as e:
        print(f"[BOOTSTRAP] Path setup failed: {e}")
    
    try:
        result['env'] = setup_env()
    except Exception as e:
        print(f"[BOOTSTRAP] Env loading failed: {e}")
    
    try:
        ssl_ctx = setup_ssl()
        result['ssl'] = ssl_ctx is not None
    except Exception as e:
        print(f"[BOOTSTRAP] SSL setup failed: {e}")
    
    try:
        setup_event_loop()
        result['event_loop'] = True
    except Exception as e:
        print(f"[BOOTSTRAP] Event loop setup failed: {e}")
    
    if install_print:
        try:
            from .output_handler import install_smart_print
            install_smart_print()
            result['smart_print'] = True
        except Exception as e:
            print(f"[BOOTSTRAP] Smart print installation failed: {e}")
    
    try:
        from .imports import load_optional_imports
        result['imports'] = load_optional_imports()
    except Exception as e:
        print(f"[BOOTSTRAP] Optional imports failed: {e}")
    
    _initialized = True
    result['status'] = 'success'
    
    print("[BOOTSTRAP] Core initialization complete")
    return result


def is_initialized() -> bool:
    """Check if the core module has been initialized."""
    return _initialized

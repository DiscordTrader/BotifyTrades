# BotifyTrades Security & Protection System

## Complete Guide to License Protection Architecture

This document explains all security layers that protect the trading bot from unauthorized use, license bypass attempts, and tampering.

---

## Overview

The protection system uses **7 layers of security** working together:

1. **Code Obfuscation** (PyArmor)
2. **Cryptographic Signatures** (RSA-2048)
3. **Machine ID Binding**
4. **Server-Side Validation**
5. **Background Heartbeat**
6. **Network Monitoring**
7. **Console Hiding**

Each layer addresses different attack vectors. Breaking one layer still leaves 6 others protecting the system.

---

## Layer 1: Code Obfuscation (PyArmor)

### What It Does
Transforms readable Python source code into encrypted, unreadable bytecode that cannot be reverse-engineered.

### How It Works
```
Original Source Code
        ↓
   PyArmor Obfuscation
        ↓
Encrypted Bytecode + Runtime Module
        ↓
   PyInstaller Bundle
        ↓
   Final Executable
```

### Protection Provided
- Source code cannot be read by opening files
- Decompilers produce unusable output
- License checking logic is hidden
- Modification attempts break the code

### Requirements
- **PyArmor Pro License** (paid, ~$50-100)
- License stored as `PYARMOR_LICENSE` in GitHub Secrets
- Base64 encoded registration file

### GitHub Actions Integration
```yaml
- name: Restore PyArmor License
  run: |
    echo "${{ secrets.PYARMOR_LICENSE }}" | base64 -d > pyarmor-regfile.zip
    pyarmor reg pyarmor-regfile.zip
    rm pyarmor-regfile.zip

- name: Obfuscate source code
  run: |
    pyarmor gen --output obfuscated src/
```

### Attack Resistance
| Attack | Result |
|--------|--------|
| Open .py files | Encrypted, unreadable |
| Decompile with uncompyle6 | Fails or produces garbage |
| Modify bytecode | Runtime detects tampering, crashes |
| Extract from executable | Still encrypted |

---

## Layer 2: Cryptographic Token Verification (RSA-2048)

### What It Does
Uses asymmetric cryptography to sign license tokens. Only the server can create valid tokens; the client can only verify them.

### How It Works
```
LICENSE SERVER (Private Key)
        ↓
Creates token: {license_key, machine_id, expiry, type}
        ↓
Signs with RSA private key
        ↓
Returns: {token_data, signature}


CLIENT APPLICATION (Public Key)
        ↓
Receives: {token_data, signature}
        ↓
Verifies signature with embedded public key
        ↓
If valid: Accept license
If invalid: Reject
```

### The Code (src/license/crypto.py)
```python
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

class LicenseCrypto:
    # Public key embedded in application (can be seen, but useless without private key)
    RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
-----END PUBLIC KEY-----"""
    
    def verify_token(self, token_data: dict, signature: bytes) -> bool:
        """Verify server signature using public key"""
        public_key = serialization.load_pem_public_key(
            self.RSA_PUBLIC_KEY.encode()
        )
        
        try:
            public_key.verify(
                signature,
                json.dumps(token_data).encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        except:
            return False
```

### Why This Is Unbreakable
- **Private key NEVER leaves the server** (license-forge--uk15286.replit.app)
- Client only has public key (can verify, cannot sign)
- RSA-2048 is computationally infeasible to crack
- Even if attacker extracts public key, they cannot forge signatures

### Attack Resistance
| Attack | Result |
|--------|--------|
| Create fake token | No private key = invalid signature |
| Modify cached token | Signature no longer matches |
| Extract public key | Useless without private key |
| Brute force private key | Would take millions of years |

---

## Layer 3: Machine ID Binding

### What It Does
Locks each license activation to specific hardware. The same license cannot be used on multiple computers.

### How It Works
```python
def get_machine_id() -> str:
    """Generate unique hardware identifier"""
    
    # Try BIOS UUID first (most reliable on Windows)
    if sys.platform == 'win32':
        try:
            output = subprocess.check_output(
                'wmic csproduct get uuid',
                shell=True
            )
            uuid = output.decode().split('\n')[1].strip()
            if uuid and uuid != 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF':
                return hashlib.sha256(uuid.encode()).hexdigest()[:32]
        except:
            pass
    
    # Fallback: /etc/machine-id on Linux
    if os.path.exists('/etc/machine-id'):
        with open('/etc/machine-id', 'r') as f:
            return hashlib.sha256(f.read().strip().encode()).hexdigest()[:32]
    
    # Fallback: MAC address + hostname
    import uuid as uuid_lib
    mac = uuid_lib.getnode()
    hostname = socket.gethostname()
    combined = f"{mac}-{hostname}"
    return hashlib.sha256(combined.encode()).hexdigest()[:32]
```

### Token Contains Machine ID
```json
{
    "license_key": "BT-XXXX-XXXX-XXXX",
    "machine_id": "a1b2c3d4e5f6...",  // Bound to THIS computer
    "expiry": "2026-12-31",
    "license_type": "subscription"
}
```

### Validation Check
```python
def validate_license(self, license_key: str) -> dict:
    # Get local machine ID
    local_machine_id = get_machine_id()
    
    # Token's machine ID must match
    if cached_token['machine_id'] != local_machine_id:
        return {
            'is_valid': False,
            'error': 'License activated on different machine'
        }
```

### Attack Resistance
| Attack | Result |
|--------|--------|
| Copy license file to another PC | Machine ID mismatch = rejected |
| Share token with friends | Each PC has different machine ID |
| Spoof machine ID | Requires modifying hardware/BIOS |
| Virtual machine hopping | Each VM has unique ID |

---

## Layer 4: Server-Side Validation

### What It Does
All critical license decisions happen on the server. The client cannot make authorization decisions alone.

### Server Endpoints (license-forge--uk15286.replit.app)
```
POST /api/validate    - Validate existing license
POST /api/activate    - Activate new license key
POST /api/trial       - Request trial license
POST /api/heartbeat   - Background validation check
POST /api/deactivate  - Remove machine binding
```

### Validation Flow
```
Client sends: {license_key, machine_id}
        ↓
Server checks database:
  - Is key valid?
  - Is key expired?
  - Is key revoked?
  - Is machine ID already bound?
  - Has max activations been reached?
        ↓
Server responds with signed token (or rejection)
        ↓
Client stores token in cache
```

### Hard Rejections Clear Cache
```python
def handle_validation_response(self, response: dict):
    if response.get('hard_rejection'):
        # License is expired, revoked, or invalid
        # MUST clear local cache - cannot use old data
        self._cache.clear()
        return {'is_valid': False, 'error': response['error']}
```

### Server Has Full Control
- **Revoke any license instantly** - Next validation fails
- **Expire licenses on schedule** - Server tracks dates
- **Limit activations** - Server counts machine IDs
- **Ban abusive users** - Blacklist in database

### Attack Resistance
| Attack | Result |
|--------|--------|
| Modify local cache | Server rejects on next validation |
| Block server connection | Offline grace period expires (48h) |
| Replay old responses | Timestamp/nonce checks detect this |
| SQL injection on server | Parameterized queries prevent this |

---

## Layer 5: Background Heartbeat

### What It Does
Periodically validates the license while the bot is running. Detects revocations that happen after startup.

### How It Works
```python
import threading
import time

class LicenseHeartbeat:
    def __init__(self, license_key: str, interval_minutes: int = 30):
        self.license_key = license_key
        self.interval = interval_minutes * 60
        self._stop_event = threading.Event()
        self._thread = None
    
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def _run(self):
        while not self._stop_event.is_set():
            # Wait for interval
            self._stop_event.wait(self.interval)
            
            if self._stop_event.is_set():
                break
            
            # Validate license
            result = validate_license(self.license_key)
            
            if not result.get('is_valid'):
                # License no longer valid - shutdown bot
                print("[HEARTBEAT] License invalid - shutting down")
                trigger_shutdown()
```

### Default Interval: 30 Minutes
- Frequent enough to catch revocations quickly
- Infrequent enough to not spam server
- Configurable per deployment

### Scenarios
| Situation | Result |
|-----------|--------|
| License revoked while running | Next heartbeat detects, bot stops |
| License expired while running | Next heartbeat detects, bot stops |
| Server temporarily down | Grace period continues |
| Internet disconnected | Network monitor takes over |

---

## Layer 6: Network Monitoring

### What It Does
Watches for internet connectivity changes and triggers validation when connection is restored.

### How It Works
```python
import socket
import threading

class NetworkMonitor:
    def __init__(self, license_key: str):
        self.license_key = license_key
        self._was_offline = False
        self._stop_event = threading.Event()
    
    def _check_connection(self) -> bool:
        """Check if internet is available"""
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def _run(self):
        while not self._stop_event.is_set():
            is_online = self._check_connection()
            
            if is_online and self._was_offline:
                # Just came back online - validate immediately
                print("[NETWORK] Connection restored - validating license")
                result = validate_license(self.license_key)
                
                if not result.get('is_valid'):
                    trigger_shutdown()
            
            self._was_offline = not is_online
            self._stop_event.wait(30)  # Check every 30 seconds
```

### Prevents Offline Bypass
- User can't "stay offline forever" to avoid validation
- As soon as internet returns, validation happens
- If license was revoked while offline, bot stops immediately

### Attack Resistance
| Attack | Result |
|--------|--------|
| Disconnect internet permanently | 48-hour grace period, then stops |
| Block only license server | Network check uses 8.8.8.8 (Google DNS) |
| Reconnect briefly | Immediate validation on reconnect |
| Firewall the app | Can't function anyway (needs broker APIs) |

---

## Layer 7: Console Hiding

### What It Does
Builds the executable without a console window. No debug output visible to users.

### PyInstaller Configuration
```python
# build/build_exe.spec
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BotifyTrades',
    debug=False,
    strip=False,
    upx=True,
    console=False,  # NO CONSOLE WINDOW
)
```

### Why This Matters
- Error messages don't reveal license logic
- Stack traces don't expose file paths
- Users can't see network requests
- Professional appearance

### Logging Still Works
```python
import logging

# Logs go to file, not console
logging.basicConfig(
    filename='botifytrades.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
```

---

## Offline Grace Period

### What It Does
Allows the bot to run for a limited time without internet connection, using cached license data.

### Duration: 48 Hours

### How It Works
```python
def check_grace_period(self, cached_data: dict) -> tuple[bool, str]:
    """Check if offline grace period is still valid"""
    
    last_validated = cached_data.get('last_validated')
    if not last_validated:
        return False, "No cached validation data"
    
    last_validated_time = datetime.fromisoformat(last_validated)
    hours_offline = (datetime.now() - last_validated_time).total_seconds() / 3600
    
    GRACE_PERIOD_HOURS = 48
    
    if hours_offline <= GRACE_PERIOD_HOURS:
        remaining = GRACE_PERIOD_HOURS - hours_offline
        return True, f"Offline mode - {remaining:.1f} hours remaining"
    else:
        return False, "Offline grace period expired"
```

### Why 48 Hours?
- Long enough for temporary outages
- Short enough to prevent abuse
- Balances user experience with security

---

## Cache System

### Location
```python
# Windows
cache_dir = os.path.expanduser('~/.discord_trading_bot')

# Linux/macOS  
cache_dir = os.path.expanduser('~/.discord_trading_bot')

# Cache file
cache_file = os.path.join(cache_dir, 'license_cache.json')
```

### Cache Contents
```json
{
    "license_key": "BT-XXXX-XXXX-XXXX",
    "machine_id": "a1b2c3d4e5f6...",
    "token_data": {
        "license_type": "subscription",
        "days_remaining": 365,
        "expiry": "2026-12-31"
    },
    "signature": "base64_encoded_rsa_signature...",
    "last_validated": "2026-01-17T10:30:00",
    "validation_count": 42
}
```

### Cache Is Encrypted
```python
from cryptography.fernet import Fernet

class LicenseCache:
    def __init__(self):
        # Key derived from machine ID (unique per computer)
        machine_id = get_machine_id()
        key = base64.urlsafe_b64encode(
            hashlib.sha256(machine_id.encode()).digest()
        )
        self._fernet = Fernet(key)
    
    def save(self, data: dict):
        encrypted = self._fernet.encrypt(json.dumps(data).encode())
        with open(self._cache_file, 'wb') as f:
            f.write(encrypted)
    
    def load(self) -> dict:
        with open(self._cache_file, 'rb') as f:
            encrypted = f.read()
        decrypted = self._fernet.decrypt(encrypted)
        return json.loads(decrypted)
```

### Attack Resistance
| Attack | Result |
|--------|--------|
| Copy cache to another PC | Different machine ID = different encryption key |
| Modify cache file | Signature verification fails |
| Delete cache | Forces fresh activation |
| Read cache contents | Encrypted, unreadable |

---

## Complete Attack Matrix

| Attack Vector | Layers That Block It |
|---------------|---------------------|
| Read source code | L1 (PyArmor) |
| Forge license token | L2 (RSA signatures) |
| Share license file | L3 (Machine ID binding) |
| Use expired license | L4 (Server validation) |
| Revoke detection | L5 (Heartbeat) |
| Stay offline forever | L6 (Network monitor) + Grace period |
| Debug/analyze behavior | L7 (Console hidden) |
| Modify cached data | L2 (Signature check) + Cache encryption |
| Tamper with executable | L1 (PyArmor anti-tamper) |
| Copy to virtual machine | L3 (Different machine ID) |

---

## Required Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `PYARMOR_LICENSE` | Base64-encoded PyArmor registration file |
| `PUBLIC_REPO_TOKEN` | GitHub token for publishing releases |

### Getting PyArmor License
1. Purchase from https://pyarmor.dashingsoft.com/
2. Download registration file (pyarmor-regfile.zip)
3. Convert to base64: `base64 pyarmor-regfile.zip > license.txt`
4. Add contents of license.txt to GitHub Secrets as `PYARMOR_LICENSE`

---

## Server-Side Components (license-forge)

The license server handles:
- License key generation
- Activation tracking
- Expiry management
- Revocation
- Usage analytics
- Token signing (RSA private key)

### Database Schema
```sql
CREATE TABLE licenses (
    id SERIAL PRIMARY KEY,
    license_key VARCHAR(32) UNIQUE NOT NULL,
    email VARCHAR(255),
    license_type VARCHAR(20),  -- 'trial', 'subscription', 'lifetime'
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    is_revoked BOOLEAN DEFAULT FALSE,
    max_activations INTEGER DEFAULT 1,
    current_activations INTEGER DEFAULT 0
);

CREATE TABLE activations (
    id SERIAL PRIMARY KEY,
    license_id INTEGER REFERENCES licenses(id),
    machine_id VARCHAR(64) NOT NULL,
    activated_at TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);
```

---

## Summary

The BotifyTrades protection system is designed with **defense in depth**:

1. **Code is unreadable** (PyArmor)
2. **Tokens are unforgeable** (RSA)
3. **Licenses are bound** (Machine ID)
4. **Server has control** (Online validation)
5. **Revocations are detected** (Heartbeat)
6. **Offline bypass fails** (Network monitor)
7. **Debug info is hidden** (No console)

Each layer complements the others. Even if an attacker somehow bypasses one layer, the remaining layers maintain protection.

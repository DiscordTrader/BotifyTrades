import threading
import time

_instance = None
_instance_lock = threading.Lock()


def get_exit_lease_manager():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExitLeaseManager()
    return _instance


LEASE_IDLE = 'idle'
LEASE_QUEUED = 'queued'
LEASE_EXECUTING = 'executing'

OWNER_RISK_ENGINE = 'risk_engine'
OWNER_WORKER = 'worker'
OWNER_CHASER = 'chaser'
OWNER_BACKUP = 'backup_thread'

LEASE_EXPIRY_SECONDS = 180


class _LeaseEntry:
    __slots__ = ('state', 'owner', 'acquired_at', 'tier')

    def __init__(self, state, owner, tier=None):
        self.state = state
        self.owner = owner
        self.acquired_at = time.monotonic()
        self.tier = tier


class ExitLeaseManager:

    def __init__(self):
        self._lock = threading.Lock()
        self._leases = {}

    def acquire(self, pos_key, owner, tier=None):
        with self._lock:
            existing = self._leases.get(pos_key)
            if existing is not None:
                age = time.monotonic() - existing.acquired_at
                if age >= LEASE_EXPIRY_SECONDS:
                    print(f"[EXIT-LEASE] ⏰ Expired lease for {pos_key} (owner={existing.owner}, age={age:.0f}s) — releasing")
                else:
                    return False
            self._leases[pos_key] = _LeaseEntry(LEASE_QUEUED, owner, tier=tier)
            return True

    def transfer(self, pos_key, new_owner, new_state=None, expected_owner=None):
        with self._lock:
            entry = self._leases.get(pos_key)
            if entry is None:
                self._leases[pos_key] = _LeaseEntry(new_state or LEASE_EXECUTING, new_owner)
                return True
            if expected_owner is not None and entry.owner != expected_owner:
                return False
            age = time.monotonic() - entry.acquired_at
            if age >= LEASE_EXPIRY_SECONDS:
                self._leases[pos_key] = _LeaseEntry(new_state or LEASE_EXECUTING, new_owner)
                return True
            entry.owner = new_owner
            if new_state:
                entry.state = new_state
            entry.acquired_at = time.monotonic()
            return True

    def release(self, pos_key, owner=None):
        with self._lock:
            entry = self._leases.get(pos_key)
            if entry is None:
                return True
            if owner and entry.owner != owner:
                return False
            del self._leases[pos_key]
            return True

    def force_release(self, pos_key):
        with self._lock:
            self._leases.pop(pos_key, None)

    def is_active(self, pos_key):
        with self._lock:
            entry = self._leases.get(pos_key)
            if entry is None:
                return False
            age = time.monotonic() - entry.acquired_at
            if age >= LEASE_EXPIRY_SECONDS:
                del self._leases[pos_key]
                return False
            return True

    def get_state(self, pos_key):
        with self._lock:
            entry = self._leases.get(pos_key)
            if entry is None:
                return {'state': LEASE_IDLE, 'owner': None, 'age': 0, 'tier': None}
            age = time.monotonic() - entry.acquired_at
            if age >= LEASE_EXPIRY_SECONDS:
                del self._leases[pos_key]
                return {'state': LEASE_IDLE, 'owner': None, 'age': 0, 'tier': None}
            return {
                'state': entry.state,
                'owner': entry.owner,
                'age': age,
                'tier': entry.tier,
            }

    def get_all_active(self):
        with self._lock:
            now = time.monotonic()
            result = {}
            expired = []
            for pk, entry in self._leases.items():
                age = now - entry.acquired_at
                if age >= LEASE_EXPIRY_SECONDS:
                    expired.append(pk)
                else:
                    result[pk] = {
                        'state': entry.state,
                        'owner': entry.owner,
                        'age': age,
                        'tier': entry.tier,
                    }
            for pk in expired:
                del self._leases[pk]
            return result

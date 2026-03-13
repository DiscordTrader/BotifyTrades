import socket
import threading
import os
import sys
import time
import subprocess
import signal

port = int(os.environ.get('GUI_PORT', 5000))

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

bound = False
for attempt in range(60):
    try:
        s.bind(('0.0.0.0', port))
        s.listen(1)
        print(f'[PREBIND] Port {port} ready', flush=True)
        bound = True
        break
    except OSError as e:
        print(f'[PREBIND] Port {port} busy ({e}), retry {attempt+1}/60', flush=True)
        time.sleep(1)

if not bound:
    print(f'[PREBIND] FATAL: Could not bind port {port} after 60 attempts', flush=True)
    sys.exit(1)

_stop = threading.Event()

def accept_loop():
    while not _stop.is_set():
        try:
            s.settimeout(0.5)
            conn, _ = s.accept()
            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 22\r\n\r\n<h1>Starting...</h1>')
            conn.close()
        except socket.timeout:
            continue
        except:
            break

t = threading.Thread(target=accept_loop, daemon=True)
t.start()

print('[PREBIND] Port placeholder active, starting bot subprocess...', flush=True)

_stop.set()
time.sleep(0.2)
try:
    s.close()
except:
    pass
print(f'[PREBIND] Released placeholder port {port}', flush=True)

bot_proc = subprocess.Popen(
    [sys.executable, '-u', 'src/selfbot_webull.py'],
    stdout=sys.stdout,
    stderr=sys.stderr,
    env={**os.environ, 'PYTHONUNBUFFERED': '1'}
)

import urllib.request
for i in range(30):
    time.sleep(1)
    if bot_proc.poll() is not None:
        print(f'[PREBIND] FATAL: Bot process exited with code {bot_proc.returncode}', flush=True)
        sys.exit(bot_proc.returncode or 1)
    try:
        resp = urllib.request.urlopen(f'http://127.0.0.1:{port}/readyz', timeout=2)
        if resp.status == 200:
            print(f'[PREBIND] ✓ Flask confirmed listening on port {port} after {i+1}s', flush=True)
            break
    except Exception:
        if i % 5 == 4:
            print(f'[PREBIND] Waiting for Flask... ({i+1}s)', flush=True)
else:
    print(f'[PREBIND] WARNING: Flask did not respond on port {port} after 30s', flush=True)

def forward_signal(signum, frame):
    bot_proc.send_signal(signum)

signal.signal(signal.SIGTERM, forward_signal)
signal.signal(signal.SIGINT, forward_signal)

bot_proc.wait()
sys.exit(bot_proc.returncode)

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

for attempt in range(60):
    try:
        s.bind(('0.0.0.0', port))
        s.listen(1)
        print(f'[PREBIND] Port {port} ready', flush=True)
        break
    except OSError as e:
        print(f'[PREBIND] Port {port} busy ({e}), retry {attempt+1}/60', flush=True)
        time.sleep(1)
else:
    print(f'[PREBIND] WARNING: Could not bind port {port}', flush=True)

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

bot_proc = subprocess.Popen(
    [sys.executable, '-u', 'src/selfbot_webull.py'],
    stdout=sys.stdout,
    stderr=sys.stderr,
    env={**os.environ, 'PYTHONUNBUFFERED': '1'}
)

time.sleep(5)
print('[PREBIND] Releasing placeholder port (Flask should have it now)', flush=True)
_stop.set()
time.sleep(0.3)
try:
    s.close()
except:
    pass

def forward_signal(signum, frame):
    bot_proc.send_signal(signum)

signal.signal(signal.SIGTERM, forward_signal)
signal.signal(signal.SIGINT, forward_signal)

bot_proc.wait()
sys.exit(bot_proc.returncode)

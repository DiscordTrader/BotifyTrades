#!/bin/bash
python3 -c "
import socket, threading, time, os, signal

def start_placeholder():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    port = int(os.environ.get('GUI_PORT', 5000))
    for attempt in range(30):
        try:
            s.bind(('0.0.0.0', port))
            s.listen(1)
            print(f'[PREBIND] Port {port} bound successfully', flush=True)
            break
        except OSError:
            print(f'[PREBIND] Port {port} busy, waiting... ({attempt+1}/30)', flush=True)
            time.sleep(1)
    else:
        print('[PREBIND] Could not bind port, continuing anyway', flush=True)
        return
    
    def accept_loop():
        while True:
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
    
    while True:
        time.sleep(0.5)
" &
PLACEHOLDER_PID=$!
sleep 2

exec python -u src/selfbot_webull.py

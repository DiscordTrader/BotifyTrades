import socket
import threading
import time
import sys
import os

def hold_port(sock, stop_event):
    while not stop_event.is_set():
        try:
            conn, _ = sock.accept()
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h3>Starting...</h3></body></html>")
            conn.close()
        except:
            break

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.settimeout(1.0)
sock.bind(('0.0.0.0', 5000))
sock.listen(1)

stop_event = threading.Event()
holder = threading.Thread(target=hold_port, args=(sock, stop_event), daemon=True)
holder.start()

time.sleep(2)

stop_event.set()
sock.close()
time.sleep(0.5)

os.execvp(sys.executable, [sys.executable, '-u', 'src/selfbot_webull.py'] + sys.argv[1:])

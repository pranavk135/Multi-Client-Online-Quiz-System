import socket
import threading
import time
import subprocess
import os
import sys
import ssl

# ── Build a fast test server from the original ────────────────────────────────
with open("server.py", "r") as f:
    orig = f.read()

mod = orig.replace("TIME_LIMIT = 10", "TIME_LIMIT = 2")
mod = mod.replace("time.sleep(5)", "time.sleep(1)")
mod = mod.replace("time.sleep(3)", "time.sleep(1)")

with open("test_server.py", "w") as f:
    f.write(mod)

HOST = "127.0.0.1"
PORT = 5000

outputs = {"Alice": [], "Bob": [], "Charlie": []}


def make_ssl_context():
    """Create a TLS client context that accepts self-signed certs (test only)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def run_client(name, answers):
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ctx = make_ssl_context()
        s = ctx.wrap_socket(raw, server_hostname=HOST)
        s.connect((HOST, PORT))
        s.send(name.encode())

        def listen():
            while True:
                try:
                    data = s.recv(4096).decode()
                    if not data:
                        break
                    outputs[name].append(data)
                except Exception:
                    break

        t = threading.Thread(target=listen, daemon=True)
        t.start()

        # Wait for quiz to start, then send answers one per question window
        time.sleep(1.5)
        for ans in answers:
            s.send(ans.encode())
            time.sleep(3)          # each question window is ~3 s in test mode

        time.sleep(2)              # allow final messages to arrive
        s.close()
    except Exception as e:
        print(f"Error in {name}: {e}")


if __name__ == "__main__":
    # Start test server as a subprocess
    proc = subprocess.Popen([sys.executable, "test_server.py"])
    time.sleep(1)

    # Alice answers all correctly; Bob and Charlie answer partially
    t1 = threading.Thread(target=run_client, args=("Alice",   ["Transport Layer", "Transmission Control Protocol", "SFTP", "Digital Certificate", "TCP", "443", "DNS"]))
    t2 = threading.Thread(target=run_client, args=("Bob",     ["Network Layer",   "Transfer Connect Protocol",    "FTP",  "Public Key",           "UDP", "80",  "ARP"]))
    t3 = threading.Thread(target=run_client, args=("Charlie", ["Transport Layer", "Transmission Control Protocol", "FTP", "Digital Certificate", "TCP", "443", "DHCP"]))

    t1.start(); t2.start(); t3.start()
    t1.join();  t2.join();  t3.join()

    proc.terminate()
    proc.wait()

    full_log = "".join(outputs["Alice"])

    print("=" * 50)
    if "=== QUIZ OVER ===" in full_log:
        print("TEST PASSED ✓ — Reached end of quiz.")
    else:
        print("TEST FAILED ✗ — Did not reach end of quiz.")
    print("=" * 50)
    print("Alice's Session Log:")
    print(full_log)

    # Clean up the temporary test server file
    if os.path.exists("test_server.py"):
        os.remove("test_server.py")

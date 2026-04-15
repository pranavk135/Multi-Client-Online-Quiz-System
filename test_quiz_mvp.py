import socket
import threading
import time
import subprocess
import json
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

outputs = {"Alice": [], "Bob": []}


def make_ssl_context():
    """Create a TLS client context that accepts self-signed certs (test only)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def send_msg(sock, data):
    """Send a newline-delimited JSON message matching the server protocol."""
    payload = json.dumps(data) + "\n"
    sock.sendall(payload.encode("utf-8"))


def run_client(name, answers):
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ctx = make_ssl_context()
        s = ctx.wrap_socket(raw, server_hostname=HOST)
        s.connect((HOST, PORT))

        # Send join message (new JSON protocol)
        send_msg(s, {"type": "join", "username": name})

        answer_idx = [0]  # mutable index for answer progression
        quiz_started = threading.Event()

        def listen():
            buf = ""
            while True:
                try:
                    data = s.recv(4096).decode("utf-8")
                    if not data:
                        break
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            outputs[name].append(line)
                            continue

                        outputs[name].append(line)

                        # Handle ping/pong for latency measurement
                        if msg.get("type") == "ping":
                            send_msg(s, {"type": "pong"})
                            continue

                        # Detect when quiz questions start
                        msg_text = msg.get("message", "")
                        if "quiz is starting" in msg_text.lower() or "starting in" in msg_text.lower():
                            quiz_started.set()

                except Exception:
                    break

        t = threading.Thread(target=listen, daemon=True)
        t.start()

        # Wait for the quiz to actually start
        quiz_started.wait(timeout=15)
        time.sleep(2)  # Extra buffer for first question to broadcast

        # Send answers with proper timing
        for ans in answers:
            send_msg(s, {"type": "answer", "data": ans})
            time.sleep(3.5)  # TIME_LIMIT(2) + leaderboard pause(1) + buffer

        time.sleep(3)  # Allow final messages (fairness report) to arrive
        s.close()
    except Exception as e:
        print(f"Error in {name}: {e}")


if __name__ == "__main__":
    # Start test server as a subprocess
    proc = subprocess.Popen(
        [sys.executable, "test_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    time.sleep(1)

    # Alice answers all correctly; Bob answers most wrong
    t1 = threading.Thread(target=run_client, args=("Alice",   ["Transport Layer", "Transmission Control Protocol", "SFTP", "Digital Certificate", "TCP", "443", "DNS"]))
    t2 = threading.Thread(target=run_client, args=("Bob",     ["Network Layer",   "Transfer Connect Protocol",    "FTP",  "Public Key",           "UDP", "80",  "ARP"]))

    t1.start(); t2.start()
    t1.join();  t2.join()

    proc.terminate()
    proc.wait()

    # Parse Alice's log - each line is a JSON message
    full_log = "\n".join(outputs["Alice"])

    print("=" * 50)
    if "QUIZ OVER" in full_log:
        print("TEST PASSED - Reached end of quiz.")
    else:
        print("TEST FAILED - Did not reach end of quiz.")
    print("=" * 50)

    # Show last few meaningful messages
    print("\nAlice's Session Log (last 15 messages):")
    for line in outputs["Alice"][-15:]:
        try:
            msg = json.loads(line)
            if msg.get("type") == "text":
                text = msg["message"]
                # Only show non-empty lines
                for l in text.strip().split("\n"):
                    if l.strip():
                        print(f"  {l}")
        except Exception:
            pass

    # Clean up the temporary test server file
    if os.path.exists("test_server.py"):
        os.remove("test_server.py")

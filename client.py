import socket
import threading
import json
import sys
import ssl

DEFAULT_HOST = "127.0.0.1"
PORT = 5000


def receive_messages(sock):
    """Receive newline-delimited JSON messages from the server and display them."""
    buf = ""
    while True:
        try:
            chunk = sock.recv(4096).decode("utf-8")
            if not chunk:
                print("\nServer disconnected.")
                sock.close()
                sys.exit(0)

            buf += chunk

            # Process all complete messages (newline-delimited JSON)
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print(line)
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    # Respond immediately with pong for latency measurement
                    pong = json.dumps({"type": "pong"}) + "\n"
                    sock.sendall(pong.encode("utf-8"))
                elif msg_type == "text":
                    print(msg.get("message", ""))
                elif msg_type == "error":
                    print(f"[ERROR] {msg.get('message', '')}")
                    sock.close()
                    sys.exit(1)
                else:
                    # Fallback: print raw data
                    print(msg.get("message", msg.get("data", str(msg))))

        except Exception as e:
            print(f"\nConnection closed: {e}")
            try:
                sock.close()
            except Exception:
                pass
            sys.exit(0)


def send_msg(sock, data):
    """Send a newline-delimited JSON message."""
    payload = json.dumps(data) + "\n"
    sock.sendall(payload.encode("utf-8"))


def main():
    # ── Parse arguments ──────────────────────────────────────────────────────
    # Usage: python client.py <server_ip> [username]
    host = DEFAULT_HOST

    if len(sys.argv) >= 2:
        host = sys.argv[1]
    else:
        host = input(f"Enter server IP [{DEFAULT_HOST}]: ").strip() or DEFAULT_HOST

    if len(sys.argv) >= 3:
        username = sys.argv[2]
    else:
        username = input("Enter your username: ").strip()

    if not username:
        print("Username cannot be empty.")
        return

    print(f"\nConnecting to {host}:{PORT} with TLS encryption...")

    # ── TLS context (accepts self-signed certs for LAN/demo use) ─────────
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket = ssl_context.wrap_socket(raw_socket, server_hostname=host)

    try:
        client_socket.connect((host, PORT))
    except Exception as e:
        print(f"Unable to connect to server at {host}:{PORT}: {e}")
        return

    print(f"Connected! TLS version: {client_socket.version()}")
    print(f"Cipher: {client_socket.cipher()[0]}\n")

    # ── Send join message ────────────────────────────────────────────────────
    send_msg(client_socket, {"type": "join", "username": username})

    # ── Start receiver thread ────────────────────────────────────────────────
    recv_thread = threading.Thread(target=receive_messages, args=(client_socket,), daemon=True)
    recv_thread.start()

    # ── Main thread: read user input and send answers ────────────────────────
    while True:
        try:
            answer = input()
            if answer.strip():
                send_msg(client_socket, {"type": "answer", "data": answer.strip()})
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            client_socket.close()
            sys.exit(0)
        except Exception:
            break


if __name__ == "__main__":
    main()

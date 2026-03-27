import socket
import threading
import sys
import ssl

HOST = "127.0.0.1"
PORT = 5000

def receive_messages(sock):
    while True:
        try:
            msg = sock.recv(4096).decode('utf-8')
            if not msg:
                print("\nServer disconnected.")
                sock.close()
                sys.exit(0)
            
            # Print the received message to the terminal
            print(msg)
        except Exception as e:
            print(f"\nConnection closed or error: {e}")
            sock.close()
            sys.exit(0)

def main():
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter your username: ").strip()
    
    if not username:
        print("Username cannot be empty.")
        return

    # Create a TLS context that accepts self-signed certs (for local/demo use)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket = ssl_context.wrap_socket(raw_socket, server_hostname=HOST)
    try:
        client_socket.connect((HOST, PORT))
    except Exception as e:
        print(f"Unable to connect to server: {e}")
        return

    # Send the username as the first message
    client_socket.send(username.encode())
    
    # Start receiver thread to listen to the server
    recv_thread = threading.Thread(target=receive_messages, args=(client_socket,))
    recv_thread.daemon = True
    recv_thread.start()
    
    # Main thread handles user input and sends it to the server
    while True:
        try:
            answer = input()
            if answer.strip():
                client_socket.send(answer.encode())
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            client_socket.close()
            sys.exit(0)
        except Exception:
            break

if __name__ == "__main__":
    main()

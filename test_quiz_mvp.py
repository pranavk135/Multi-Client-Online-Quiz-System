import socket
import threading
import time
import subprocess
import os
import sys

# temporarily create a faster server for testing
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

def run_client(name, answers):
    try:
        s = socket.socket()
        s.connect((HOST, PORT))
        s.send(name.encode())
        
        def listen():
            while True:
                try:
                    data = s.recv(4096).decode()
                    if not data: break
                    outputs[name].append(data)
                except:
                    break
        
        listen_thread = threading.Thread(target=listen, daemon=True)
        listen_thread.start()
        
        # Timeline: 1s start delay. Then Q1. 2s to answer, 1s pause.
        # Wait 1.5s then send first, then every 3s
        time.sleep(1.5)
        for ans in answers:
            s.send(ans.encode())
            time.sleep(3)
            
        # Give some time for final messages
        time.sleep(2)
        s.close()
    except Exception as e:
        print(f"Error in {name}: {e}")

if __name__ == "__main__":
    proc = subprocess.Popen([sys.executable, "test_server.py"])
    time.sleep(1)
    
    t1 = threading.Thread(target=run_client, args=("Alice", ["Paris", "FTP", "2", "Transmission Control Protocol"]))
    t2 = threading.Thread(target=run_client, args=("Bob", ["Berlin", "SMTP", "4", "Transfer Connect"]))
    t3 = threading.Thread(target=run_client, args=("Charlie", ["Rome", "SSH", "1", "1"]))
    
    t1.start()
    t2.start()
    t3.start()
    
    t1.join()
    t2.join()
    t3.join()
    
    proc.terminate()
    proc.wait()
    
    full_log = "".join(outputs["Alice"])
    if "=== QUIZ OVER ===" in full_log:
        print("TEST PASSED: Reached the end of quiz.")
    else:
        print("TEST FAILED: Did not reach end.")
    print("----------------------------------------")
    print("Alice's Final View:")
    print(full_log)
    
    os.remove("test_server.py")

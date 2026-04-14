# QuizNet — Multi-Client Online Quiz System

A real-time, multi-client online quiz application built as a Computer Networks mini project. The system demonstrates core networking concepts: **TCP sockets**, **multi-threading**, **SSL/TLS encryption**, and **WebSockets**.

---

## Architecture

```
                        ┌───────────────────────────────┐
                        │          questions.json        │
                        └───────────┬───────────────────┘
                                    │ loaded by
          ┌─────────────────────────┼──────────────────────────────┐
          │                         │                              │
          ▼                         ▼                              │
 ┌─────────────────┐     ┌─────────────────────┐                  │
 │    server.py    │     │    web_server.py     │                  │
 │  (TCP + TLS)    │     │  (FastAPI + WSS)     │                  │
 │  Port: 5000     │     │  Port: 443           │                  │
 └────────┬────────┘     └──────────┬──────────┘                  │
          │ TLS/TCP                 │ WSS (WebSocket over HTTPS)   │
    ┌─────┴─────┐           ┌──────┴──────┐                       │
    │  client.py│           │  Browser    │                       │
    │ (Terminal)│           │  (index.html│                       │
    └───────────┘           │   + app.js) │                       │
                            └─────────────┘                       │
                                                                   │
                        certs/ (cert.pem, key.pem) ───────────────┘
```

### Components

| File | Role |
|------|------|
| `server.py` | TCP quiz server. Wraps socket with TLS. Manages 3 clients, broadcasts questions, collects answers, scores, and sends leaderboard. |
| `client.py` | Terminal-based TLS client. Connects to `server.py`, sends username, displays questions, reads user input. |
| `web_server.py` | FastAPI web server with WebSocket support. Runs over HTTPS (port 443). Serves the browser frontend. |
| `static/index.html` | Browser UI — login, lobby, quiz, leaderboard, and game-over screens. |
| `static/app.js` | WebSocket client logic in vanilla JS. Handles all server message types and UI transitions. |
| `static/style.css` | Minimal dark-theme CSS with Inter font. No external CSS frameworks. |
| `questions.json` | 7 Computer Networks questions (OSI, TCP, SSL/TLS, DNS, ports). |
| `certs/` | Self-signed TLS certificate and key used by both `server.py` and `web_server.py`. |
| `test_quiz_mvp.py` | Automated test: spawns 3 TLS clients simultaneously, verifies quiz completes end-to-end. |

---

## SSL/TLS Implementation

### Terminal Server (`server.py`)
```python
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(certfile="certs/cert.pem", keyfile="certs/key.pem")
server_socket = ssl_context.wrap_socket(raw_socket, server_side=True)
```

### Terminal Client (`client.py`)
```python
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False       # self-signed cert
ssl_context.verify_mode = ssl.CERT_NONE
client_socket = ssl_context.wrap_socket(raw_socket, server_hostname=HOST)
```

### Web Server (`web_server.py`)
```python
uvicorn.run(app, host="0.0.0.0", port=443,
            ssl_keyfile="certs/key.pem",
            ssl_certfile="certs/cert.pem")
```
The browser automatically upgrades the WebSocket connection to **WSS** (WebSocket Secure) when served over HTTPS.

### Generating the Self-Signed Certificate
```bash
openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem \
  -out certs/cert.pem -days 365 -nodes \
  -config certs/openssl.cnf
```

---

## How to Run

### Prerequisites
```bash
pip install -r requirements.txt
```

### Option 1 — Terminal Clients (Raw TCP + TLS)

**Terminal 1 — Start the TCP server:**
```bash
python server.py
```

**Terminals 2, 3, 4 — Connect clients:**
```bash
python client.py         # prompts for username
# or
python client.py Alice   # pass username as argument
```
The quiz starts automatically once **3 players** connect.

---

### Option 2 — Browser Clients (HTTPS + WebSocket Secure)

**Start the web server (requires admin/sudo for port 443):**
```bash
python web_server.py
```

Open **3 browser tabs** (or different browsers) and navigate to:
```
https://127.0.0.1
```
Accept the self-signed certificate warning and enter a username in each tab.

---

### Running the Automated Test
```bash
python test_quiz_mvp.py
```
Spawns 3 TLS-encrypted clients, runs the full quiz, and prints a PASS/FAIL result.

---

## Key Networking Concepts Demonstrated

| Concept | Where Used |
|---------|-----------|
| **TCP Sockets** | `server.py` ↔ `client.py` communication |
| **Multi-threading** | Per-client threads in `server.py`; receiver thread in `client.py` |
| **SSL/TLS (TLS 1.2/1.3)** | Both TCP server and HTTPS/WSS web server |
| **WebSockets** | Real-time browser ↔ `web_server.py` communication |
| **Broadcast** | Server sends questions and leaderboard to all connected clients |
| **Self-Signed Certificates** | Generated via OpenSSL, loaded via Python `ssl` module |
| **Async I/O** | `asyncio` + `uvicorn` in `web_server.py` for concurrent connections |

---

## Project Structure
```
Mini-Project/
├── server.py            # TCP + TLS Quiz Server
├── client.py            # TLS Terminal Client
├── web_server.py        # FastAPI HTTPS + WSS Web Server
├── questions.json       # Quiz Questions (CN topics)
├── test_quiz_mvp.py     # Automated TLS Test
├── requirements.txt     # Python dependencies
├── certs/
│   ├── cert.pem         # Self-signed TLS certificate
│   ├── key.pem          # Private key
│   └── openssl.cnf      # OpenSSL config for cert generation
└── static/
    ├── index.html       # Browser UI
    ├── app.js           # WebSocket client (vanilla JS)
    └── style.css        # Minimal dark-theme styles
```

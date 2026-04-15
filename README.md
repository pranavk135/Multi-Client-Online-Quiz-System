# QuizNet — Multi-Client Online Quiz System

A real-time, multi-client quiz system built with Python that runs across **connected computers on a LAN** using **TCP sockets with TLS/SSL encryption**. Designed for a Computer Networks mini-project demonstrating networking concepts verifiable via **Wireshark**.

---

## 📋 Table of Contents

- [Architecture](#-architecture)
- [Features](#-features)
- [Prerequisites](#-prerequisites)
- [Setup Instructions](#-setup-instructions)
  - [1. Generate TLS Certificates](#1-generate-tls-certificates)
  - [2. Install Dependencies](#2-install-dependencies)
  - [3. Run the Server](#3-run-the-server)
  - [4. Run Clients](#4-run-clients)
- [Two Modes of Operation](#-two-modes-of-operation)
- [Wireshark Verification Guide](#-wireshark-verification-guide)
- [File Structure](#-file-structure)
- [Troubleshooting](#-troubleshooting)

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SERVER MACHINE                         │
│                                                             │
│   ┌─────────────┐         ┌──────────────────┐             │
│   │  server.py   │         │  web_server.py   │             │
│   │ (TCP Socket) │         │ (FastAPI + WSS)  │             │
│   │  Port 5000   │         │   Port 8443      │             │
│   └──────┬───────┘         └────────┬─────────┘             │
│          │ TLS/SSL                   │ TLS/SSL               │
│          │ Encrypted                 │ Encrypted             │
└──────────┼───────────────────────────┼───────────────────────┘
           │                           │
     ┌─────┴─────┐             ┌──────┴──────┐
     │  LAN/WiFi  │             │  LAN/WiFi   │
     └─────┬─────┘             └──────┬──────┘
           │                           │
  ┌────────┴────────┐        ┌────────┴────────┐
  │  CLIENT MACHINE  │        │  CLIENT MACHINE  │
  │                  │        │                  │
  │   client.py      │        │  Web Browser     │
  │  (TCP Socket)    │        │  (HTTPS/WSS)     │
  └──────────────────┘        └──────────────────┘
```

**Protocol Stack:**
```
Application  :  Quiz Protocol (JSON messages)
Transport    :  TCP (reliable, ordered delivery)
Security     :  TLS 1.2/1.3 (encryption, authentication)
Network      :  IPv4 (LAN)
```

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **TCP Sockets** | Reliable, connection-oriented communication |
| **TLS/SSL Encryption** | All traffic encrypted with self-signed certificates |
| **Multi-Client Support** | 2-3 simultaneous players |
| **Real-Time Leaderboard** | Live score updates after each question |
| **Latency Measurement** | Ping-pong based RTT calculation |
| **Fairness Evaluation** | Jain's Fairness Index for latency bias analysis |
| **Wireshark Verifiable** | TLS handshake and encrypted payloads visible in captures |
| **Two Interfaces** | Terminal-based (TCP) and Web-based (HTTPS/WebSocket) |

---

## ⚙ Prerequisites

- **Python 3.8+** on all machines
- **OpenSSL** for certificate generation
  - Windows: `winget install ShiningLight.OpenSSL`
  - Linux: `sudo apt install openssl`
  - macOS: pre-installed
- **Wireshark** for packet capture analysis
  - Download: https://www.wireshark.org/download.html
- All machines must be on the **same LAN/WiFi network**

---

## 🚀 Setup Instructions

### 1. Generate TLS Certificates

Before running, you must generate TLS certificates with your **server machine's LAN IP**.

**Find your server's LAN IP:**
```bash
# Windows
ipconfig       # Look for "IPv4 Address" under Wi-Fi or Ethernet

# Linux
ip a           # Look for "inet" under wlan0 or eth0

# macOS
ifconfig en0   # Look for "inet"
```

**Generate certificates:**
```bash
cd certs

# Windows
generate_certs.bat

# Linux/macOS
chmod +x generate_certs.sh
./generate_certs.sh
```

Or manually with OpenSSL:
```bash
cd certs
# Edit openssl.cnf: Change IP.2 to your server's LAN IP
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout key.pem -out cert.pem -config openssl.cnf
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Server

**On the SERVER machine:**

```bash
# Terminal-based (TCP socket on port 5000)
python server.py               # Default: 2 players
python server.py 3             # For 3 players

# Web-based (HTTPS on port 8443)
python web_server.py                    # Default: port 8443, 2 players
python web_server.py --port 9000       # Custom port
python web_server.py --players 3       # 3 players
```

### 4. Run Clients

**On each CLIENT machine:**

```bash
# Terminal client — connect to server's LAN IP
python client.py 192.168.1.42          # Will prompt for username
python client.py 192.168.1.42 Alice    # Username as argument

# Web client — open browser and navigate to:
# https://192.168.1.42:8443
# (Accept the self-signed certificate warning)
```

---

## 🎮 Two Modes of Operation

### Mode 1: Terminal-Based (TCP Sockets)
- **Server**: `server.py` — raw TCP socket server with TLS
- **Client**: `client.py` — raw TCP socket client with TLS
- **Port**: 5000
- **Best for**: Wireshark analysis (clean TCP/TLS traffic)

### Mode 2: Web-Based (HTTPS + WebSocket)
- **Server**: `web_server.py` — FastAPI with HTTPS and Secure WebSocket
- **Client**: Any web browser
- **Port**: 8443
- **Best for**: User-friendly interface with visual leaderboard

---

## 🔍 Wireshark Verification Guide

This section explains how to use Wireshark to verify TCP communication and TLS/SSL encryption.

### Step 1: Start Wireshark Capture

1. Open Wireshark on the **server machine**
2. Select the network interface connected to your LAN (e.g., Wi-Fi or Ethernet)
3. Start capturing packets

### Step 2: Apply Display Filter

For terminal-based server (port 5000):
```
tcp.port == 5000
```

For web-based server (port 8443):
```
tcp.port == 8443
```

### Step 3: Start the Quiz

1. Run the server
2. Connect clients from other machines
3. Play through the quiz

### Step 4: Analyze the Capture

#### TCP 3-Way Handshake
Look for three consecutive packets at the start of each connection:
```
Client → Server : [SYN]        (Synchronize)
Server → Client : [SYN, ACK]   (Synchronize-Acknowledge)
Client → Server : [ACK]        (Acknowledge)
```
This confirms TCP is the transport protocol.

#### TLS Handshake
After the TCP handshake, you'll see TLS negotiation:
```
Client → Server : Client Hello     (TLS version, supported ciphers)
Server → Client : Server Hello     (Selected cipher, certificate)
Server → Client : Certificate      (Server's X.509 certificate)
Client → Server : Key Exchange     (Pre-master secret, encrypted)
Both            : Change Cipher Spec
Both            : Finished          (Handshake complete)
```

#### Encrypted Application Data
After the TLS handshake, all quiz data (questions, answers, scores) appears as:
```
Client ↔ Server : Application Data  (encrypted, NOT readable)
```

**Key Observation**: The quiz questions, answers, and scores are **NOT visible in plaintext** in Wireshark — they are encrypted by TLS. This proves the encryption is working.

### Step 5: Wireshark Screenshots to Capture

For your project report, capture screenshots showing:

1. **TCP Handshake** — Filter: `tcp.flags.syn == 1`
2. **TLS Client Hello** — Filter: `tls.handshake.type == 1`
3. **TLS Server Hello + Certificate** — Filter: `tls.handshake.type == 2`
4. **Encrypted Data** — Any `Application Data` packet showing encrypted payload
5. **Full conversation** — Right-click a packet → Follow → TCP Stream

### Step 6: Export for Report

- **File → Export Packet Dissections → As PDF** for documentation
- **Statistics → Conversations → TCP** for connection summary
- **Statistics → Protocol Hierarchy** for protocol breakdown

---

## 📁 File Structure

```
Mini-Project/
├── server.py           # TCP socket server with TLS (terminal clients)
├── client.py           # TCP socket client with TLS (terminal client)
├── web_server.py       # FastAPI web server with HTTPS/WSS (browser clients)
├── questions.json      # Quiz questions database (7 networking questions)
├── requirements.txt    # Python dependencies (fastapi, uvicorn, websockets)
├── test_quiz_mvp.py    # Automated test script (2 simulated clients)
├── README.md           # This file
├── certs/
│   ├── cert.pem        # TLS certificate (generated)
│   ├── key.pem         # TLS private key (generated)
│   ├── openssl.cnf     # OpenSSL configuration (edit IP.2 for your LAN)
│   ├── generate_certs.bat  # Windows certificate generator
│   └── generate_certs.sh   # Linux/macOS certificate generator
└── static/
    ├── index.html      # Web UI HTML
    ├── style.css       # Web UI styles (dark theme)
    └── app.js          # Web UI JavaScript (WebSocket client)
```

---

## 🛠 Troubleshooting

### "Unable to connect to server"
- Verify the server is running and showing "Waiting for players..."
- Check that the client is using the correct server IP
- Ensure both machines are on the same network
- Check Windows Firewall: allow Python through on port 5000/8443

### "SSL certificate verify failed"
- The client uses `CERT_NONE` mode — this shouldn't happen
- If using a browser, click "Advanced" → "Proceed to site" to accept the self-signed cert

### "Certificate does not match server IP"
- Regenerate certificates with the correct server LAN IP
- Run `generate_certs.bat` (Windows) or `generate_certs.sh` (Linux/Mac)

### Browser shows "Connection Refused"
- Make sure `web_server.py` is running
- Use `https://` (not `http://`) — the server requires TLS
- Check the port: default is `8443`, not `443`

### Wireshark shows no packets
- Make sure you're capturing on the correct network interface
- Apply the correct display filter: `tcp.port == 5000` or `tcp.port == 8443`
- Make sure you started capture **before** connecting clients

### Windows Firewall blocking connections
```powershell
# Allow Python through firewall (run as Administrator)
netsh advfirewall firewall add rule name="QuizNet Server" dir=in action=allow protocol=TCP localport=5000
netsh advfirewall firewall add rule name="QuizNet Web" dir=in action=allow protocol=TCP localport=8443
```

---

## 🧪 Running Tests

```bash
python test_quiz_mvp.py
```

This runs an automated test with 2 simulated clients on localhost. It verifies:
- TLS connection establishment
- Quiz question/answer flow
- Score calculation
- Fairness report generation

---

## 📄 License

Academic project — Computer Networks Mini-Project (Semester 4)

"""
QuizNet Web Server — Multi-Threaded TCP/TLS Architecture
=========================================================

Concurrency model:
  - One dedicated thread per connected client (blocking I/O)
  - Quiz controller runs in its own thread
  - Static HTTP files served via process_request hook (same port)
  - No async/await — pure threading with Lock/Event synchronization

Architecture:
  Main Thread ──── WebSocket Server (accepts TCP connections over TLS)
       │              ├── Client Thread: "Alice"   (blocking recv/send)
       │              ├── Client Thread: "Bob"     (blocking recv/send)
       │              └── Client Thread: "Charlie" (blocking recv/send)
       │
       └── Quiz Controller Thread (quiz logic, broadcasts, timer)
"""

import json
import logging
import time
import ssl
import socket
import threading
import os
import sys
import argparse
import mimetypes
from urllib.parse import unquote

from websockets.sync.server import serve as ws_serve
from websockets.http11 import Response
from websockets.datastructures import Headers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(thread)-16s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

NUM_PLAYERS   = 2       # Default: 2 players (override with --players N)
TIME_LIMIT    = 10
LATENCY_PINGS = 3


# ══════════════════════════════════════════════════════════════════════════
# Static File Serving (via process_request hook — same port as WebSocket)
# ══════════════════════════════════════════════════════════════════════════

def serve_static_file(connection, request):
    """
    Handle HTTP requests for static files.
    Returns a Response for static content, or None to proceed with
    the WebSocket upgrade handshake.

    This runs in the acceptor thread BEFORE a client thread is spawned.
    """
    path = request.path

    # WebSocket paths — let the WebSocket handler deal with them
    if path.startswith("/ws/"):
        return None

    # Serve index.html for root
    if path in ("/", ""):
        path = "/static/index.html"

    # Map URL path to filesystem path
    file_path = path.lstrip("/")

    if os.path.isfile(file_path):
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

        with open(file_path, "rb") as f:
            body = f.read()

        return Response(
            200, "OK",
            Headers([
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-cache"),
            ]),
            body,
        )

    return Response(404, "Not Found", Headers(), b"404 Not Found")


# ══════════════════════════════════════════════════════════════════════════
# QuizManager — thread-safe shared state
# ══════════════════════════════════════════════════════════════════════════

class QuizManager:
    """
    Thread-safe quiz state manager.
    All mutable shared state is protected by self.lock (threading.Lock).
    Per-client send operations are serialized by per-client send_locks.
    """

    def __init__(self, num_players):
        self.num_players = num_players
        self.lock = threading.Lock()            # Protects all shared state below
        self.all_joined = threading.Event()     # Signaled when enough players connect
        self.quiz_over  = threading.Event()     # Signaled when quiz ends

        # Per-client send locks (prevents concurrent sends on the same socket)
        self.send_locks = {}                    # username -> threading.Lock

        # Shared game state
        self.connections       = {}             # username -> websocket
        self.client_ips        = {}             # username -> "ip:port"
        self.scores            = {}             # username -> int
        self.current_responses = {}             # username -> answer str
        self.accepting_answers = False
        self.quiz_started      = False

        # Latency & fairness tracking
        self.latencies         = {}             # username -> one-way latency (seconds)
        self.response_times    = {}             # username -> [raw times per question]
        self.adjusted_times    = {}             # username -> [adjusted times]
        self.answer_timestamps = {}             # username -> time.time() of answer
        self.question_send_time = 0.0

        # Pong coordination (for latency measurement)
        self.pong_events = {}                   # username -> threading.Event
        self.pong_times  = {}                   # username -> float

        # Load questions
        try:
            with open("questions.json", "r") as f:
                self.questions = json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions.json: {e}")
            self.questions = []

    # ── Player management ────────────────────────────────────────────────

    def add_player(self, username, websocket, ip_str):
        """Register a new player. Returns (success: bool, error_msg: str|None)."""
        with self.lock:
            if username in self.connections:
                return False, "Username already taken."
            if self.quiz_started:
                return False, "Quiz already in progress."

            self.connections[username]    = websocket
            self.send_locks[username]    = threading.Lock()
            self.client_ips[username]    = ip_str
            self.scores[username]        = 0
            self.response_times[username] = []
            self.adjusted_times[username] = []
            self.pong_events[username]   = threading.Event()

            count = len(self.connections)
            logger.info(
                f"[CONNECT]  {username:15s}  IP: {ip_str}  "
                f"({count}/{self.num_players})"
            )

            if count >= self.num_players:
                self.all_joined.set()

            return True, None

    def remove_player(self, username):
        """Unregister a player and optionally broadcast updated lobby."""
        broadcast_lobby = False
        players = []

        with self.lock:
            self.connections.pop(username, None)
            self.send_locks.pop(username, None)
            ip = self.client_ips.pop(username, "unknown")

            if not self.quiz_started:
                self.scores.pop(username, None)
                self.response_times.pop(username, None)
                self.adjusted_times.pop(username, None)
                self.pong_events.pop(username, None)
                players = list(self.connections.keys())
                broadcast_lobby = True
                logger.info(
                    f"[DISCONNECT] {username} ({ip}) left lobby. "
                    f"({len(self.connections)}/{self.num_players})"
                )
            else:
                logger.info(f"[DISCONNECT] {username} ({ip}) left mid-quiz.")

        if broadcast_lobby:
            self.broadcast({
                "type": "lobby_update",
                "players": players,
                "required": self.num_players,
            })
            self.broadcast({
                "type": "system",
                "message": f"{username} disconnected. ({len(players)}/{self.num_players})",
            })

    # ── Communication ────────────────────────────────────────────────────

    def send_to(self, username, data):
        """Send a JSON message to one client. Uses per-client lock for thread safety."""
        with self.lock:
            ws        = self.connections.get(username)
            send_lock = self.send_locks.get(username)

        if ws and send_lock:
            with send_lock:
                try:
                    ws.send(json.dumps(data))
                except Exception:
                    pass

    def broadcast(self, data):
        """Broadcast a JSON message to every connected client."""
        with self.lock:
            clients = list(self.connections.keys())
        for uname in clients:
            self.send_to(uname, data)

    def get_player_list(self):
        with self.lock:
            return list(self.connections.keys())

    # ── Answer recording ─────────────────────────────────────────────────

    def record_answer(self, username, answer):
        """Record a player's answer (first answer only). Returns True if recorded."""
        with self.lock:
            if self.accepting_answers and username not in self.current_responses:
                self.answer_timestamps[username] = time.time()
                self.current_responses[username] = answer
                return True
            return False

    def record_pong(self, username):
        """Record pong receipt time and signal the waiting event."""
        self.pong_times[username] = time.time()
        event = self.pong_events.get(username)
        if event:
            event.set()


# ══════════════════════════════════════════════════════════════════════════
# Client Handler — ONE DEDICATED THREAD PER CLIENT
# ══════════════════════════════════════════════════════════════════════════

def client_handler(websocket, manager):
    """
    Handle one WebSocket client connection.

    *** This function runs in a DEDICATED THREAD for each connected client. ***
    All I/O is BLOCKING — no async/await anywhere.
    The thread exits when the client disconnects or the quiz ends.
    """

    # ── Extract username from path: /ws/<username> ────────────────────────
    path  = websocket.request.path
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "ws":
        username = unquote(parts[1])
    else:
        try:
            websocket.send(json.dumps({"type": "error", "message": "Invalid path."}))
        except Exception:
            pass
        return

    # ── Get client IP ─────────────────────────────────────────────────────
    try:
        addr   = websocket.socket.getpeername()
        ip_str = f"{addr[0]}:{addr[1]}"
    except Exception:
        ip_str = "unknown"

    # Name this thread for clear log visibility
    threading.current_thread().name = f"Client-{username}"
    logger.info(f"[WS HANDSHAKE] {username} from {ip_str}")

    # ── Register player ───────────────────────────────────────────────────
    success, error = manager.add_player(username, websocket, ip_str)
    if not success:
        try:
            websocket.send(json.dumps({"type": "error", "message": error}))
        except Exception:
            pass
        return

    # ── Broadcast lobby update ────────────────────────────────────────────
    players = manager.get_player_list()
    manager.broadcast({
        "type": "system",
        "message": f"{username} joined! ({len(players)}/{manager.num_players})",
    })
    manager.broadcast({
        "type": "lobby_update",
        "players": players,
        "required": manager.num_players,
    })

    # ══════════════════════════════════════════════════════════════════════
    #  BLOCKING RECEIVE LOOP — this is the core of the per-client thread
    # ══════════════════════════════════════════════════════════════════════
    try:
        while not manager.quiz_over.is_set():
            try:
                data = websocket.recv(timeout=1.0)
            except TimeoutError:
                continue
            except Exception:
                break

            # Check for pong response (latency measurement)
            try:
                msg = json.loads(data)
                if msg.get("type") == "pong":
                    manager.record_pong(username)
                    continue
            except (json.JSONDecodeError, AttributeError):
                pass

            # Try to record as a quiz answer
            answer = data.strip()
            if answer and manager.record_answer(username, answer):
                logger.info(f"[ANSWER] {username}: '{answer}'")
                manager.send_to(username, {"type": "ack", "message": "Answer received!"})

    except Exception as e:
        logger.debug(f"Client handler error for {username}: {e}")
    finally:
        manager.remove_player(username)
        logger.info(f"[CLOSED] Thread for {username} exiting")


# ══════════════════════════════════════════════════════════════════════════
# Quiz Controller — runs in its own dedicated thread
# ══════════════════════════════════════════════════════════════════════════

def quiz_controller(manager):
    """
    Main quiz logic thread.
    Blocks on threading.Event until all players join, then runs the quiz.
    """
    threading.current_thread().name = "QuizController"
    logger.info(f"Waiting for {manager.num_players} players to join...")

    # ── Block until all players have connected ────────────────────────────
    manager.all_joined.wait()

    with manager.lock:
        manager.quiz_started = True
    logger.info("=" * 52)
    logger.info("QUIZ STARTING")
    logger.info("Connected clients:")
    with manager.lock:
        for uname, ip in manager.client_ips.items():
            logger.info(f"  {uname:15s}  {ip}")
    logger.info("=" * 52)

    # ── Measure network latency ───────────────────────────────────────────
    manager.broadcast({
        "type": "system",
        "message": "All players connected! Measuring network latency...",
    })
    measure_latency(manager)

    manager.broadcast({
        "type": "system",
        "message": "Latency measured! Quiz starts in 3 seconds...",
    })
    time.sleep(3)

    # ── Run the quiz ──────────────────────────────────────────────────────
    run_quiz(manager)


def measure_latency(manager):
    """Ping each client and compute one-way latency. Runs in QuizController thread."""
    logger.info("Measuring latency for all players...")
    players = manager.get_player_list()

    for username in players:
        rtts = []
        try:
            for _ in range(LATENCY_PINGS):
                event = manager.pong_events.get(username)
                if event:
                    event.clear()

                ping_time = time.time()
                manager.send_to(username, {"type": "ping"})

                # Block until pong received (up to 5 seconds)
                if event and event.wait(timeout=5.0):
                    pong_time = manager.pong_times.get(username, ping_time)
                    rtts.append(pong_time - ping_time)

                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Latency ping failed for {username}: {e}")

        with manager.lock:
            manager.latencies[username] = (sum(rtts) / len(rtts) / 2) if rtts else 0

    # Log and broadcast results
    logger.info("Latency results (one-way):")
    latency_data = []
    with manager.lock:
        for uname, lat in manager.latencies.items():
            ms = round(lat * 1000, 1)
            logger.info(f"  {uname:15s}  {ms} ms")
            latency_data.append({"username": uname, "latency_ms": ms})

    manager.broadcast({"type": "latency_results", "results": latency_data})


def run_quiz(manager):
    """Run all quiz questions sequentially. Runs in QuizController thread."""
    for idx, q in enumerate(manager.questions):
        with manager.lock:
            manager.current_responses.clear()
            manager.answer_timestamps.clear()
            manager.question_send_time = time.time()
            manager.accepting_answers = True

        manager.broadcast({
            "type": "question",
            "number": idx + 1,
            "total": len(manager.questions),
            "question": q["question"],
            "options": q["options"],
            "time_limit": TIME_LIMIT,
        })
        logger.info(f"[Q{idx+1}] {q['question'][:70]}")

        # Countdown timer (blocking sleep — no asyncio)
        for i in range(TIME_LIMIT, 0, -1):
            manager.broadcast({"type": "timer", "time_left": i})
            time.sleep(1)

        with manager.lock:
            manager.accepting_answers = False
        manager.broadcast({"type": "timer", "time_left": 0})

        # ── Evaluate answers ──────────────────────────────────────────────
        correct_answer = q["answer"]
        correct_idx    = str(q["options"].index(correct_answer) + 1)

        manager.broadcast({
            "type": "answer_result",
            "correct_answer": correct_answer,
            "message": f"Time's up! Correct answer: {correct_answer}",
        })

        with manager.lock:
            for uname, response in manager.current_responses.items():
                if response.lower() == correct_answer.lower() or response == correct_idx:
                    manager.scores[uname] += 10

            for uname in list(manager.connections.keys()):
                if uname in manager.answer_timestamps:
                    raw = manager.answer_timestamps[uname] - manager.question_send_time
                    adj = max(0, raw - manager.latencies.get(uname, 0))
                    manager.response_times[uname].append(raw)
                    manager.adjusted_times[uname].append(adj)
                else:
                    manager.response_times[uname].append(TIME_LIMIT)
                    manager.adjusted_times[uname].append(TIME_LIMIT)

        send_leaderboard(manager)
        time.sleep(5)

    end_quiz(manager)


def send_leaderboard(manager):
    with manager.lock:
        sorted_scores = sorted(manager.scores.items(), key=lambda x: x[1], reverse=True)
    manager.broadcast({
        "type": "leaderboard",
        "scores": [{"username": k, "score": v} for k, v in sorted_scores],
    })


def end_quiz(manager):
    with manager.lock:
        sorted_scores = sorted(manager.scores.items(), key=lambda x: x[1], reverse=True)
    winner = sorted_scores[0][0] if sorted_scores else "None"

    manager.broadcast({
        "type": "quiz_over",
        "scores": [{"username": k, "score": v} for k, v in sorted_scores],
        "winner": winner,
    })

    # Send fairness data to clients
    fairness_data = build_fairness_data(manager)
    manager.broadcast({"type": "fairness_report", "fairness": fairness_data})

    # Print report to server console only
    print_fairness_report(manager)
    logger.info("Quiz finished. Server will reset for next game.")

    # Signal quiz over so client threads can exit
    manager.quiz_over.set()
    time.sleep(3)
    reset_manager(manager)


# ══════════════════════════════════════════════════════════════════════════
# Fairness Report
# ══════════════════════════════════════════════════════════════════════════

def build_fairness_data(manager):
    """Build fairness data dict to send to clients."""
    with manager.lock:
        latencies_list = [
            {"username": u, "latency_ms": round(manager.latencies.get(u, 0) * 1000, 1)}
            for u in manager.scores
        ]

        response_stats = []
        avg_adjusted   = {}
        for u in manager.scores:
            raw_list = manager.response_times.get(u, [])
            adj_list = manager.adjusted_times.get(u, [])
            if raw_list:
                avg_raw = round((sum(raw_list) / len(raw_list)) * 1000, 1)
                avg_adj = round((sum(adj_list) / len(adj_list)) * 1000, 1)
                avg_adjusted[u] = avg_adj
                response_stats.append({
                    "username": u,
                    "avg_raw_ms": avg_raw,
                    "avg_adjusted_ms": avg_adj,
                })

        # Jain's Fairness Index
        jfi     = None
        verdict = "Not enough data"
        if len(avg_adjusted) > 1:
            vals   = list(avg_adjusted.values())
            n      = len(vals)
            sum_x  = sum(vals)
            sum_x2 = sum(v * v for v in vals)
            jfi    = round((sum_x ** 2) / (n * sum_x2), 4) if sum_x2 > 0 else 1.0
            if   jfi >= 0.95: verdict = "FAIR - minimal latency bias"
            elif jfi >= 0.80: verdict = "MODERATE - some latency advantage exists"
            else:             verdict = "UNFAIR - significant latency disparity"

        # Per-question breakdown
        players = list(manager.scores.keys())
        per_question = []
        for i in range(len(manager.questions)):
            q_data = {"question": i + 1}
            for u in players:
                rt = manager.response_times.get(u, [])
                q_data[u] = round(rt[i] * 1000, 1) if i < len(rt) else None
            per_question.append(q_data)

    return {
        "latencies": latencies_list,
        "response_stats": response_stats,
        "jfi": jfi,
        "verdict": verdict,
        "players": players,
        "per_question": per_question,
    }


def print_fairness_report(manager):
    """Print fairness report to server console (not sent to clients)."""
    with manager.lock:
        report  = "\n" + "=" * 52 + "\n"
        report += "      LATENCY & FAIRNESS EVALUATION REPORT\n"
        report += "=" * 52 + "\n"

        report += "\n[1] Client IPs\n" + "-" * 35 + "\n"
        for u, ip in manager.client_ips.items():
            report += f"  {u:15s} : {ip}\n"

        report += "\n[2] Network Latency (One-Way)\n" + "-" * 35 + "\n"
        for u in manager.scores:
            lat = manager.latencies.get(u, 0)
            report += f"  {u:15s} : {lat*1000:6.1f} ms\n"

        report += "\n[3] Avg Response Times\n" + "-" * 35 + "\n"
        report += f"  {'Player':15s} | {'Raw (ms)':>10s} | {'Adjusted (ms)':>13s}\n"
        avg_adjusted = {}
        for u in manager.scores:
            raw_list = manager.response_times.get(u, [])
            adj_list = manager.adjusted_times.get(u, [])
            if raw_list:
                avg_raw = (sum(raw_list) / len(raw_list)) * 1000
                avg_adj = (sum(adj_list) / len(adj_list)) * 1000
                avg_adjusted[u] = avg_adj
                report += f"  {u:15s} | {avg_raw:10.1f} | {avg_adj:13.1f}\n"

        report += "\n[4] Jain's Fairness Index\n" + "-" * 35 + "\n"
        if len(avg_adjusted) > 1:
            vals   = list(avg_adjusted.values())
            n      = len(vals)
            sum_x  = sum(vals)
            sum_x2 = sum(v * v for v in vals)
            jfi    = (sum_x ** 2) / (n * sum_x2) if sum_x2 > 0 else 1.0
            report += f"  JFI = {jfi:.4f}  (1.0 = perfectly fair)\n"
            if   jfi >= 0.95: report += "  Verdict: FAIR - minimal latency bias\n"
            elif jfi >= 0.80: report += "  Verdict: MODERATE - some latency advantage\n"
            else:             report += "  Verdict: UNFAIR - significant disparity\n"
        else:
            report += "  Not enough data.\n"

        report += "\n[5] Per-Question Response Times (ms)\n" + "-" * 35 + "\n"
        users  = list(manager.scores.keys())
        header = f"  {'Q#':>3s}"
        for u in users:
            header += f" | {u:>12s}"
        report += header + "\n"
        for i in range(len(manager.questions)):
            row = f"  {i+1:3d}"
            for u in users:
                rt = manager.response_times.get(u, [])
                if i < len(rt):
                    row += f" | {rt[i]*1000:12.1f}"
                else:
                    row += f" | {'—':>12s}"
            report += row + "\n"

        report += "\n" + "=" * 52 + "\n"
        print(report)


# ══════════════════════════════════════════════════════════════════════════
# Server Reset (for next game)
# ══════════════════════════════════════════════════════════════════════════

def reset_manager(manager):
    """Reset all state so the server can host another game."""
    with manager.lock:
        manager.quiz_started = False
        manager.quiz_over.clear()
        manager.all_joined.clear()
        manager.connections.clear()
        manager.send_locks.clear()
        manager.client_ips.clear()
        manager.scores.clear()
        manager.current_responses.clear()
        manager.latencies.clear()
        manager.response_times.clear()
        manager.adjusted_times.clear()
        manager.answer_timestamps.clear()
        manager.pong_events.clear()
        manager.pong_times.clear()

    # Start a new quiz controller for the next round
    threading.Thread(
        target=quiz_controller, args=(manager,),
        daemon=True, name="QuizController",
    ).start()
    logger.info("Server reset. Waiting for new players...")


# ══════════════════════════════════════════════════════════════════════════
# Main — Server Entry Point
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuizNet Web Server (Multi-Threaded)")
    parser.add_argument("--port",    type=int, default=8443,        help="Port (default: 8443)")
    parser.add_argument("--players", type=int, default=NUM_PLAYERS, help=f"Players needed (default: {NUM_PLAYERS})")
    args = parser.parse_args()

    NUM_PLAYERS = args.players
    manager = QuizManager(num_players=NUM_PLAYERS)

    # Discover LAN IPs
    hostname = socket.gethostname()
    try:
        local_ips = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        local_ips = ["127.0.0.1"]

    print("=" * 58)
    print("  QUIZNET WEB SERVER — MULTI-THREADED TCP/TLS")
    print("=" * 58)
    print(f"  Port          : {args.port}")
    print(f"  Players needed: {NUM_PLAYERS}")
    print(f"  Server IPs    : {', '.join(local_ips)}")
    print(f"  Open browser  : https://<SERVER_IP>:{args.port}")
    print("-" * 58)
    print(f"  Threading     : One thread per client (blocking I/O)")
    print(f"  Protocol      : WebSocket over TCP/TLS")
    print(f"  Sync model    : threading.Lock + threading.Event")
    print("=" * 58)

    # ── SSL context ───────────────────────────────────────────────────────
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile="certs/cert.pem", keyfile="certs/key.pem")

    # ── Start Quiz Controller thread ──────────────────────────────────────
    threading.Thread(
        target=quiz_controller, args=(manager,),
        daemon=True, name="QuizController",
    ).start()

    # ── Start WebSocket server on main thread ─────────────────────────────
    #    process_request hook serves static HTTP files on the same port.
    #    Each WebSocket connection spawns a new thread automatically.
    logger.info(f"Server listening on wss://0.0.0.0:{args.port}")

    def handler(websocket):
        client_handler(websocket, manager)

    with ws_serve(
        handler,
        host="0.0.0.0",
        port=args.port,
        ssl=ssl_ctx,
        process_request=serve_static_file,
    ) as server:
        server.serve_forever()
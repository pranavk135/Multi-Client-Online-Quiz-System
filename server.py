import socket
import threading
import json
import time
import ssl
import sys

HOST = "0.0.0.0"          # Listen on ALL interfaces (required for LAN)
PORT = 5000
NUM_PLAYERS = 2            # Default: 1 server + 1 client (override via CLI)
TIME_LIMIT = 10
LATENCY_PINGS = 3          # Number of pings to average for latency measurement


class QuizServer:
    def __init__(self, num_players=NUM_PLAYERS):
        self.num_players = num_players
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Wrap with TLS using the self-signed certificate
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ssl_context.load_cert_chain(certfile="certs/cert.pem", keyfile="certs/key.pem")
        self.server_socket = self.ssl_context.wrap_socket(raw_socket, server_side=True)

        self.clients = []
        self.scores = {}
        self.current_responses = {}
        self.accepting_answers = False

        # Latency & fairness tracking
        self.latencies = {}           # username -> measured one-way latency (seconds)
        self.response_times = {}      # username -> list of raw response times per question
        self.adjusted_times = {}      # username -> list of latency-adjusted response times
        self.answer_timestamps = {}   # username -> timestamp when answer was received
        self.question_send_time = 0   # timestamp when current question was broadcast
        self.recv_buffers = {}        # username -> partial receive buffer

        try:
            with open("questions.json", "r") as f:
                self.questions = json.load(f)
        except FileNotFoundError:
            print("questions.json not found! Exiting.")
            exit(1)

    # ── Protocol helpers ─────────────────────────────────────────────────────
    def send_msg(self, conn, data):
        """Send a newline-delimited JSON message over TCP/TLS."""
        try:
            payload = json.dumps(data) + "\n"
            conn.sendall(payload.encode("utf-8"))
        except Exception:
            pass

    def send_text(self, conn, text):
        """Send a simple text message wrapped in JSON."""
        self.send_msg(conn, {"type": "text", "message": text})

    def recv_one_msg(self, conn, username, timeout=None):
        """Receive exactly one newline-delimited JSON message. Returns parsed dict or None."""
        if timeout is not None:
            conn.settimeout(timeout)

        buf = self.recv_buffers.get(username, "")

        while "\n" not in buf:
            try:
                chunk = conn.recv(4096).decode("utf-8")
                if not chunk:
                    return None
                buf += chunk
            except socket.timeout:
                self.recv_buffers[username] = buf
                return None
            except Exception:
                return None

        line, rest = buf.split("\n", 1)
        self.recv_buffers[username] = rest

        if timeout is not None:
            conn.settimeout(None)

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"type": "raw", "data": line}

    # ── Broadcast ────────────────────────────────────────────────────────────
    def broadcast(self, message):
        """Broadcast a plain-text message to every connected client."""
        for conn, _ in self.clients:
            self.send_text(conn, message)

    def broadcast_json(self, data):
        """Broadcast a JSON object to every connected client."""
        for conn, _ in self.clients:
            self.send_msg(conn, data)

    # ── Server start ─────────────────────────────────────────────────────────
    def start(self):
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen()

        # Discover and display the server's LAN IP(s)
        import socket as _s
        hostname = _s.gethostname()
        try:
            local_ips = _s.gethostbyname_ex(hostname)[2]
        except Exception:
            local_ips = ["127.0.0.1"]

        print("=" * 55)
        print("  QUIZNET SERVER - TCP/TLS")
        print("=" * 55)
        print(f"  Port          : {PORT}")
        print(f"  Players needed: {self.num_players}")
        print(f"  Server IPs    : {', '.join(local_ips)}")
        print(f"  Clients run   : python client.py <SERVER_IP>")
        print("=" * 55)
        print(f"\nWaiting for {self.num_players} players to connect...\n")

        while len(self.clients) < self.num_players:
            try:
                conn, addr = self.server_socket.accept()
            except Exception:
                break

            # First message from client: {"type": "join", "username": "..."}
            msg = self.recv_one_msg(conn, f"_pending_{addr}", timeout=10)
            if not msg or msg.get("type") != "join":
                self.send_msg(conn, {"type": "error", "message": "Invalid handshake."})
                conn.close()
                continue

            username = msg.get("username", "").strip()
            if not username or username in self.scores:
                self.send_msg(conn, {"type": "error", "message": "Invalid or duplicate username."})
                conn.close()
                continue

            self.clients.append((conn, username))
            self.scores[username] = 0
            self.response_times[username] = []
            self.adjusted_times[username] = []
            self.recv_buffers[username] = self.recv_buffers.pop(f"_pending_{addr}", "")

            print(f"  [+] {username} joined from {addr[0]}:{addr[1]}")
            self.broadcast(f"{username} has joined the quiz! ({len(self.clients)}/{self.num_players})")

        print(f"\nAll {self.num_players} players connected!")
        self.broadcast(f"\n--- All players connected! Measuring network latency... ---")
        self.measure_latency()

        # Start client listener threads after latency measurement
        for conn, username in self.clients:
            threading.Thread(target=self.client_handler, args=(conn, username), daemon=True).start()

        self.broadcast("\n--- The quiz is starting in 3 seconds... ---")
        time.sleep(3)
        self.run_quiz()

    # ── Latency measurement ──────────────────────────────────────────────────
    def measure_latency(self):
        print("\nMeasuring network latency for all players...")
        for conn, username in self.clients:
            rtts = []
            try:
                for _ in range(LATENCY_PINGS):
                    ping_time = time.time()
                    self.send_msg(conn, {"type": "ping"})
                    resp = self.recv_one_msg(conn, username, timeout=5)
                    pong_time = time.time()
                    if resp and resp.get("type") == "pong":
                        rtts.append(pong_time - ping_time)
                    time.sleep(0.1)
            except Exception as e:
                print(f"  Latency measurement failed for {username}: {e}")

            if rtts:
                avg_rtt = sum(rtts) / len(rtts)
                self.latencies[username] = avg_rtt / 2  # one-way latency
            else:
                self.latencies[username] = 0

        # Display and broadcast latency results
        latency_msg = "\n--- Network Latency Results ---\n"
        for username, latency in self.latencies.items():
            latency_msg += f"  {username}: {latency*1000:.1f} ms (one-way)\n"
        self.broadcast(latency_msg)
        print(latency_msg)

    # ── Client listener thread ───────────────────────────────────────────────
    def client_handler(self, conn, username):
        while True:
            try:
                msg = self.recv_one_msg(conn, username)
                if msg is None:
                    break

                answer = msg.get("data") or msg.get("answer", "")

                # Only record the FIRST answer if we are currently accepting them
                if self.accepting_answers and username not in self.current_responses and answer:
                    self.answer_timestamps[username] = time.time()
                    self.current_responses[username] = answer
            except Exception:
                break

    # ── Quiz loop ────────────────────────────────────────────────────────────
    def run_quiz(self):
        for idx, q in enumerate(self.questions):
            self.current_responses.clear()
            self.answer_timestamps.clear()

            # Formulate question string
            q_text = f"\n--- Question {idx + 1}/{len(self.questions)} ---\n"
            q_text += q["question"] + "\n"
            for i, opt in enumerate(q["options"]):
                q_text += f"{i+1}. {opt}\n"
            q_text += f"\nYou have {TIME_LIMIT} seconds to answer! Type the option number.\n"

            self.question_send_time = time.time()
            self.broadcast(q_text)
            self.accepting_answers = True

            # Wait for replies within the time limit
            time.sleep(TIME_LIMIT)

            self.accepting_answers = False

            # Evaluate responses
            correct_answer = q["answer"]
            correct_idx = str(q["options"].index(correct_answer) + 1)

            self.broadcast(f"\nTime's up! The correct answer was: {correct_answer}")

            for username, response in self.current_responses.items():
                if response.lower() == correct_answer.lower() or response == correct_idx:
                    self.scores[username] += 10

            # Record response times for this question
            for _, uname in self.clients:
                if uname in self.answer_timestamps:
                    raw_time = self.answer_timestamps[uname] - self.question_send_time
                    adjusted = max(0, raw_time - self.latencies.get(uname, 0))
                    self.response_times[uname].append(raw_time)
                    self.adjusted_times[uname].append(adjusted)
                else:
                    self.response_times[uname].append(TIME_LIMIT)
                    self.adjusted_times[uname].append(TIME_LIMIT)

            self.send_leaderboard()
            time.sleep(5)  # Pause before next question

        self.end_quiz()

    def send_leaderboard(self):
        leaderboard = "\n--- Current Leaderboard ---\n"
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)

        for rank, (user, score) in enumerate(sorted_scores, 1):
            leaderboard += f"{rank}. {user}: {score} points\n"

        self.broadcast(leaderboard)

    def end_quiz(self):
        final_msg = "\n=== QUIZ OVER ===\nFinal Rankings:\n"
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)

        for rank, (user, score) in enumerate(sorted_scores, 1):
            final_msg += f"{rank}. {user}: {score} points\n"

        if sorted_scores:
            final_msg += f"\nWinner: {sorted_scores[0][0]}!\n"

        self.broadcast(final_msg)
        time.sleep(1)

        # Send fairness evaluation report
        report = self.generate_fairness_report()
        self.broadcast(report)
        print("Quiz finished. Closing connections.")

        # Give clients time to receive the final message before closing
        time.sleep(2)

        for conn, _ in self.clients:
            try:
                conn.close()
            except Exception:
                pass
        self.server_socket.close()

    def generate_fairness_report(self):
        """Generate a comprehensive latency and fairness evaluation report."""
        report = "\n" + "=" * 50 + "\n"
        report += "   LATENCY & FAIRNESS EVALUATION REPORT\n"
        report += "=" * 50 + "\n"

        # 1. Latency Summary
        report += "\n[1] Network Latency (One-Way)\n"
        report += "-" * 35 + "\n"
        for user in self.scores:
            lat = self.latencies.get(user, 0)
            report += f"  {user:15s} : {lat*1000:6.1f} ms\n"

        if self.latencies:
            lat_vals = list(self.latencies.values())
            max_lat = max(lat_vals)
            min_lat = min(lat_vals)
            spread = (max_lat - min_lat) * 1000
            report += f"  {'Spread':15s} : {spread:6.1f} ms\n"

        # 2. Per-Player Response Time Stats
        report += "\n[2] Response Times (avg per player)\n"
        report += "-" * 35 + "\n"
        report += f"  {'Player':15s} | {'Raw (ms)':>10s} | {'Adjusted (ms)':>14s}\n"
        report += f"  {'-'*15}-+-{'-'*10}-+-{'-'*14}\n"

        avg_adjusted = {}
        for user in self.scores:
            raw_list = self.response_times.get(user, [])
            adj_list = self.adjusted_times.get(user, [])
            if raw_list:
                avg_raw = (sum(raw_list) / len(raw_list)) * 1000
                avg_adj = (sum(adj_list) / len(adj_list)) * 1000
                avg_adjusted[user] = avg_adj
                report += f"  {user:15s} | {avg_raw:10.1f} | {avg_adj:14.1f}\n"
            else:
                report += f"  {user:15s} | {'N/A':>10s} | {'N/A':>14s}\n"

        # 3. Jain's Fairness Index
        report += "\n[3] Fairness Index (Jain's)\n"
        report += "-" * 35 + "\n"
        if avg_adjusted and len(avg_adjusted) > 1:
            values = list(avg_adjusted.values())
            n = len(values)
            sum_x = sum(values)
            sum_x2 = sum(v * v for v in values)
            if sum_x2 > 0:
                jfi = (sum_x ** 2) / (n * sum_x2)
            else:
                jfi = 1.0
            report += f"  JFI = {jfi:.4f}  (1.0 = perfectly fair)\n"
            if jfi >= 0.95:
                report += "  Verdict: FAIR - minimal latency bias\n"
            elif jfi >= 0.80:
                report += "  Verdict: MODERATE - some latency advantage exists\n"
            else:
                report += "  Verdict: UNFAIR - significant latency disparity\n"
        else:
            report += "  Not enough data to compute fairness index.\n"

        # 4. Per-Question Breakdown
        report += "\n[4] Per-Question Response Times (ms)\n"
        report += "-" * 35 + "\n"
        num_q = len(self.questions)
        users = list(self.scores.keys())
        header = f"  {'Q#':>3s}"
        for u in users:
            header += f" | {u:>10s}"
        report += header + "\n"
        for i in range(num_q):
            row = f"  {i+1:3d}"
            for u in users:
                rt_list = self.response_times.get(u, [])
                if i < len(rt_list):
                    row += f" | {rt_list[i]*1000:10.1f}"
                else:
                    row += f" | {'--':>10s}"
            report += row + "\n"

        report += "\n" + "=" * 50 + "\n"
        print(report)
        return report


if __name__ == "__main__":
    # Parse optional command-line argument for number of players
    players = NUM_PLAYERS
    if len(sys.argv) > 1:
        try:
            players = int(sys.argv[1])
            if players < 1:
                players = NUM_PLAYERS
        except ValueError:
            print(f"Usage: python server.py [num_players]  (default: {NUM_PLAYERS})")
            sys.exit(1)

    server = QuizServer(num_players=players)
    server.start()

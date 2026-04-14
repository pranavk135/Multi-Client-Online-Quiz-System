import socket
import threading
import json
import time
import ssl
import math

HOST = "127.0.0.1"
PORT = 5000
NUM_PLAYERS = 3
TIME_LIMIT = 10
LATENCY_PINGS = 3  # Number of pings to average for latency measurement

class QuizServer:
    def __init__(self):
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
        
        try:
            with open("questions.json", "r") as f:
                self.questions = json.load(f)
        except FileNotFoundError:
            print("questions.json not found! Exiting.")
            exit(1)

    def start(self):
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen()
        print(f"Server started on {HOST}:{PORT}. Waiting for {NUM_PLAYERS} players...")

        while len(self.clients) < NUM_PLAYERS:
            conn, addr = self.server_socket.accept()
            # Expect the first message to be the username
            username = conn.recv(1024).decode('utf-8').strip()
            
            if not username or username in self.scores:
                conn.send("Invalid or duplicate username. Disconnecting.\n".encode())
                conn.close()
                continue
                
            self.clients.append((conn, username))
            self.scores[username] = 0
            self.response_times[username] = []
            self.adjusted_times[username] = []
            print(f"{username} joined from {addr}")
            self.broadcast(f"{username} has joined the quiz! ({len(self.clients)}/{NUM_PLAYERS})\n")

        print("All players connected.")
        self.broadcast("\n--- All players connected! Measuring network latency... ---\n")
        self.measure_latency()

        # Start client listener threads after latency measurement
        for conn, username in self.clients:
            threading.Thread(target=self.client_handler, args=(conn, username), daemon=True).start()

        self.broadcast("\n--- The quiz is starting in 3 seconds... ---\n")
        time.sleep(3)
        self.run_quiz()

    def measure_latency(self):
        """Measure network latency for each client using multiple ping-pong rounds."""
        print("Measuring network latency for all players...")
        for conn, username in self.clients:
            rtts = []
            try:
                conn.settimeout(5)
                for _ in range(LATENCY_PINGS):
                    ping_time = time.time()
                    conn.send("__PING__".encode())
                    response = conn.recv(1024).decode('utf-8').strip()
                    pong_time = time.time()
                    if response == "__PONG__":
                        rtts.append(pong_time - ping_time)
                    time.sleep(0.1)  # Small gap between pings
                conn.settimeout(None)
            except Exception as e:
                print(f"Latency measurement failed for {username}: {e}")
                conn.settimeout(None)

            if rtts:
                avg_rtt = sum(rtts) / len(rtts)
                self.latencies[username] = avg_rtt / 2  # one-way latency
            else:
                self.latencies[username] = 0

        # Broadcast latency results
        latency_msg = "\n--- Network Latency Results ---\n"
        for username, latency in self.latencies.items():
            latency_msg += f"  {username}: {latency*1000:.1f} ms (one-way)\n"
        self.broadcast(latency_msg)
        print(latency_msg)

    def client_handler(self, conn, username):
        while True:
            try:
                msg = conn.recv(1024).decode('utf-8').strip()
                if not msg:
                    break
                
                # Only record the FIRST answer if we are currently accepting them
                if self.accepting_answers and username not in self.current_responses:
                    self.answer_timestamps[username] = time.time()
                    self.current_responses[username] = msg
            except:
                break

    def broadcast(self, message):
        for conn, _ in self.clients:
            try:
                conn.send(message.encode())
            except:
                pass

    def run_quiz(self):
        for idx, q in enumerate(self.questions):
            self.current_responses.clear()
            self.answer_timestamps.clear()
            
            # Formulate question string
            q_text = f"\n--- Question {idx + 1}/{len(self.questions)} ---\n"
            q_text += q["question"] + "\n"
            for i, opt in enumerate(q["options"]):
                q_text += f"{i+1}. {opt}\n"
            q_text += f"\nYou have {TIME_LIMIT} seconds to answer! Type the exact option text or number.\n"
            
            self.question_send_time = time.time()
            self.broadcast(q_text)
            self.accepting_answers = True
            
            # Wait for replies within the time limit
            time.sleep(TIME_LIMIT)
            
            self.accepting_answers = False
            
            # Evaluate responses
            correct_answer = q["answer"]
            correct_idx = str(q["options"].index(correct_answer) + 1)
            
            self.broadcast(f"\nTime's up! The correct answer was: {correct_answer}\n")
            
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
                    # Player did not answer — record TIME_LIMIT as response time
                    self.response_times[uname].append(TIME_LIMIT)
                    self.adjusted_times[uname].append(TIME_LIMIT)
                    
            self.send_leaderboard()
            time.sleep(5) # Pause before next question

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
        self.broadcast(self.generate_fairness_report())
        print("Quiz finished. Closing connections.")
        
        # Give clients time to receive the final message before closing
        time.sleep(2)
        
        for conn, _ in self.clients:
            try:
                conn.close()
            except:
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
                report += "  Verdict: ✓ FAIR — minimal latency bias\n"
            elif jfi >= 0.80:
                report += "  Verdict: ~ MODERATE — some latency advantage exists\n"
            else:
                report += "  Verdict: ✗ UNFAIR — significant latency disparity\n"
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
                    row += f" | {'—':>10s}"
            report += row + "\n"

        report += "\n" + "=" * 50 + "\n"
        print(report)
        return report

if __name__ == "__main__":
    server = QuizServer()
    server.start()

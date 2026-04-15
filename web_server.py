import json
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Dict
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

NUM_PLAYERS   = 2       # Default: 2 players (override with --players N)
TIME_LIMIT    = 10
LATENCY_PINGS = 3

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_ips: Dict[str, str] = {}
        self.scores: Dict[str, int] = {}
        self.current_responses: Dict[str, str] = {}
        self.accepting_answers: bool = False
        self.quiz_started: bool = False
        self.latencies: Dict[str, float] = {}
        self.response_times: Dict[str, list] = {}
        self.adjusted_times: Dict[str, list] = {}
        self.answer_timestamps: Dict[str, float] = {}
        self.question_send_time: float = 0
        self.pong_received: Dict[str, float] = {}

        try:
            with open("questions.json", "r") as f:
                self.questions = json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions.json: {e}")
            self.questions = []

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()

        client_ip   = websocket.client.host
        client_port = websocket.client.port

        if username in self.active_connections:
            await websocket.send_json({"type": "error", "message": "Username already taken."})
            await websocket.close()
            return False

        if self.quiz_started:
            await websocket.send_json({"type": "error", "message": "Quiz already in progress."})
            await websocket.close()
            return False

        self.active_connections[username] = websocket
        self.client_ips[username] = f"{client_ip}:{client_port}"
        self.scores[username] = 0
        self.response_times[username] = []
        self.adjusted_times[username] = []

        logger.info(
            f"[CONNECT]  {username:15s}  IP: {client_ip}:{client_port}  "
            f"({len(self.active_connections)}/{NUM_PLAYERS})"
        )

        await self.broadcast({
            "type": "system",
            "message": f"{username} joined! ({len(self.active_connections)}/{NUM_PLAYERS})"
        })
        await self.broadcast({
            "type": "lobby_update",
            "players": list(self.active_connections.keys()),
            "required": NUM_PLAYERS
        })

        if len(self.active_connections) == NUM_PLAYERS and not self.quiz_started:
            asyncio.create_task(self.start_quiz())

        return True

    def disconnect(self, username: str):
        ip = self.client_ips.pop(username, "unknown")
        self.active_connections.pop(username, None)

        if not self.quiz_started:
            self.scores.pop(username, None)
            self.response_times.pop(username, None)
            self.adjusted_times.pop(username, None)
            logger.info(
                f"[DISCONNECT] {username} ({ip}) left lobby. "
                f"Players: {len(self.active_connections)}/{NUM_PLAYERS}"
            )
            asyncio.create_task(self.broadcast({
                "type": "lobby_update",
                "players": list(self.active_connections.keys()),
                "required": NUM_PLAYERS
            }))
            asyncio.create_task(self.broadcast({
                "type": "system",
                "message": f"{username} disconnected. "
                           f"Waiting... ({len(self.active_connections)}/{NUM_PLAYERS})"
            }))
        else:
            logger.info(f"[DISCONNECT] {username} ({ip}) left mid-quiz.")

    async def broadcast(self, data: dict):
        dead = []
        for uname, conn in self.active_connections.items():
            try:
                await conn.send_json(data)
            except Exception:
                dead.append(uname)
        for uname in dead:
            self.disconnect(uname)

    async def start_quiz(self):
        self.quiz_started = True
        logger.info("=" * 52)
        logger.info("QUIZ STARTING")
        logger.info("Connected clients:")
        for uname, ip in self.client_ips.items():
            logger.info(f"  {uname:15s}  {ip}")
        logger.info("=" * 52)

        await self.broadcast({
            "type": "system",
            "message": "All players connected! Measuring network latency..."
        })
        await self.measure_latency()
        await self.broadcast({
            "type": "system",
            "message": "Latency measured! Quiz starts in 3 seconds..."
        })
        await asyncio.sleep(3)
        await self.run_quiz()

    async def measure_latency(self):
        logger.info("Measuring latency for all players...")
        for username, ws in list(self.active_connections.items()):
            rtts = []
            try:
                for _ in range(LATENCY_PINGS):
                    self.pong_received.pop(username, None)
                    ping_time = time.time()
                    await ws.send_json({"type": "ping"})
                    for _ in range(50):
                        if username in self.pong_received:
                            rtts.append(self.pong_received[username] - ping_time)
                            break
                        await asyncio.sleep(0.1)
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Latency ping failed for {username}: {e}")

            self.latencies[username] = (sum(rtts) / len(rtts) / 2) if rtts else 0

        logger.info("Latency results (one-way):")
        latency_data = []
        for uname, lat in self.latencies.items():
            ms = round(lat * 1000, 1)
            logger.info(f"  {uname:15s}  {ms} ms")
            latency_data.append({"username": uname, "latency_ms": ms})

        await self.broadcast({"type": "latency_results", "results": latency_data})

    async def run_quiz(self):
        for idx, q in enumerate(self.questions):
            self.current_responses.clear()
            self.answer_timestamps.clear()

            self.question_send_time = time.time()
            await self.broadcast({
                "type": "question",
                "number": idx + 1,
                "total": len(self.questions),
                "question": q["question"],
                "options": q["options"],
                "time_limit": TIME_LIMIT
            })
            logger.info(f"[Q{idx+1}] {q['question'][:70]}")

            self.accepting_answers = True
            for i in range(TIME_LIMIT, 0, -1):
                await self.broadcast({"type": "timer", "time_left": i})
                await asyncio.sleep(1)

            self.accepting_answers = False
            await self.broadcast({"type": "timer", "time_left": 0})

            correct_answer = q["answer"]
            correct_idx    = str(q["options"].index(correct_answer) + 1)

            await self.broadcast({
                "type": "answer_result",
                "correct_answer": correct_answer,
                "message": f"Time's up! Correct answer: {correct_answer}"
            })

            for uname, response in self.current_responses.items():
                if response.lower() == correct_answer.lower() or response == correct_idx:
                    self.scores[uname] += 10

            for uname in list(self.active_connections.keys()):
                if uname in self.answer_timestamps:
                    raw = self.answer_timestamps[uname] - self.question_send_time
                    adj = max(0, raw - self.latencies.get(uname, 0))
                    self.response_times[uname].append(raw)
                    self.adjusted_times[uname].append(adj)
                else:
                    self.response_times[uname].append(TIME_LIMIT)
                    self.adjusted_times[uname].append(TIME_LIMIT)

            await self.send_leaderboard()
            await asyncio.sleep(5)

        await self.end_quiz()

    async def send_leaderboard(self):
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        await self.broadcast({
            "type": "leaderboard",
            "scores": [{"username": k, "score": v} for k, v in sorted_scores]
        })

    async def end_quiz(self):
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        winner = sorted_scores[0][0] if sorted_scores else "None"

        await self.broadcast({
            "type": "quiz_over",
            "scores": [{"username": k, "score": v} for k, v in sorted_scores],
            "winner": winner
        })

        self.print_fairness_report()
        logger.info("Quiz finished. Resetting state.")

        self.quiz_started = False
        self.active_connections.clear()
        self.client_ips.clear()
        self.scores.clear()
        self.current_responses.clear()
        self.latencies.clear()
        self.response_times.clear()
        self.adjusted_times.clear()
        self.answer_timestamps.clear()

    def print_fairness_report(self):
        report  = "\n" + "=" * 52 + "\n"
        report += "      LATENCY & FAIRNESS EVALUATION REPORT\n"
        report += "=" * 52 + "\n"

        report += "\n[1] Client IPs\n" + "-" * 35 + "\n"
        for uname, ip in self.client_ips.items():
            report += f"  {uname:15s} : {ip}\n"

        report += "\n[2] Network Latency (One-Way)\n" + "-" * 35 + "\n"
        for uname in self.scores:
            lat = self.latencies.get(uname, 0)
            report += f"  {uname:15s} : {lat*1000:6.1f} ms\n"

        report += "\n[3] Avg Response Times\n" + "-" * 35 + "\n"
        report += f"  {'Player':15s} | {'Raw (ms)':>10s} | {'Adjusted (ms)':>13s}\n"
        avg_adjusted = {}
        for uname in self.scores:
            raw_list = self.response_times.get(uname, [])
            adj_list = self.adjusted_times.get(uname, [])
            if raw_list:
                avg_raw = (sum(raw_list) / len(raw_list)) * 1000
                avg_adj = (sum(adj_list) / len(adj_list)) * 1000
                avg_adjusted[uname] = avg_adj
                report += f"  {uname:15s} | {avg_raw:10.1f} | {avg_adj:13.1f}\n"

        report += "\n[4] Jain's Fairness Index\n" + "-" * 35 + "\n"
        if avg_adjusted and len(avg_adjusted) > 1:
            vals   = list(avg_adjusted.values())
            n      = len(vals)
            sum_x  = sum(vals)
            sum_x2 = sum(v * v for v in vals)
            jfi    = (sum_x ** 2) / (n * sum_x2) if sum_x2 > 0 else 1.0
            report += f"  JFI = {jfi:.4f}  (1.0 = perfectly fair)\n"
            if jfi >= 0.95:
                report += "  Verdict: FAIR - minimal latency bias\n"
            elif jfi >= 0.80:
                report += "  Verdict: MODERATE - some latency advantage exists\n"
            else:
                report += "  Verdict: UNFAIR - significant latency disparity\n"
        else:
            report += "  Not enough data.\n"

        report += "\n[5] Per-Question Response Times (ms)\n" + "-" * 35 + "\n"
        users  = list(self.scores.keys())
        header = f"  {'Q#':>3s}"
        for u in users:
            header += f" | {u:>12s}"
        report += header + "\n"
        for i in range(len(self.questions)):
            row = f"  {i+1:3d}"
            for u in users:
                rt_list = self.response_times.get(u, [])
                row += f" | {rt_list[i]*1000:12.1f}" if i < len(rt_list) else f" | {'—':>12s}"
            report += row + "\n"

        report += "\n" + "=" * 52 + "\n"
        print(report)


manager = ConnectionManager()

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    client_ip   = websocket.client.host
    client_port = websocket.client.port
    logger.info(f"[WS HANDSHAKE] {username} from {client_ip}:{client_port}")

    success = await manager.connect(websocket, username)
    if not success:
        return

    try:
        while True:
            data = await websocket.receive_text()

            try:
                msg = json.loads(data)
                if msg.get("type") == "pong":
                    manager.pong_received[username] = time.time()
                    continue
            except (json.JSONDecodeError, AttributeError):
                pass

            if manager.accepting_answers and username not in manager.current_responses:
                manager.answer_timestamps[username] = time.time()
                manager.current_responses[username] = data.strip()
                logger.info(f"[ANSWER] {username}: '{data.strip()}'")
                await websocket.send_json({"type": "ack", "message": "Answer received!"})

    except WebSocketDisconnect:
        manager.disconnect(username)
        logger.info(f"[DISCONNECT] {username} ({client_ip}:{client_port})")


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="QuizNet Web Server")
    parser.add_argument("--port", type=int, default=8443, help="Port to listen on (default: 8443)")
    parser.add_argument("--players", type=int, default=NUM_PLAYERS, help=f"Number of players (default: {NUM_PLAYERS})")
    args = parser.parse_args()

    NUM_PLAYERS = args.players

    print("=" * 55)
    print("  QUIZNET WEB SERVER — HTTPS/WSS (TLS)")
    print("=" * 55)
    print(f"  Port          : {args.port}")
    print(f"  Players needed: {NUM_PLAYERS}")
    print(f"  Open browser  : https://<SERVER_IP>:{args.port}")
    print("=" * 55)

    uvicorn.run(
        app,
        host="0.0.0.0",              # Listen on all interfaces for LAN
        port=args.port,
        ssl_keyfile="certs/key.pem",
        ssl_certfile="certs/cert.pem",
    )
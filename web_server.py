import json
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict, Any
import asyncio
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

# Quiz Engine variables
NUM_PLAYERS = 3
TIME_LIMIT = 10

LATENCY_PINGS = 3  # Number of pings to average for latency measurement

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.scores: Dict[str, int] = {}
        self.current_responses: Dict[str, str] = {}
        self.accepting_answers: bool = False
        self.quiz_started: bool = False

        # Latency & fairness tracking
        self.latencies: Dict[str, float] = {}            # username -> one-way latency (seconds)
        self.response_times: Dict[str, list] = {}        # username -> list of raw response times
        self.adjusted_times: Dict[str, list] = {}        # username -> list of latency-adjusted times
        self.answer_timestamps: Dict[str, float] = {}    # username -> timestamp when answer received
        self.question_send_time: float = 0               # timestamp when current question was sent
        self.pong_received: Dict[str, float] = {}        # username -> pong receive timestamp
        
        try:
            with open("questions.json", "r") as f:
                self.questions = json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions: {e}")
            self.questions = []

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        
        if username in self.active_connections or self.quiz_started:
            await websocket.send_json({"type": "error", "message": "Username already taken or quiz has started."})
            await websocket.close()
            return False

        self.active_connections[username] = websocket
        self.scores[username] = 0
        self.response_times[username] = []
        self.adjusted_times[username] = []
        logger.info(f"{username} connected. Total: {len(self.active_connections)}")
        
        # Broadcast player join
        await self.broadcast({
            "type": "system",
            "message": f"{username} has joined the quiz! ({len(self.active_connections)}/{NUM_PLAYERS})"
        })
        
        # Update waiting lobby UI
        await self.broadcast({
            "type": "lobby_update",
            "players": list(self.active_connections.keys()),
            "required": NUM_PLAYERS
        })

        if len(self.active_connections) == NUM_PLAYERS and not self.quiz_started:
            asyncio.create_task(self.start_quiz())
            
        return True

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]
        if username in self.scores and not self.quiz_started:
            del self.scores[username]
            # If they leave before quiz starts, notify others
            asyncio.create_task(self.broadcast({
                "type": "lobby_update",
                "players": list(self.active_connections.keys()),
                "required": NUM_PLAYERS
            }))
            asyncio.create_task(self.broadcast({
                "type": "system",
                "message": f"{username} disconnected."
            }))

    async def broadcast(self, data: dict):
        for connection in self.active_connections.values():
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")

    async def start_quiz(self):
        self.quiz_started = True
        logger.info("Starting quiz...")
        await self.broadcast({
            "type": "system",
            "message": "All players connected! Measuring network latency..."
        })
        await self.measure_latency()
        await self.broadcast({
            "type": "system",
            "message": "Latency measured! The quiz is starting in 3 seconds..."
        })
        await asyncio.sleep(3)
        await self.run_quiz()

    async def measure_latency(self):
        """Measure network latency for each client using WebSocket ping-pong."""
        logger.info("Measuring network latency for all players...")
        for username, ws in self.active_connections.items():
            rtts = []
            try:
                for _ in range(LATENCY_PINGS):
                    self.pong_received.pop(username, None)
                    ping_time = time.time()
                    await ws.send_json({"type": "ping"})
                    # Wait for pong (up to 5 seconds)
                    for _ in range(50):
                        if username in self.pong_received:
                            rtt = self.pong_received[username] - ping_time
                            rtts.append(rtt)
                            break
                        await asyncio.sleep(0.1)
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Latency measurement failed for {username}: {e}")

            if rtts:
                avg_rtt = sum(rtts) / len(rtts)
                self.latencies[username] = avg_rtt / 2  # one-way latency
            else:
                self.latencies[username] = 0

        # Broadcast latency results to all clients
        latency_data = []
        for username, latency in self.latencies.items():
            latency_data.append({"username": username, "latency_ms": round(latency * 1000, 1)})
        await self.broadcast({
            "type": "latency_results",
            "results": latency_data
        })
        logger.info(f"Latency results: {latency_data}")

    async def run_quiz(self):
        for idx, q in enumerate(self.questions):
            self.current_responses.clear()
            self.answer_timestamps.clear()
            
            # Send Question
            self.question_send_time = time.time()
            await self.broadcast({
                "type": "question",
                "number": idx + 1,
                "total": len(self.questions),
                "question": q["question"],
                "options": q["options"],
                "time_limit": TIME_LIMIT
            })
            
            self.accepting_answers = True
            
            # Timer wait
            for i in range(TIME_LIMIT, 0, -1):
                await self.broadcast({"type": "timer", "time_left": i})
                await asyncio.sleep(1)
                
            self.accepting_answers = False
            await self.broadcast({"type": "timer", "time_left": 0})
            
            # Evaluate responses
            correct_answer = q["answer"]
            correct_idx = str(q["options"].index(correct_answer) + 1)
            
            await self.broadcast({
                "type": "answer_result",
                "correct_answer": correct_answer,
                "message": f"Time's up! The correct answer was: {correct_answer}"
            })
            
            for username, response in self.current_responses.items():
                if response.lower() == correct_answer.lower() or response == correct_idx:
                    self.scores[username] += 10

            # Record response times for this question
            for uname in list(self.active_connections.keys()):
                if uname in self.answer_timestamps:
                    raw_time = self.answer_timestamps[uname] - self.question_send_time
                    adjusted = max(0, raw_time - self.latencies.get(uname, 0))
                    self.response_times[uname].append(raw_time)
                    self.adjusted_times[uname].append(adjusted)
                else:
                    self.response_times[uname].append(TIME_LIMIT)
                    self.adjusted_times[uname].append(TIME_LIMIT)
                    
            await self.send_leaderboard()
            await asyncio.sleep(5)  # Pause before next question

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

        # Print fairness report to server terminal only
        self.print_fairness_report()
        logger.info("Quiz finished.")
        # Reset state for a new game
        self.quiz_started = False
        self.active_connections.clear()
        self.scores.clear()
        self.current_responses.clear()
        self.latencies.clear()
        self.response_times.clear()
        self.adjusted_times.clear()
        self.answer_timestamps.clear()

    def print_fairness_report(self):
        """Print fairness evaluation report to server terminal."""
        report = "\n" + "=" * 50 + "\n"
        report += "   LATENCY & FAIRNESS EVALUATION REPORT\n"
        report += "=" * 50 + "\n"

        report += "\n[1] Network Latency (One-Way)\n" + "-" * 35 + "\n"
        for user in self.scores:
            lat = self.latencies.get(user, 0)
            report += f"  {user:15s} : {lat*1000:6.1f} ms\n"

        report += "\n[2] Avg Response Times\n" + "-" * 35 + "\n"
        report += f"  {'Player':15s} | {'Raw (ms)':>10s} | {'Adjusted (ms)':>14s}\n"
        avg_adjusted = {}
        for user in self.scores:
            raw_list = self.response_times.get(user, [])
            adj_list = self.adjusted_times.get(user, [])
            if raw_list:
                avg_raw = (sum(raw_list) / len(raw_list)) * 1000
                avg_adj = (sum(adj_list) / len(adj_list)) * 1000
                avg_adjusted[user] = avg_adj
                report += f"  {user:15s} | {avg_raw:10.1f} | {avg_adj:14.1f}\n"

        report += "\n[3] Jain's Fairness Index\n" + "-" * 35 + "\n"
        if avg_adjusted and len(avg_adjusted) > 1:
            values = list(avg_adjusted.values())
            n = len(values)
            sum_x = sum(values)
            sum_x2 = sum(v * v for v in values)
            jfi = (sum_x ** 2) / (n * sum_x2) if sum_x2 > 0 else 1.0
            report += f"  JFI = {jfi:.4f}  (1.0 = perfectly fair)\n"
            if jfi >= 0.95:
                report += "  Verdict: FAIR - minimal latency bias\n"
            elif jfi >= 0.80:
                report += "  Verdict: MODERATE - some latency advantage exists\n"
            else:
                report += "  Verdict: UNFAIR - significant latency disparity\n"

        report += "\n[4] Per-Question Response Times (ms)\n" + "-" * 35 + "\n"
        users = list(self.scores.keys())
        header = f"  {'Q#':>3s}"
        for u in users:
            header += f" | {u:>10s}"
        report += header + "\n"
        for i in range(len(self.questions)):
            row = f"  {i+1:3d}"
            for u in users:
                rt_list = self.response_times.get(u, [])
                row += f" | {rt_list[i]*1000:10.1f}" if i < len(rt_list) else f" | {'—':>10s}"
            report += row + "\n"

        report += "\n" + "=" * 50 + "\n"
        print(report)

manager = ConnectionManager()

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    success = await manager.connect(websocket, username)
    if not success:
        return
        
    try:
        while True:
            data = await websocket.receive_text()

            # Try to parse as JSON (for pong messages)
            try:
                msg = json.loads(data)
                if msg.get("type") == "pong":
                    manager.pong_received[username] = time.time()
                    continue
            except (json.JSONDecodeError, AttributeError):
                pass

            # Handle as quiz answer (only accept the first answer per question)
            if manager.accepting_answers and username not in manager.current_responses:
                manager.answer_timestamps[username] = time.time()
                manager.current_responses[username] = data.strip()
                await websocket.send_json({"type": "ack", "message": "Answer received!"})
    except WebSocketDisconnect:
        manager.disconnect(username)
        logger.info(f"{username} disconnected.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=443,
        ssl_keyfile="certs/key.pem",
        ssl_certfile="certs/cert.pem",
    )
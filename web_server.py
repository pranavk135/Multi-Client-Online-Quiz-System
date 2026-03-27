import json
import logging
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

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.scores: Dict[str, int] = {}
        self.current_responses: Dict[str, str] = {}
        self.accepting_answers: bool = False
        self.quiz_started: bool = False
        
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
            "message": "All players connected! The quiz is starting in 3 seconds..."
        })
        await asyncio.sleep(3)
        await self.run_quiz()

    async def run_quiz(self):
        for idx, q in enumerate(self.questions):
            self.current_responses.clear()
            
            # Send Question
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
        logger.info("Quiz finished.")
        # Reset state for a new game
        self.quiz_started = False
        self.active_connections.clear()
        self.scores.clear()
        self.current_responses.clear()

manager = ConnectionManager()

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    success = await manager.connect(websocket, username)
    if not success:
        return
        
    try:
        while True:
            data = await websocket.receive_text()
            if manager.accepting_answers:
                # Store the user's answer
                manager.current_responses[username] = data.strip()
                # Acknowledge receipt back to the specific user
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

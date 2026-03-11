import socket
import threading
import json
import time

HOST = "127.0.0.1"
PORT = 5000
NUM_PLAYERS = 3
TIME_LIMIT = 10

class QuizServer:
    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = []
        self.scores = {}
        self.current_responses = {}
        self.accepting_answers = False
        
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
            print(f"{username} joined from {addr}")
            self.broadcast(f"{username} has joined the quiz! ({len(self.clients)}/{NUM_PLAYERS})\n")
            
            # Start client listener thread
            threading.Thread(target=self.client_handler, args=(conn, username), daemon=True).start()

        print("All players connected. Starting quiz...")
        self.broadcast("\n--- All players connected! The quiz is starting in 3 seconds... ---\n")
        time.sleep(3)
        self.run_quiz()

    def client_handler(self, conn, username):
        while True:
            try:
                msg = conn.recv(1024).decode('utf-8').strip()
                if not msg:
                    break
                
                # Only record answers if we are currently accepting them
                if self.accepting_answers:
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
            
            # Formulate question string
            q_text = f"\n--- Question {idx + 1}/{len(self.questions)} ---\n"
            q_text += q["question"] + "\n"
            for i, opt in enumerate(q["options"]):
                q_text += f"{i+1}. {opt}\n"
            q_text += f"\nYou have {TIME_LIMIT} seconds to answer! Type the exact option text or number.\n"
            
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
        print("Quiz finished. Closing connections.")
        
        # Give clients time to receive the final message before closing
        time.sleep(1)
        
        for conn, _ in self.clients:
            try:
                conn.close()
            except:
                pass
        self.server_socket.close()

if __name__ == "__main__":
    server = QuizServer()
    server.start()

let ws;
let username = "";

// Element References
const loginScreen = document.getElementById("login-screen");
const lobbyScreen = document.getElementById("lobby-screen");
const quizScreen = document.getElementById("quiz-screen");
const leaderboardScreen = document.getElementById("leaderboard-screen");
const gameOverScreen = document.getElementById("game-over-screen");

const usernameInput = document.getElementById("username-input");
const joinBtn = document.getElementById("join-btn");
const loginError = document.getElementById("login-error");

const lobbyPlayers = document.getElementById("lobby-players");
const lobbyStatus = document.getElementById("lobby-status");

const questionCounter = document.getElementById("question-counter");
const timerEl = document.getElementById("timer");
const questionText = document.getElementById("question-text");
const optionsContainer = document.getElementById("options-container");
const answerInput = document.getElementById("answer-input");
const submitBtn = document.getElementById("submit-answer-btn");
const ackMessage = document.getElementById("ack-message");
const quizMessage = document.getElementById("quiz-message");

const leaderboardList = document.getElementById("leaderboard-list");
const finalLeaderboard = document.getElementById("final-leaderboard");
const winnerText = document.getElementById("winner-text");

function showScreen(screenEl) {
    document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
    screenEl.classList.add('active');
}

joinBtn.addEventListener("click", () => {
    username = usernameInput.value.trim();
    if (!username) {
        loginError.textContent = "Please enter a username.";
        return;
    }
    
    // Connect to WebSocket using wss (secure) if secure page, or ws if local testing
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${encodeURIComponent(username)}`);
    
    ws.onopen = () => {
        loginError.textContent = "";
        showScreen(lobbyScreen);
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };
    
    ws.onclose = () => {
        if(loginScreen.classList.contains('active')){
           loginError.textContent = "Could not connect to server.";
        } else {
           alert("Disconnected from server.");
           location.reload();
        }
    };
});

// Allow Enter key to submit login
usernameInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") joinBtn.click();
});

// Allow Enter key to submit answer
answerInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") submitBtn.click();
});

submitBtn.addEventListener("click", () => {
    const answer = answerInput.value.trim();
    if (answer && ws.readyState === WebSocket.OPEN) {
        ws.send(answer);
        answerInput.value = "";
    }
});

function handleServerMessage(data) {
    switch (data.type) {
        case "error":
            loginError.textContent = data.message;
            ws.close();
            break;
            
        case "system":
            if (lobbyScreen.classList.contains('active')) {
                lobbyStatus.textContent = data.message;
            } else {
                quizMessage.textContent = data.message;
            }
            break;
            
        case "lobby_update":
            lobbyPlayers.innerHTML = "";
            data.players.forEach(p => {
                const badge = document.createElement("span");
                badge.className = "player-badge";
                badge.textContent = p;
                lobbyPlayers.appendChild(badge);
            });
            break;
            
        case "question":
            showScreen(quizScreen);
            ackMessage.textContent = "";
            quizMessage.textContent = "";
            answerInput.value = "";
            answerInput.focus();
            
            questionCounter.textContent = `Question ${data.number}/${data.total}`;
            questionText.textContent = data.question;
            timerEl.textContent = `${data.time_limit}s`;
            
            optionsContainer.innerHTML = "";
            data.options.forEach((opt, idx) => {
                const div = document.createElement("div");
                div.className = "option-card";
                div.textContent = `${idx + 1}. ${opt}`;
                optionsContainer.appendChild(div);
            });
            break;
            
        case "timer":
            timerEl.textContent = `${data.time_left}s`;
            if (data.time_left <= 3) {
                timerEl.style.color = "var(--error)";
            } else {
                timerEl.style.color = "";
            }
            break;
            
        case "ack":
            ackMessage.textContent = data.message;
            break;
            
        case "answer_result":
            quizMessage.textContent = data.message;
            break;
            
        case "leaderboard":
            showScreen(leaderboardScreen);
            renderLeaderboard(leaderboardList, data.scores);
            break;
            
        case "quiz_over":
            showScreen(gameOverScreen);
            winnerText.textContent = `Winner: ${data.winner}!`;
            renderLeaderboard(finalLeaderboard, data.scores);
            break;
    }
}

function renderLeaderboard(container, scores) {
    container.innerHTML = "";
    scores.forEach((entry, idx) => {
        const row = document.createElement("div");
        row.className = "lb-row";
        
        const nameSpan = document.createElement("span");
        nameSpan.textContent = `${idx + 1}. ${entry.username}`;
        
        const scoreSpan = document.createElement("span");
        scoreSpan.textContent = entry.score;
        scoreSpan.style.color = "var(--accent)";
        
        row.appendChild(nameSpan);
        row.appendChild(scoreSpan);
        container.appendChild(row);
    });
}

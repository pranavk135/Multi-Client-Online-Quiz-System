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
        loginError.textContent = "Identity required for uplink.";
        return;
    }
    
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
           loginError.textContent = "Connection forcibly closed by remote host.";
        } else {
           alert("Link severed. Please reload.");
           location.reload();
        }
    };
});

usernameInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") joinBtn.click();
});

// Broadcasts selection to the socket and visually locks options
function selectOption(optionIndex) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        // Send the selected option index as a string
        ws.send(optionIndex.toString());
        
        // Disable all buttons and highlight the chosen one
        const buttons = optionsContainer.querySelectorAll('.option-btn');
        buttons.forEach((btn, idx) => {
            btn.disabled = true;
            if ((idx + 1) === optionIndex) {
                btn.classList.add('selected');
            }
        });
    }
}

function handleServerMessage(data) {
    switch (data.type) {
        case "error":
            loginError.textContent = data.message;
            if(ws) ws.close();
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
            
            questionCounter.textContent = `Question ${data.number}/${data.total}`;
            questionText.textContent = data.question;
            timerEl.textContent = `${data.time_limit}s`;
            
            // Generate interactive buttons
            optionsContainer.innerHTML = "";
            data.options.forEach((opt, idx) => {
                const btn = document.createElement("button");
                btn.className = "option-btn";
                
                // Simple letter label: A, B, C, D
                const labels = ["A", "B", "C", "D"];
                const prefixSpan = document.createElement("span");
                prefixSpan.style.fontWeight = "700";
                prefixSpan.style.marginRight = "12px";
                prefixSpan.style.color = "#4a90e2";
                prefixSpan.textContent = `${labels[idx]}.`;
                
                btn.appendChild(prefixSpan);
                btn.appendChild(document.createTextNode(opt));
                
                // Hook up click event
                btn.onclick = () => selectOption(idx + 1);
                optionsContainer.appendChild(btn);
            });
            break;
            
        case "timer":
            timerEl.textContent = `${data.time_left}s`;
            if (data.time_left <= 3) {
                timerEl.style.color = "var(--neon-pink)";
                timerEl.style.borderColor = "var(--neon-pink)";
                timerEl.style.boxShadow = "0 0 15px rgba(255, 0, 127, 0.5)";
            } else {
                timerEl.style.color = "";
                timerEl.style.borderColor = "";
                timerEl.style.boxShadow = "";
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
            winnerText.textContent = data.winner;
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
        nameSpan.textContent = `0${idx + 1}. ${entry.username}`;
        
        const scoreSpan = document.createElement("span");
        scoreSpan.textContent = entry.score;
        scoreSpan.style.color = "var(--neon-cyan)";
        
        row.appendChild(nameSpan);
        row.appendChild(scoreSpan);
        container.appendChild(row);
    });
}

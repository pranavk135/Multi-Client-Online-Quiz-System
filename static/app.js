let ws;
let username = "";

// ── Screen References ────────────────────────────────────────────────────────
const loginScreen       = document.getElementById("login-screen");
const lobbyScreen       = document.getElementById("lobby-screen");
const quizScreen        = document.getElementById("quiz-screen");
const leaderboardScreen = document.getElementById("leaderboard-screen");
const gameOverScreen    = document.getElementById("game-over-screen");

// ── Login ────────────────────────────────────────────────────────────────────
const usernameInput = document.getElementById("username-input");
const joinBtn       = document.getElementById("join-btn");
const loginError    = document.getElementById("login-error");

// ── Lobby ────────────────────────────────────────────────────────────────────
const lobbyPlayers  = document.getElementById("lobby-players");
const lobbySub      = document.getElementById("lobby-sub");
const lobbyBar      = document.getElementById("lobby-bar");
const lobbyCount    = document.getElementById("lobby-count");

// ── Quiz ─────────────────────────────────────────────────────────────────────
const qCounter      = document.getElementById("question-counter");
const timerEl       = document.getElementById("timer");
const questionText  = document.getElementById("question-text");
const optionsCont   = document.getElementById("options-container");
const ackMessage    = document.getElementById("ack-message");
const quizMessage   = document.getElementById("quiz-message");

// ── Leaderboard ──────────────────────────────────────────────────────────────
const lbList        = document.getElementById("leaderboard-list");
const lbResultMsg   = document.getElementById("lb-result-msg");

// ── Game Over ─────────────────────────────────────────────────────────────────
const finalLb       = document.getElementById("final-leaderboard");
const winnerText    = document.getElementById("winner-text");
const fairnessDiv   = document.getElementById("fairness-report");

// ── Helpers ──────────────────────────────────────────────────────────────
const LABELS = ["A", "B", "C", "D", "E"];

function showScreen(el) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    el.classList.add("active");
}

function renderLeaderboard(container, scores, highlightWinner = false) {
    container.innerHTML = "";
    scores.forEach((entry, idx) => {
        const row = document.createElement("div");
        row.className = "lb-row";

        const rank = document.createElement("span");
        rank.className = "lb-rank";
        rank.textContent = `#${idx + 1}`;

        const name = document.createElement("span");
        name.className = "lb-name";
        name.textContent = entry.username;

        const score = document.createElement("span");
        score.className = "lb-score";
        score.textContent = `${entry.score} pts`;

        row.appendChild(rank);
        row.appendChild(name);
        row.appendChild(score);
        container.appendChild(row);
    });
}

// ── Join / Connect ───────────────────────────────────────────────────────
function connect() {
    username = usernameInput.value.trim();
    if (!username) {
        loginError.textContent = "Please enter a username.";
        return;
    }

    loginError.textContent = "";
    joinBtn.textContent = "Connecting…";
    joinBtn.disabled = true;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${encodeURIComponent(username)}`);

    ws.onopen = () => {
        showScreen(lobbyScreen);
        joinBtn.textContent = "Connect →";
        joinBtn.disabled = false;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };

    ws.onerror = () => {
        loginError.textContent = "Could not connect to server.";
        joinBtn.textContent = "Connect →";
        joinBtn.disabled = false;
    };

    ws.onclose = () => {
        if (!loginScreen.classList.contains("active")) {
            // Don't reload on game over screen — let users see the results
            if (!gameOverScreen.classList.contains("active")) {
                alert("Connection closed. Please reload.");
                location.reload();
            }
        } else {
            joinBtn.textContent = "Connect →";
            joinBtn.disabled = false;
        }
    };
}

joinBtn.addEventListener("click", connect);
usernameInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") connect();
});

// ── Answer Selection ──────────────────────────────────────────────────────
function selectOption(index) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    ws.send(index.toString());

    // Lock all buttons and mark selected
    optionsCont.querySelectorAll(".option-btn").forEach((btn, i) => {
        btn.disabled = true;
        if (i + 1 === index) btn.classList.add("selected");
    });
}

// ── Fairness Report Renderer ─────────────────────────────────────────────
function renderFairnessReport(container, fairness) {
    if (!fairness) return;
    container.innerHTML = "";

    // Section 1: Latency
    const latSec = document.createElement("div");
    latSec.className = "fr-section";
    latSec.innerHTML = `<div class="fr-title">📡 Network Latency (One-Way)</div>`;
    const latTable = document.createElement("table");
    latTable.className = "fr-table";
    latTable.innerHTML = `<tr><th>Player</th><th>Latency</th></tr>`;
    fairness.latencies.forEach(l => {
        latTable.innerHTML += `<tr><td>${l.username}</td><td>${l.latency_ms} ms</td></tr>`;
    });
    latSec.appendChild(latTable);
    container.appendChild(latSec);

    // Section 2: Response Times
    if (fairness.response_stats && fairness.response_stats.length > 0) {
        const rtSec = document.createElement("div");
        rtSec.className = "fr-section";
        rtSec.innerHTML = `<div class="fr-title">⏱️ Avg Response Times</div>`;
        const rtTable = document.createElement("table");
        rtTable.className = "fr-table";
        rtTable.innerHTML = `<tr><th>Player</th><th>Raw (ms)</th><th>Adjusted (ms)</th></tr>`;
        fairness.response_stats.forEach(s => {
            rtTable.innerHTML += `<tr><td>${s.username}</td><td>${s.avg_raw_ms}</td><td>${s.avg_adjusted_ms}</td></tr>`;
        });
        rtSec.appendChild(rtTable);
        container.appendChild(rtSec);
    }

    // Section 3: Jain's Fairness Index
    const jfiSec = document.createElement("div");
    jfiSec.className = "fr-section";
    let jfiClass = "fr-verdict-fair";
    let jfiIcon = "✓";
    if (fairness.jfi !== null) {
        if (fairness.jfi < 0.80) { jfiClass = "fr-verdict-unfair"; jfiIcon = "✗"; }
        else if (fairness.jfi < 0.95) { jfiClass = "fr-verdict-moderate"; jfiIcon = "~"; }
    }
    jfiSec.innerHTML = `
        <div class="fr-title">⚖️ Fairness Index (Jain's)</div>
        <div class="fr-jfi">
            <span class="fr-jfi-value">${fairness.jfi !== null ? fairness.jfi : 'N/A'}</span>
            <span class="fr-jfi-label">/ 1.0</span>
        </div>
        <div class="${jfiClass}">${jfiIcon} ${fairness.verdict}</div>
    `;
    container.appendChild(jfiSec);

    // Section 4: Per-Question Breakdown
    if (fairness.per_question && fairness.per_question.length > 0 && fairness.players) {
        const pqSec = document.createElement("div");
        pqSec.className = "fr-section";
        pqSec.innerHTML = `<div class="fr-title">📊 Per-Question Response Times (ms)</div>`;
        const pqTable = document.createElement("table");
        pqTable.className = "fr-table";
        let header = `<tr><th>Q#</th>`;
        fairness.players.forEach(p => { header += `<th>${p}</th>`; });
        header += `</tr>`;
        pqTable.innerHTML = header;
        fairness.per_question.forEach(q => {
            let row = `<tr><td>${q.question}</td>`;
            fairness.players.forEach(p => {
                row += `<td>${q[p] !== null ? q[p] : '—'}</td>`;
            });
            row += `</tr>`;
            pqTable.innerHTML += row;
        });
        pqSec.appendChild(pqTable);
        container.appendChild(pqSec);
    }
}

// ── Message Handler ───────────────────────────────────────────────────────
function handleMessage(data) {
    switch (data.type) {

        case "ping":
            // Respond immediately with pong for latency measurement
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: "pong"}));
            }
            break;

        case "latency_results":
            // Show latency results briefly in lobby
            if (lobbyScreen.classList.contains("active")) {
                lobbySub.textContent = "Latency measured! Starting soon...";
            }
            break;

        case "error":
            loginError.textContent = data.message;
            if (ws) ws.close();
            showScreen(loginScreen);
            break;

        case "system":
            if (lobbyScreen.classList.contains("active")) {
                lobbySub.textContent = data.message;
            } else if (quizScreen.classList.contains("active")) {
                quizMessage.textContent = data.message;
            }
            break;

        case "lobby_update": {
            const players  = data.players;
            const required = data.required;

            // Rebuild chips
            lobbyPlayers.innerHTML = "";
            players.forEach(p => {
                const chip = document.createElement("span");
                chip.className = "player-chip";
                chip.textContent = p;
                lobbyPlayers.appendChild(chip);
            });

            // Progress bar
            const pct = Math.round((players.length / required) * 100);
            lobbyBar.style.width = `${pct}%`;
            lobbyCount.textContent = `${players.length} / ${required}`;
            break;
        }

        case "question":
            showScreen(quizScreen);
            ackMessage.textContent = "";
            quizMessage.textContent = "";

            qCounter.textContent   = `Question ${data.number} / ${data.total}`;
            questionText.textContent = data.question;
            timerEl.textContent    = `${data.time_limit}s`;
            timerEl.classList.remove("urgent");

            // Build option buttons
            optionsCont.innerHTML = "";
            data.options.forEach((opt, idx) => {
                const btn = document.createElement("button");
                btn.className = "option-btn";

                const key = document.createElement("span");
                key.className = "option-key";
                key.textContent = LABELS[idx];

                btn.appendChild(key);
                btn.appendChild(document.createTextNode(opt));
                btn.onclick = () => selectOption(idx + 1);
                optionsCont.appendChild(btn);
            });
            break;

        case "timer":
            timerEl.textContent = `${data.time_left}s`;
            if (data.time_left <= 3) {
                timerEl.classList.add("urgent");
            } else {
                timerEl.classList.remove("urgent");
            }
            break;

        case "ack":
            ackMessage.textContent = "✓ " + data.message;
            break;

        case "answer_result":
            quizMessage.textContent = data.message;
            break;

        case "leaderboard":
            showScreen(leaderboardScreen);
            lbResultMsg.textContent = "Scores after this round:";
            renderLeaderboard(lbList, data.scores);
            break;

        case "quiz_over":
            showScreen(gameOverScreen);
            winnerText.textContent = data.winner;
            renderLeaderboard(finalLb, data.scores);
            break;

        case "fairness_report":
            // Render the fairness report on the game over screen
            if (fairnessDiv && data.fairness) {
                renderFairnessReport(fairnessDiv, data.fairness);
            }
            break;
    }
}
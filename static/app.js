// NEXUS BINGO - Frontend JavaScript (IMPROVED)
// Features: Voice calling, BINGO button, fast gameplay, straight line patterns

const API_BASE = '';
let tg = window.Telegram?.WebApp;
let currentUser = null;
let currentRoom = null;
let selectedCartelaIds = [];
let allCartelas = [];
let gamePollInterval = null;
let currentCartelaPage = 1;

// Voice calling state
let voiceEnabled = true;
let lastCall = null;
let hasShownBingo = false;
let isEliminated = false;  // NEW: Track elimination

// Stake levels
const STAKE_LEVELS = [10, 25, 50, 100, 250, 500];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    if (tg) {
        tg.expand();
        tg.ready();
        tg.setHeaderColor('#0f0f23');
    }
    initAuth();
    loadProfile();
    showStakeSelector();
});

// Auth
function getAuthHeaders() {
    if (tg?.initData) {
        return { 'X-Telegram-Init-Data': tg.initData };
    }
    return {};
}

async function initAuth() {
    try {
        const res = await fetch(`${API_BASE}/webapp`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (data.user) {
            currentUser = data.user;
            document.getElementById('balance').textContent = `💰 ${data.user.balance.toFixed(0)} ETB`;
        }
    } catch (e) {
        showToast('Auth failed. Open via Telegram.');
    }
}

// Tabs
function showTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    ['rooms', 'game', 'profile'].forEach(t => {
        document.getElementById(`tab-${t}`).classList.toggle('hidden', t !== tab);
    });
    if (tab === 'rooms') showStakeSelector();
    if (tab === 'profile') loadProfile();
}

// ============================================================
// VOICE CALLING (FIXED)
// ============================================================
function speakNumber(call) {
    if (!voiceEnabled || !call) return;
    const letter = call.charAt(0);
    const number = call.slice(1);
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(`${letter} ${number}`);
    utterance.rate = 0.85;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    utterance.lang = 'en-US';
    speechSynthesis.speak(utterance);
}

function stopVoice() {
    speechSynthesis.cancel();
}

function toggleVoice() {
    voiceEnabled = !voiceEnabled;
    showToast(voiceEnabled ? '🔊 Voice ON' : '🔇 Voice OFF');
    const btn = document.getElementById('voice-btn');
    if (btn) btn.textContent = voiceEnabled ? '🔊 ON' : '🔇 OFF';
    if (!voiceEnabled) stopVoice();
}

// ============================================================
// STAKE SELECTOR
// ============================================================
function showStakeSelector() {
    const list = document.getElementById('rooms-list');
    list.innerHTML = `
        <div class="section">
            <div class="section-title">🎯 Choose Your Stake</div>
            <div style="font-size: 13px; color: #8892b0; margin-bottom: 16px; text-align: center;">
                Pick a stake level. Game starts instantly with bots!<br>
                <span style="color: #38ef7d;">⚡ No waiting — play now!</span>
            </div>
            <div class="stake-grid">
                ${STAKE_LEVELS.map(stake => `
                    <div class="stake-card" onclick="joinRoomByStake(${stake})">
                        <div class="stake-amount">${stake} ETB</div>
                        <div class="stake-label">Quick Match</div>
                        <div class="stake-players" id="stake-count-${stake}">Checking...</div>
                    </div>
                `).join('')}
            </div>
        </div>
        <div class="section">
            <div class="section-title">⚙️ Options</div>
            <button class="btn btn-secondary" onclick="openCreateRoom()">🏠 Create Private Room</button>
            <button class="btn btn-secondary" onclick="openJoinByCode()">🔑 Join by Code</button>
            <button class="btn btn-secondary" id="voice-btn" onclick="toggleVoice()">🔊 Voice ON</button>
        </div>
    `;
    loadStakeCounts();
}

async function loadStakeCounts() {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/stake-counts`, { headers: getAuthHeaders() });
        const counts = await res.json();
        STAKE_LEVELS.forEach(stake => {
            const el = document.getElementById(`stake-count-${stake}`);
            if (el) {
                const count = counts[stake] || 0;
                el.textContent = count > 0 ? `👥 ${count} waiting` : '🎮 Join now';
            }
        });
    } catch (e) {
        STAKE_LEVELS.forEach(stake => {
            const el = document.getElementById(`stake-count-${stake}`);
            if (el) el.textContent = '🎮 Join now';
        });
    }
}

async function joinRoomByStake(stake) {
    const cartelas = prompt('How many cartelas? (1-3)', '1');
    if (!cartelas) return;
    const numCartelas = parseInt(cartelas);
    if (numCartelas < 1 || numCartelas > 3) {
        showToast('Cartelas must be 1-3');
        return;
    }
    showToast(`🎮 Joining ${stake} ETB room...`);
    try {
        const res = await fetch(`${API_BASE}/api/rooms/join-by-stake`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ stake: stake, cartelas: numCartelas })
        });
        const data = await res.json();
        if (data.error) { 
            showToast(data.error); 
            return; 
        }
        showToast(`✅ Joined ${stake} ETB room!`);
        enterRoom(data.room_id);
    } catch (e) {
        showToast('Failed to join room. Try again.');
    }
}

// ============================================================
// GAME (IMPROVED)
// ============================================================
function enterRoom(roomId) {
    currentRoom = roomId;
    hasShownBingo = false;
    isEliminated = false;  // Reset
    lastCall = null;
    stopVoice();

    document.querySelectorAll('.tab')[1].click();
    document.getElementById('game-active').classList.remove('hidden');
    document.getElementById('game-inactive').classList.add('hidden');

    if (gamePollInterval) {
        clearInterval(gamePollInterval);
        gamePollInterval = null;
    }

    loadRoomState(roomId);
    gamePollInterval = setInterval(() => {
        if (currentRoom && !isEliminated) {
            loadRoomState(currentRoom);
        }
    }, 2000);
}

function leaveRoom() {
    if (gamePollInterval) {
        clearInterval(gamePollInterval);
        gamePollInterval = null;
    }
    stopVoice();
    hideBingoButton();
    currentRoom = null;
    hasShownBingo = false;
    isEliminated = false;
    lastCall = null;
    document.getElementById('game-active').classList.add('hidden');
    document.getElementById('game-inactive').classList.remove('hidden');
    showStakeSelector();
}

async function loadRoomState(roomId) {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/state`, { headers: getAuthHeaders() });
        const state = await res.json();

        if (state.error) {
            if (state.error.includes('not found') || state.error.includes('not in room') || state.error.includes('eliminated')) {
                leaveRoom();
                showToast(state.error);
            }
            return;
        }

        // Check if player was eliminated by server
        if (state.is_eliminated) {
            handleGameOver('You were eliminated from this round.');
            return;
        }

        // Update current call with VOICE
        const currentCallEl = document.getElementById('current-call');
        const newCall = state.current_call;
        const oldCall = currentCallEl.dataset.lastCall;

        if (newCall && newCall !== oldCall) {
            currentCallEl.textContent = newCall;
            currentCallEl.dataset.lastCall = newCall;
            currentCallEl.classList.add('new-call');
            setTimeout(() => currentCallEl.classList.remove('new-call'), 1000);
            speakNumber(newCall);
            lastCall = newCall;
        } else if (!newCall) {
            currentCallEl.textContent = '--';
            currentCallEl.dataset.lastCall = '';
        }

        // Update status
        const statusEl = document.getElementById('game-status');
        statusEl.textContent = state.status;
        statusEl.className = `status status-${state.status}`;

        // Update called numbers
        const calledDiv = document.getElementById('called-numbers');
        const calledNumbers = state.called_numbers || [];
        const sortedCalled = [...calledNumbers].sort((a, b) => a - b);
        calledDiv.innerHTML = sortedCalled.map(n => 
            `<span class="called-number">${n}</span>`
        ).join('');

        // Update cartelas
        renderMyCartelas(state.my_cartelas, state.my_marked, calledNumbers, state.bingo_claimed);

        // Update room info
        if (state.pot !== undefined) {
            const potEl = document.getElementById('game-pot');
            if (potEl) potEl.textContent = `💰 ${state.pot.toFixed(0)} ETB`;
        }
        if (state.players !== undefined) {
            const playersEl = document.getElementById('game-players');
            if (playersEl) playersEl.textContent = `👥 ${state.players}/${state.max_players || 20}`;
        }

        // Game completed
        if (state.status === 'completed') {
            clearInterval(gamePollInterval);
            gamePollInterval = null;

            if (state.winner) {
                if (state.winner.id === currentUser?.id) {
                    showToast('🎉 YOU WON! Check your balance!', 5000);
                    confetti();
                    const victory = new SpeechSynthesisUtterance('Congratulations! You won!');
                    victory.rate = 0.8;
                    victory.pitch = 1.3;
                    speechSynthesis.speak(victory);
                } else {
                    showToast(`🏆 ${state.winner.name} won the game!`);
                }
            } else {
                showToast('Game ended with no winner.');
            }

            setTimeout(() => {
                leaveRoom();
            }, 5000);
        }
    } catch (e) {
        console.error('Room state error:', e);
    }
}

// ============================================================
// CARTELA RENDERING (FIXED)
// ============================================================
function renderMyCartelas(cartelas, marked, calledNumbers, bingoClaimed) {
    const container = document.getElementById('my-cartelas');
    if (!cartelas || cartelas.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="icon">🎫</div><div>No cartelas yet</div></div>';
        return;
    }

    const calledSet = new Set(calledNumbers || []);
    let anyHasBingo = false;

    container.innerHTML = cartelas.map((cartela, cidx) => {
        const cartelaMarked = (marked && marked[cidx]) || [];
        const hasBingo = checkStraightLine(cartelaMarked);
        if (hasBingo) anyHasBingo = true;

        return `
            <div class="cartela-wrapper" data-cartela="${cidx}">
                <div class="cartela-header">
                    <span>Cartela #${cidx + 1}</span>
                    <span class="cartela-progress">${cartelaMarked.length}/25</span>
                </div>
                <div class="cartela-grid">
                    ${cartela.map((num, idx) => {
                        const isMarked = cartelaMarked.includes(idx);
                        const isCalled = calledSet.has(num) && num !== 0;
                        const isFree = num === 0;

                        let classes = ['cartela-cell'];
                        if (isFree) classes.push('free');
                        if (isMarked) classes.push('marked');
                        if (isCalled && !isFree && !isMarked) classes.push('called');

                        return `
                            <div class="${classes.join(' ')}"
                                 data-number="${num}"
                                 data-cartela="${cidx}"
                                 data-index="${idx}"
                                 onclick="handleCellClick(this, '${currentRoom}', ${cidx}, ${idx}, ${num})">
                                ${isFree ? '★' : num}
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');

    // FIXED: Show BINGO button if any cartela has straight line AND not already claimed/eliminated
    if (anyHasBingo && !hasShownBingo && !bingoClaimed && !isEliminated) {
        showBingoButton();
    }
}

// Check straight line patterns
function checkStraightLine(marked) {
    if (!marked || marked.length < 5) return false;
    const m = new Set(marked);

    // Rows
    for (let row = 0; row < 5; row++) {
        if ([0,1,2,3,4].every(col => m.has(row * 5 + col))) return true;
    }
    // Columns
    for (let col = 0; col < 5; col++) {
        if ([0,1,2,3,4].every(row => m.has(row * 5 + col))) return true;
    }
    // Diagonals
    if ([0,6,12,18,24].every(i => m.has(i))) return true;
    if ([4,8,12,16,20].every(i => m.has(i))) return true;

    return false;
}

function handleCellClick(cell, roomId, cartelaIdx, numberIdx, number) {
    const statusEl = document.getElementById('game-status');
    if (statusEl && statusEl.textContent !== 'active') {
        showToast('Wait for the game to start!');
        return;
    }
    if (number === 0) return;
    if (!cell.classList.contains('called') && !cell.classList.contains('marked')) {
        showToast("That number hasn't been called yet!");
        return;
    }
    markNumber(roomId, cartelaIdx, numberIdx);
}

async function markNumber(roomId, cartelaIdx, numberIdx) {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/mark`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cartela_index: cartelaIdx, number_index: numberIdx })
        });
        const data = await res.json();

        if (data.error) {
            showToast(data.error);
            return;
        }

        // Server says we have bingo
        if (data.has_bingo && !hasShownBingo) {
            showBingoButton();
        }

        if (data.marked) {
            const cell = document.querySelector(`[data-cartela="${cartelaIdx}"][data-index="${numberIdx}"]`);
            if (cell) {
                cell.classList.add('marked');
                cell.classList.remove('called');
            }
            const progressEl = document.querySelector(`.cartela-wrapper[data-cartela="${cartelaIdx}"] .cartela-progress`);
            if (progressEl) {
                const current = parseInt(progressEl.textContent.split('/')[0]) || 0;
                progressEl.textContent = `${current + 1}/25`;
            }
        }
    } catch (e) {
        showToast('Failed to mark number');
    }
}

// ============================================================
// BINGO BUTTON (IMPROVED - with Game Over)
// ============================================================
function showBingoButton() {
    if (hasShownBingo || isEliminated) return;
    hasShownBingo = true;

    let btn = document.getElementById('bingo-btn');
    if (!btn) {
        btn = document.createElement('button');
        btn.id = 'bingo-btn';
        btn.innerHTML = '🎉 BINGO! 🎉';
        btn.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: linear-gradient(135deg, #ff0000 0%, #ff4444 100%);
            color: white;
            font-size: 28px;
            font-weight: 800;
            padding: 20px 60px;
            border-radius: 50px;
            border: none;
            z-index: 1000;
            box-shadow: 0 0 30px rgba(255,0,0,0.6), 0 4px 20px rgba(0,0,0,0.3);
            cursor: pointer;
            animation: bingoPulse 0.6s infinite alternate;
            letter-spacing: 4px;
        `;
        btn.onclick = claimBingo;
        document.body.appendChild(btn);

        const style = document.createElement('style');
        style.textContent = `
            @keyframes bingoPulse {
                from { transform: translateX(-50%) scale(1); box-shadow: 0 0 30px rgba(255,0,0,0.6); }
                to { transform: translateX(-50%) scale(1.15); box-shadow: 0 0 50px rgba(255,0,0,0.9); }
            }
        `;
        document.head.appendChild(style);
    }

    btn.style.display = 'block';

    // Voice alert
    if (voiceEnabled) {
        const bingoAlert = new SpeechSynthesisUtterance('Bingo! Click the button now!');
        bingoAlert.rate = 0.9;
        bingoAlert.pitch = 1.2;
        speechSynthesis.speak(bingoAlert);
    }
}

function hideBingoButton() {
    const btn = document.getElementById('bingo-btn');
    if (btn) btn.style.display = 'none';
}

// NEW: Game Over handler
function handleGameOver(reason) {
    isEliminated = true;
    stopVoice();
    hideBingoButton();
    clearInterval(gamePollInterval);
    gamePollInterval = null;

    // Grey out cartelas
    document.querySelectorAll('.cartela-cell').forEach(cell => {
        cell.classList.add('losing');
        cell.style.pointerEvents = 'none';
    });

    // Show game over overlay (create if not exists)
    let overlay = document.getElementById('game-over-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'game-over-overlay';
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal" style="border: 2px solid #eb3349; text-align: center;">
                <div style="font-size: 64px; margin-bottom: 16px;">💀</div>
                <div style="font-size: 32px; font-weight: 800; color: #eb3349; margin-bottom: 16px;">GAME OVER</div>
                <div style="color: #8892b0; margin-bottom: 24px;" id="game-over-reason"></div>
                <button class="btn btn-primary" onclick="dismissGameOver()">Back to Lobby</button>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    document.getElementById('game-over-reason').textContent = reason || 'You called BINGO but had no winning pattern!';
    overlay.classList.add('active');

    if (tg?.HapticFeedback) {
        tg.HapticFeedback.notificationOccurred('error');
    }
}

function dismissGameOver() {
    const overlay = document.getElementById('game-over-overlay');
    if (overlay) overlay.classList.remove('active');
    leaveRoom();
}

async function claimBingo() {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${currentRoom}/bingo`, {
            method: 'POST',
            headers: getAuthHeaders()
        });

        const data = await res.json();

        if (data.success) {
            // PLAYER WON!
            hideBingoButton();
            showToast('🎉 BINGO! YOU WON!', 5000);

            if (voiceEnabled) {
                const victory = new SpeechSynthesisUtterance('Congratulations! You won!');
                victory.rate = 0.8;
                victory.pitch = 1.3;
                speechSynthesis.speak(victory);
            }

            confetti();
            clearInterval(gamePollInterval);

            // Show winner overlay
            let overlay = document.getElementById('winner-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'winner-overlay';
                overlay.className = 'modal-overlay';
                overlay.innerHTML = `
                    <div class="modal" style="border: 2px solid #38ef7d; text-align: center;">
                        <div style="font-size: 64px; margin-bottom: 16px;">🏆</div>
                        <div style="font-size: 32px; font-weight: 800; color: #38ef7d; margin-bottom: 16px;">BINGO!</div>
                        <div style="color: #8892b0; margin-bottom: 24px;">
                            Congratulations! You completed a winning pattern!<br>
                            <span style="color: #38ef7d; font-size: 20px; font-weight: bold;" id="winner-prize"></span>
                        </div>
                        <button class="btn btn-success" onclick="dismissWinner()">Claim Prize</button>
                    </div>
                `;
                document.body.appendChild(overlay);
            }

            document.getElementById('winner-prize').textContent = data.prize ? `+${data.prize} ETB` : '';
            overlay.classList.add('active');

            if (tg?.HapticFeedback) {
                tg.HapticFeedback.notificationOccurred('success');
            }

        } else {
            // FALSE BINGO - GAME OVER!
            handleGameOver(data.error || 'You called BINGO without a valid pattern!');
        }
    } catch (e) {
        showToast('Failed to claim bingo');
    }
}

function dismissWinner() {
    const overlay = document.getElementById('winner-overlay');
    if (overlay) overlay.classList.remove('active');
    leaveRoom();
    loadProfile(); // Refresh balance
}

// ============================================================
// PRIVATE ROOMS
// ============================================================
function openCreateRoom() {
    const stake = parseInt(prompt('Stake per cartela (ETB):', '10'));
    if (!stake || stake < 1) return;
    const cartelas = parseInt(prompt('Cartelas (1-3):', '1'));
    if (!cartelas || cartelas < 1 || cartelas > 3) return;
    const isPrivate = confirm('Make this room private?');

    fetch(`${API_BASE}/api/rooms`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ stake, cartelas, is_private: isPrivate })
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) { showToast(data.error); return; }
        if (isPrivate) {
            showToast(`Room created! Code: ${data.room.invite_code}`);
            alert(`Share this code: ${data.room.invite_code}`);
        }
        enterRoom(data.room.id);
    })
    .catch(() => showToast('Failed to create room'));
}

function openJoinByCode() {
    const code = prompt('Enter invite code:');
    if (!code) return;
    const cartelas = parseInt(prompt('Cartelas (1-3):', '1')) || 1;

    fetch(`${API_BASE}/api/rooms/join-by-code`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: code, cartelas })
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) { showToast(data.error); return; }
        enterRoom(data.room_id);
    })
    .catch(() => showToast('Failed to join room'));
}

// ============================================================
// PROFILE
// ============================================================
async function loadProfile() {
    try {
        const res = await fetch(`${API_BASE}/api/user/profile`, { headers: getAuthHeaders() });
        const user = await res.json();

        document.getElementById('profile-info').innerHTML = `
            <div class="info-row"><span class="info-label">Name:</span><span class="info-value">${user.first_name} ${user.last_name || ''}</span></div>
            <div class="info-row"><span class="info-label">Username:</span><span class="info-value">@${user.username || 'N/A'}</span></div>
            <div class="info-row"><span class="info-label">Balance:</span><span class="info-value">${user.balance.toFixed(2)} ETB</span></div>
            <div class="info-row"><span class="info-label">Games Played:</span><span class="info-value">${user.stats.games_played}</span></div>
            <div class="info-row"><span class="info-label">Games Won:</span><span class="info-value">${user.stats.games_won}</span></div>
            <div class="info-row"><span class="info-label">Win Rate:</span><span class="info-value">${user.stats.win_rate}%</span></div>
        `;

        loadTransactions();
    } catch (e) {
        document.getElementById('profile-info').innerHTML = '<div class="empty-state">Failed to load profile</div>';
    }
}

async function loadTransactions() {
    try {
        const res = await fetch(`${API_BASE}/api/user/transactions`, { headers: getAuthHeaders() });
        const txs = await res.json();

        const list = document.getElementById('transactions-list');
        if (txs.length === 0) {
            list.innerHTML = '<div style="text-align:center;color:#8892b0;padding:20px;">No transactions yet</div>';
            return;
        }

        list.innerHTML = txs.slice(0, 10).map(t => `
            <div class="info-row">
                <span class="info-label">${t.type}</span>
                <span class="info-value" style="color:${t.amount > 0 ? '#38ef7d' : '#ef4444'}">
                    ${t.amount > 0 ? '+' : ''}${t.amount.toFixed(0)} ETB
                </span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Transactions error:', e);
    }
}

// ============================================================
// DEPOSIT / WITHDRAW
// ============================================================
function openDeposit() { openModal('modal-deposit'); }
function openWithdraw() { openModal('modal-withdraw'); }

async function requestDeposit() {
    const amount = parseFloat(document.getElementById('deposit-amount').value);
    if (!amount || amount < 10) { showToast('Min deposit 10 ETB'); return; }

    try {
        const res = await fetch(`${API_BASE}/api/user/deposit`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount })
        });
        const data = await res.json();
        if (data.error) { showToast(data.error); return; }

        showToast(`✅ Deposit #${data.deposit_id} requested!`);
        showToast(`📱 Send ${amount} ETB to 0936719379 (Alazar)`);
        closeModal('modal-deposit');
    } catch (e) {
        showToast('Deposit request failed');
    }
}

async function requestWithdrawal() {
    const amount = parseFloat(document.getElementById('withdraw-amount').value);
    const phone = document.getElementById('withdraw-phone').value;
    if (!amount || amount < 50) { showToast('Min withdrawal 50 ETB'); return; }
    if (!phone) { showToast('Enter phone number'); return; }

    try {
        const res = await fetch(`${API_BASE}/api/user/withdraw`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, phone_number: phone })
        });
        const data = await res.json();
        if (data.error) { showToast(data.error); return; }

        showToast(`✅ Withdrawal #${data.withdrawal_id} requested!`);
        closeModal('modal-withdraw');
        loadProfile();
    } catch (e) {
        showToast('Withdrawal request failed');
    }
}

// ============================================================
// UI HELPERS
// ============================================================
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

function showToast(msg, duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), duration);
}

function confetti() {
    for (let i = 0; i < 50; i++) {
        const el = document.createElement('div');
        el.style.cssText = `
            position: fixed;
            width: 10px; height: 10px;
            background: hsl(${Math.random() * 360}, 100%, 50%);
            left: ${Math.random() * 100}vw;
            top: -10px;
            border-radius: 50%;
            z-index: 9999;
            animation: fall ${2 + Math.random() * 2}s linear forwards;
        `;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    }
}

// Add fall animation
const fallStyle = document.createElement('style');
fallStyle.textContent = `
    @keyframes fall {
        to { transform: translateY(100vh) rotate(720deg); opacity: 0; }
    }
`;
document.head.appendChild(fallStyle);

// Close modals on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.remove('active');
    });
});

// NEXUS BINGO - Frontend JavaScript
const API_BASE = '';
let tg = window.Telegram?.WebApp;
let currentUser = null;
let currentRoom = null;
let selectedCartelaIds = [];
let allCartelas = [];
let gamePollInterval = null;
let currentCartelaPage = 1;

// Stake levels available
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
    showStakeSelector(); // Show stake picker instead of room list
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
// STAKE SELECTOR (Replaces room list)
// ============================================================

function showStakeSelector() {
    const list = document.getElementById('rooms-list');
    
    list.innerHTML = `
        <div class="section">
            <div class="section-title">🎯 Choose Your Stake</div>
            <div style="font-size: 13px; color: #8892b0; margin-bottom: 16px; text-align: center;">
                Pick a stake level. We'll find or create a room for you instantly!<br>
                <span style="color: #38ef7d;">⏱️ 1 min timer — bots fill empty slots</span>
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
    `;
    
    // Load player counts for each stake
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
    
    showToast(`🎮 Finding ${stake} ETB room...`);
    
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
// GAME (Same as before, with polling)
// ============================================================

function enterRoom(roomId) {
    currentRoom = roomId;
    document.querySelectorAll('.tab')[1].click();
    document.getElementById('game-active').classList.remove('hidden');
    document.getElementById('game-inactive').classList.add('hidden');
    
    if (gamePollInterval) {
        clearInterval(gamePollInterval);
        gamePollInterval = null;
    }
    
    loadRoomState(roomId);
    gamePollInterval = setInterval(() => {
        if (currentRoom) {
            loadRoomState(currentRoom);
        }
    }, 2000);
}

function leaveRoom() {
    if (gamePollInterval) {
        clearInterval(gamePollInterval);
        gamePollInterval = null;
    }
    currentRoom = null;
    document.getElementById('game-active').classList.add('hidden');
    document.getElementById('game-inactive').classList.remove('hidden');
    showStakeSelector();
}

async function loadRoomState(roomId) {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/state`, { headers: getAuthHeaders() });
        const state = await res.json();
        if (state.error) {
            if (state.error.includes('not found') || state.error.includes('not in room')) {
                leaveRoom();
                showToast('You were removed from the room');
            }
            return;
        }
        
        // Update current call with animation
        const currentCallEl = document.getElementById('current-call');
        const newCall = state.current_call;
        const oldCall = currentCallEl.dataset.lastCall;
        
        if (newCall && newCall !== oldCall) {
            currentCallEl.textContent = newCall;
            currentCallEl.dataset.lastCall = newCall;
            currentCallEl.classList.add('new-call');
            setTimeout(() => currentCallEl.classList.remove('new-call'), 1000);
        } else if (!newCall) {
            currentCallEl.textContent = '--';
            currentCallEl.dataset.lastCall = '';
        }
        
        // Update game status
        const statusEl = document.getElementById('game-status');
        statusEl.textContent = state.status;
        statusEl.className = `status status-${state.status}`;
        
        // Show countdown timer if waiting
        if (state.status === 'waiting' && state.time_remaining !== undefined) {
            const timerEl = document.getElementById('game-timer');
            if (timerEl) {
                const seconds = Math.ceil(state.time_remaining / 1000);
                timerEl.textContent = `⏱️ ${seconds}s until bots join`;
                timerEl.classList.remove('hidden');
            }
        } else {
            const timerEl = document.getElementById('game-timer');
            if (timerEl) timerEl.classList.add('hidden');
        }
        
        // Update called numbers grid (sorted)
        const calledDiv = document.getElementById('called-numbers');
        const calledNumbers = state.called_numbers || [];
        const sortedCalled = [...calledNumbers].sort((a, b) => a - b);
        
        calledDiv.innerHTML = sortedCalled.map(n => 
            `<span class="called-number">${n}</span>`
        ).join('');
        
        // Update cartelas
        renderMyCartelas(state.my_cartelas, state.my_marked, calledNumbers);
        
        // Update room info
        if (state.pot !== undefined) {
            const potEl = document.getElementById('game-pot');
            if (potEl) potEl.textContent = `💰 ${state.pot.toFixed(0)} ETB`;
        }
        if (state.players !== undefined) {
            const playersEl = document.getElementById('game-players');
            if (playersEl) playersEl.textContent = `👥 ${state.players}/${state.max_players || 20}`;
        }
        
        // Game over handling
        if (state.status === 'completed') {
            clearInterval(gamePollInterval);
            gamePollInterval = null;
            
            if (state.winner) {
                if (state.winner.id === currentUser?.id) {
                    showToast('🎉 YOU WON! Check your balance!');
                    confetti();
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

function renderMyCartelas(cartelas, marked, calledNumbers) {
    const container = document.getElementById('my-cartelas');
    if (!cartelas || cartelas.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="icon">🎫</div><div>No cartelas yet</div></div>';
        return;
    }
    
    const calledSet = new Set(calledNumbers || []);
    
    container.innerHTML = cartelas.map((cartela, cidx) => `
        <div class="cartela-wrapper" data-cartela="${cidx}">
            <div class="cartela-header">
                <span>Cartela #${cidx + 1}</span>
                <span class="cartela-progress">${countMarked(marked, cidx)}/25</span>
            </div>
            <div class="cartela-grid">
                ${cartela.map((num, idx) => {
                    const isMarked = marked && marked[cidx] && marked[cidx].includes(idx);
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
    `).join('');
}

function countMarked(marked, cidx) {
    if (!marked || !marked[cidx]) return 0;
    return marked[cidx].length;
}

function handleCellClick(cell, roomId, cartelaIdx, numberIdx, number) {
    const statusEl = document.getElementById('game-status');
    if (statusEl && statusEl.textContent !== 'active') {
        showToast('Wait for the game to start!');
        return;
    }
    
    if (number === 0) return;
    
    if (!cell.classList.contains('called') && !cell.classList.contains('marked')) {
        showToast('That number hasn\'t been called yet!');
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
        
        if (data.winner) {
            showToast('🎉 BINGO! YOU WON!');
            confetti();
            loadRoomState(roomId);
        } else if (data.marked) {
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

// Profile
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

// Deposit / Withdraw
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

// UI Helpers
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
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

// Close modals on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.remove('active');
    });
});

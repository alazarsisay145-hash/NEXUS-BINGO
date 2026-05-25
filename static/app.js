// NEXUS BINGO - Frontend JavaScript
const API_BASE = '';
let tg = window.Telegram?.WebApp;
let currentUser = null;
let currentRoom = null;
let selectedCartelaIds = [];
let allCartelas = [];
let gamePollInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    if (tg) {
        tg.expand();
        tg.ready();
        tg.setHeaderColor('#0f0f23');
    }
    initAuth();
    loadRooms();
    loadProfile();
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
    if (tab === 'rooms') loadRooms();
    if (tab === 'profile') loadProfile();
}

// Rooms
async function loadRooms() {
    const list = document.getElementById('rooms-list');
    list.innerHTML = '<div class="loading"><div class="spinner"></div><div>Loading rooms...</div></div>';
    
    try {
        const res = await fetch(`${API_BASE}/api/rooms`, { headers: getAuthHeaders() });
        const rooms = await res.json();
        
        if (!Array.isArray(rooms) || rooms.length === 0) {
            list.innerHTML = '<div class="empty-state"><div class="icon">🏠</div><div>No active rooms. Create one!</div></div>';
            return;
        }
        
        list.innerHTML = rooms.map(r => `
            <div class="room-card" onclick="joinRoom('${r.id}')">
                <div class="room-header">
                    <div>
                        <span class="stake">${r.stake.toFixed(0)} ETB</span>
                        ${r.is_private ? '<span class="badge-private">🔒 PRIVATE</span>' : ''}
                        ${r.is_automated ? '<span class="badge-private" style="background:#ef4444;">🤖 BOTS</span>' : ''}
                    </div>
                    <span class="status status-${r.status}">${r.status}</span>
                </div>
                <div class="players">👥 ${r.players}/${r.max_players} players • 💰 ${r.pot.toFixed(0)} ETB pot</div>
                ${r.invite_code ? `<div style="font-size:12px;color:#a78bfa;margin-top:4px;">🔑 Code: ${r.invite_code}</div>` : ''}
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><div>Failed to load rooms</div></div>';
    }
}

// Create Room
let createRoomData = { selectionMode: 'random', selectedIds: [] };

function openCreateRoom() {
    selectedCartelaIds = [];
    createRoomData = { selectionMode: 'random', selectedIds: [] };
    document.getElementById('selected-cartelas-display').textContent = '';
    document.getElementById('btn-random').style.background = '#667eea';
    document.getElementById('btn-manual').style.background = '#2a2a4e';
    openModal('modal-create');
}

function toggleCartelaSelection(mode) {
    createRoomData.selectionMode = mode;
    const btnRandom = document.getElementById('btn-random');
    const btnManual = document.getElementById('btn-manual');
    
    if (mode === 'random') {
        btnRandom.style.background = '#667eea';
        btnManual.style.background = '#2a2a4e';
        selectedCartelaIds = [];
        document.getElementById('selected-cartelas-display').textContent = '🎲 Random selection';
    } else {
        btnRandom.style.background = '#2a2a4e';
        btnManual.style.background = '#667eea';
    }
}

async function openCartelaPicker() {
    const maxCartelas = parseInt(document.getElementById('create-cartelas').value) || 1;
    document.getElementById('max-cartelas-allowed').textContent = maxCartelas;
    
    if (allCartelas.length === 0) {
        await loadCartelasBatch(1);
    }
    renderCartelaPicker();
    openModal('modal-cartelas');
}

async function loadCartelasBatch(page) {
    try {
        const res = await fetch(`${API_BASE}/api/cartelas/preview/batch?page=${page}&per_page=50`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (page === 1) allCartelas = [];
        allCartelas = allCartelas.concat(data.cartelas);
        return data;
    } catch (e) {
        showToast('Failed to load cartelas');
    }
}

function renderCartelaPicker() {
    const selector = document.getElementById('cartela-selector');
    const pagination = document.getElementById('cartela-pagination');
    const maxCartelas = parseInt(document.getElementById('create-cartelas').value) || 1;
    
    selector.innerHTML = allCartelas.map(c => {
        const isSelected = selectedCartelaIds.includes(c.id);
        return `
            <div class="cartela-option ${isSelected ? 'selected' : ''}" onclick="toggleCartela(${c.id}, ${maxCartelas})">
                <div class="cartela-id">#${c.id}</div>
                <div class="cartela-preview">
                    ${c.numbers.map((n, i) => `
                        <div class="cartela-preview-cell ${n === 0 ? 'free' : ''}">${n || '★'}</div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
    
    pagination.innerHTML = `
        <button class="page-btn" onclick="changeCartelaPage(-1)" ${allCartelas.length < 50 ? 'disabled' : ''}>← Prev</button>
        <button class="page-btn" onclick="changeCartelaPage(1)">Next →</button>
    `;
    
    document.getElementById('selected-count').textContent = `Selected: ${selectedCartelaIds.length}/${maxCartelas}`;
}

function toggleCartela(id, max) {
    const idx = selectedCartelaIds.indexOf(id);
    if (idx > -1) {
        selectedCartelaIds.splice(idx, 1);
    } else if (selectedCartelaIds.length < max) {
        selectedCartelaIds.push(id);
    } else {
        showToast(`Max ${max} cartelas allowed!`);
        return;
    }
    renderCartelaPicker();
}

function changeCartelaPage(dir) {
    showToast('Loading more cartelas...');
}

function confirmCartelaSelection() {
    const maxCartelas = parseInt(document.getElementById('create-cartelas').value) || 1;
    if (selectedCartelaIds.length === 0) {
        showToast('Please select at least one cartela');
        return;
    }
    if (selectedCartelaIds.length > maxCartelas) {
        showToast(`Max ${maxCartelas} cartelas allowed!`);
        return;
    }
    createRoomData.selectedIds = [...selectedCartelaIds];
    document.getElementById('selected-cartelas-display').textContent = `🎯 Selected: #${selectedCartelaIds.join(', #')}`;
    closeModal('modal-cartelas');
}

async function createRoom() {
    const stake = parseFloat(document.getElementById('create-stake').value);
    const maxPlayers = parseInt(document.getElementById('create-max-players').value);
    const cartelas = parseInt(document.getElementById('create-cartelas').value);
    const isPrivate = document.getElementById('create-private').checked;
    const rigged = document.getElementById('create-rigged').checked;
    
    if (!stake || stake < 1) { showToast('Invalid stake'); return; }
    if (maxPlayers < 1 || maxPlayers > 1000) { showToast('Players must be 1-1000'); return; }
    if (cartelas < 1 || cartelas > 3) { showToast('Cartelas must be 1-3'); return; }
    
    const body = {
        stake,
        max_players: maxPlayers,
        cartelas,
        is_private: isPrivate,
        rigged_mode: rigged,
        cartela_selection: createRoomData.selectionMode,
        selected_cartela_ids: createRoomData.selectedIds
    };
    
    try {
        const res = await fetch(`${API_BASE}/api/rooms`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.error) { showToast(data.error); return; }
        
        showToast(`✅ Room created! ID: ${data.room.id}`);
        if (data.room.invite_code) {
            showToast(`🔑 Invite code: ${data.room.invite_code}`);
        }
        closeModal('modal-create');
        enterRoom(data.room.id);
    } catch (e) {
        showToast('Failed to create room');
    }
}
// Join Room
async function joinRoom(roomId) {
    const cartelas = prompt('How many cartelas? (1-3)', '1');
    if (!cartelas) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/join`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cartelas: parseInt(cartelas) })
        });
        const data = await res.json();
        if (data.error) { showToast(data.error); return; }
        
        showToast('✅ Joined room!');
        enterRoom(roomId);
    } catch (e) {
        showToast('Failed to join room');
    }
}

// Join by Code
function openJoinByCode() {
    openModal('modal-join-code');
}

async function joinByCode() {
    const code = document.getElementById('join-code').value.trim().toUpperCase();
    const cartelas = parseInt(document.getElementById('join-code-cartelas').value) || 1;
    
    if (!code) { showToast('Enter invite code'); return; }
    
    try {
        const res = await fetch(`${API_BASE}/api/rooms/join-by-code`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ invite_code: code, cartelas })
        });
        const data = await res.json();
        if (data.error) { showToast(data.error); return; }
        
        showToast('✅ Joined private room!');
        closeModal('modal-join-code');
        enterRoom(data.room_id);
    } catch (e) {
        showToast('Invalid invite code');
    }
}

// Game
function enterRoom(roomId) {
    currentRoom = roomId;
    showTab('game');
    document.querySelectorAll('.tab')[1].click();
    document.getElementById('game-active').classList.remove('hidden');
    document.getElementById('game-inactive').classList.add('hidden');
    
    if (gamePollInterval) clearInterval(gamePollInterval);
    loadRoomState(roomId);
    gamePollInterval = setInterval(() => loadRoomState(roomId), 3000);
}

async function loadRoomState(roomId) {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/state`, { headers: getAuthHeaders() });
        const state = await res.json();
        if (state.error) return;
        
        document.getElementById('current-call').textContent = state.current_call || '--';
        document.getElementById('game-status').textContent = state.status;
        document.getElementById('game-status').className = `status status-${state.status}`;
        
        const calledDiv = document.getElementById('called-numbers');
        calledDiv.innerHTML = (state.called_numbers || []).map(n => 
            `<span class="called-number">${n}</span>`
        ).join('');
        
        renderMyCartelas(state.my_cartelas, state.my_marked, state.called_numbers);
        
        if (state.status === 'completed') {
            clearInterval(gamePollInterval);
            showToast('🎉 Game Over! Check Telegram for winner.');
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
    
    container.innerHTML = cartelas.map((cartela, cidx) => `
        <div style="margin-bottom: 20px;">
            <div style="text-align: center; font-size: 14px; color: #a78bfa; margin-bottom: 8px;">
                Cartela #${cidx + 1}
            </div>
            <div class="cartela-grid">
                ${cartela.map((num, idx) => {
                    const isMarked = marked && marked[cidx] && marked[cidx].includes(idx);
                    const isCalled = calledNumbers && calledNumbers.includes(num);
                    const isFree = num === 0;
                    return `
                        <div class="cartela-cell ${isMarked ? 'marked' : ''} ${isFree ? 'free' : ''} ${isCalled && !isFree ? 'called' : ''}"
                             onclick="markNumber('${currentRoom}', ${cidx}, ${idx})">
                            ${isFree ? '★' : num}
                        </div>
                    `;
                }).join('')}
            </div>
        </div>
    `).join('');
}

async function markNumber(roomId, cartelaIdx, numberIdx) {
    try {
        const res = await fetch(`${API_BASE}/api/rooms/${roomId}/mark`, {
            method: 'POST',
            headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cartela_index: cartelaIdx, number_index: numberIdx })
        });
        const data = await res.json();
        if (data.winner) {
            showToast('🎉 BINGO! YOU WON!');
            confetti();
        } else if (data.marked) {
            loadRoomState(roomId);
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

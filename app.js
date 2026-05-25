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

/* Claude Messages — Session list + detail viewer */

const sessionList = document.getElementById('session-list');
const conversation = document.getElementById('conversation');
const emptyState = document.getElementById('empty-state');
const convHeader = document.getElementById('conv-header');
const messagesDiv = document.getElementById('messages');
const searchInput = document.getElementById('session-search');
const loadMore = document.getElementById('load-more');

let currentSessionId = null;
let currentOffset = 50;
let searchTimeout = null;
let evtSource = null;

// --- Session list ---

function selectSession(sessionId) {
  if (currentSessionId === sessionId) return;
  currentSessionId = sessionId;

  // Highlight active
  document.querySelectorAll('.claude-session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.sessionId === sessionId);
  });

  emptyState.style.display = 'none';
  conversation.style.display = 'flex';
  messagesDiv.innerHTML = '<div class="claude-loading">Loading...</div>';

  fetch(`/api/claude/sessions/${sessionId}/messages`)
    .then(r => r.json())
    .then(data => {
      renderConversation(data.session, data.messages);
    })
    .catch(err => {
      messagesDiv.innerHTML = `<div class="claude-error">Failed to load: ${err.message}</div>`;
    });
}

function renderConversation(session, messages) {
  // Header
  if (session) {
    const shortCwd = session.cwd ? session.cwd.split('/').slice(-3).join('/') : 'unknown';
    const time = session.start_time ? new Date(session.start_time).toLocaleString() : '';
    convHeader.innerHTML = `
      <div class="claude-conv-cwd">${shortCwd}</div>
      <div class="claude-conv-meta">
        <span>${time}</span>
        <span class="claude-conv-status ${session.status || ''}">${session.status || ''}</span>
        ${session.summary ? `<span class="claude-conv-summary">${escapeHtml(session.summary)}</span>` : ''}
      </div>
    `;
  }

  // Messages
  messagesDiv.innerHTML = '';
  for (const msg of messages) {
    messagesDiv.appendChild(createMessageEl(msg));
  }
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function createMessageEl(msg) {
  const div = document.createElement('div');
  div.className = `claude-msg claude-msg-${msg.role}`;
  div.dataset.msgId = msg.id;

  const content = msg.content || '';
  const isToolSummary = content.startsWith('[Used tools:') || content === '[Tool calls in progress...]' || content === '[Response logged]';
  const displayContent = isToolSummary
    ? `<span class="claude-tool-summary">${escapeHtml(content)}</span>`
    : escapeHtml(content);

  let meta = '';
  if (msg.timestamp) {
    const t = new Date(msg.timestamp);
    meta += `<span class="claude-msg-time">${t.toLocaleTimeString()}</span>`;
  }
  if (msg.model) {
    meta += `<span class="claude-msg-model">${msg.model.replace('claude-', '')}</span>`;
  }
  if (msg.input_tokens || msg.output_tokens) {
    const tokens = [];
    if (msg.input_tokens) tokens.push(`${(msg.input_tokens / 1000).toFixed(1)}k in`);
    if (msg.output_tokens) tokens.push(`${(msg.output_tokens / 1000).toFixed(1)}k out`);
    meta += `<span class="claude-msg-tokens">${tokens.join(', ')}</span>`;
  }

  div.innerHTML = `
    <div class="claude-msg-role">${msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'Claude' : msg.role}</div>
    <div class="claude-msg-content">${displayContent}</div>
    ${meta ? `<div class="claude-msg-meta">${meta}</div>` : ''}
  `;
  return div;
}

// --- Search ---

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    const query = searchInput.value.trim();
    loadSessions(0, query);
  }, 400);
});

function loadSessions(offset = 0, search = null) {
  let url = `/api/claude/sessions?limit=50&offset=${offset}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (offset === 0) {
        // Clear existing (except load-more)
        const items = sessionList.querySelectorAll('.claude-session-item');
        items.forEach(el => el.remove());
      }
      const frag = document.createDocumentFragment();
      for (const s of data.sessions) {
        frag.appendChild(createSessionEl(s));
      }
      sessionList.insertBefore(frag, loadMore);
      currentOffset = offset + data.count;
      loadMore.style.display = data.count < 50 ? 'none' : 'block';
    });
}

function createSessionEl(s) {
  const div = document.createElement('div');
  div.className = 'claude-session-item';
  if (s.session_id === currentSessionId) div.classList.add('active');
  div.dataset.sessionId = s.session_id;

  const cwd = s.cwd ? s.cwd.split('/').slice(-2).join('/') : 'unknown';
  const preview = (s.summary || s.first_message || '').substring(0, 80);
  const time = s.start_time ? relativeTime(new Date(s.start_time)) : '';

  div.innerHTML = `
    <div class="claude-session-cwd">${escapeHtml(cwd)}</div>
    <div class="claude-session-preview">${escapeHtml(preview)}</div>
    <div class="claude-session-meta">
      <span class="claude-session-count">${s.msg_count} msg${s.msg_count !== 1 ? 's' : ''}</span>
      <span class="claude-session-time">${time}</span>
    </div>
  `;
  div.addEventListener('click', () => selectSession(s.session_id));
  return div;
}

// --- Load more ---

loadMore.addEventListener('click', () => {
  const search = searchInput.value.trim() || null;
  loadSessions(currentOffset, search);
});

// --- Click handlers for initial server-rendered sessions ---

sessionList.addEventListener('click', (e) => {
  const item = e.target.closest('.claude-session-item');
  if (item && item.dataset.sessionId) {
    selectSession(item.dataset.sessionId);
  }
});

// --- SSE live updates ---

function connectLive() {
  evtSource = new EventSource('/api/claude/live');

  evtSource.addEventListener('new_message', (e) => {
    const msg = JSON.parse(e.data);

    // If viewing this session, append message
    if (msg.session_id === currentSessionId) {
      // Check if message already exists (update placeholder)
      const existing = messagesDiv.querySelector(`[data-msg-id="${msg.id}"]`);
      if (existing) {
        existing.replaceWith(createMessageEl(msg));
      } else {
        messagesDiv.appendChild(createMessageEl(msg));
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
      }
    }

    // Update session list - bump session to top or update count
    updateSessionInList(msg.session_id);
  });

  evtSource.onerror = () => {
    evtSource.close();
    setTimeout(connectLive, 5000);
  };
}

function updateSessionInList(sessionId) {
  const item = sessionList.querySelector(`[data-session-id="${sessionId}"]`);
  if (item) {
    // Bump to top
    const firstItem = sessionList.querySelector('.claude-session-item');
    if (firstItem && firstItem !== item) {
      sessionList.insertBefore(item, firstItem);
    }
    // Increment count
    const countEl = item.querySelector('.claude-session-count');
    if (countEl) {
      const match = countEl.textContent.match(/(\d+)/);
      if (match) {
        const n = parseInt(match[1]) + 1;
        countEl.textContent = `${n} msg${n !== 1 ? 's' : ''}`;
      }
    }
  }
  // New session not in list — reload top of list
  else {
    loadSessions(0, searchInput.value.trim() || null);
  }
}

connectLive();

// --- Helpers ---

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function relativeTime(date) {
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/* ============================================================================ */
/* SSUET AI ASSISTANT - MAIN JAVASCRIPT CONTROLLER                           */
/* ============================================================================ */

// ── GLOBAL STATE ──
let messages = [];
let recognition = null;
let voiceText = '';
let currentSessionId = null;
let selectedRating = 0;
let allSessions = [];

// XSS Sanitization helper
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// CSRF token helper
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

// Helpers to access containers
function getChatContainer() {
  return document.getElementById('chatContainer');
}

// Helper to access messages container
function getMessagesContainer() {
  return document.getElementById('messages');
}

// ── SIDEBAR & UI TOGGLES ──
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('active');
  document.getElementById('chatContainer').classList.toggle('sidebar-open');
}

function toggleDropdown() {
  document.getElementById('userDropdown').classList.toggle('active');
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.user-profile')) {
    const dd = document.getElementById('userDropdown');
    if (dd) dd.classList.remove('active');
  }
});

// ── SESSION & HISTORY MANAGEMENT ──

// 1. Fetch all previous chat sessions from the database
async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) return;
    const data = await res.json();
    allSessions = data.sessions || [];
    displaySessions(allSessions);
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

// 2. Display sessions in the sidebar
function displaySessions(sessions) {
  const list = document.getElementById('sessionList');
  if (!sessions || sessions.length === 0) {
    list.innerHTML = '<div style="text-align:center; color:var(--muted); padding:20px;">No chat history yet</div>';
    return;
  }

  list.innerHTML = sessions.map(function (s) {
    return '<div class="session-item ' + (s.id === currentSessionId ? 'active' : '') + '" ' +
      'onclick="loadSession(' + s.id + ')">' +
      '<div class="session-info">' +
      '<div class="session-name">💬 ' + (s.session_name || 'Chat') + '</div>' +
      '<div class="session-time">' + new Date(s.created_at).toLocaleString('en-PK', { year: 'numeric', month: 'short', day: 'numeric' }) + '</div>' +
      '</div>' +
      '</div>';
  }).join('');
}

// 3. Filter sessions based on search input
function filterSessions() {
  const searchTerm = document.getElementById('searchHistory').value.toLowerCase();
  const filtered = allSessions.filter(session =>
    (session.session_name || '').toLowerCase().includes(searchTerm)
  );
  displaySessions(filtered);
}

// 4. Load a specific chat's messages and display them
async function loadSession(sessionId) {
  try {
    currentSessionId = sessionId;

    const res = await fetch(`/api/messages/${sessionId}`);
    if (!res.ok) return;
    const data = await res.json();

    // Hide welcome and clear only the messages container
    const welcome = document.getElementById('welcomeScreen');
    if (welcome) welcome.style.display = 'none';
    const msgs = getMessagesContainer();
    if (msgs) msgs.innerHTML = '';

    // Load messages from DB
    data.messages.forEach(msg => {
      addMsg(msg.sender, msg.content, false);
    });

    // Close sidebar on mobile
    const sb = document.getElementById('sidebar');
    if (sb && sb.classList.contains('active')) toggleSidebar();
  } catch (err) {
    console.error('Failed to load session:', err);
  }
}

// 5. Reset for a brand new chat
function newChat() {
  currentSessionId = null;
  const msgs = getMessagesContainer();
  if (msgs) msgs.innerHTML = '';
  const welcome = document.getElementById('welcomeScreen');
  if (welcome) welcome.style.display = 'flex';

  // Clear search
  document.getElementById('searchHistory').value = '';
  displaySessions(allSessions);

  // Close sidebar (if opened via button)
  const sb = document.getElementById('sidebar');
  if (sb && sb.classList.contains('active')) toggleSidebar();
}

// ── CORE CHAT LOGIC ──

async function sendMsg() {
  const input = document.getElementById('msgInput');
  const text = input.value.trim();
  if (!text) return;

  document.getElementById('welcomeScreen').style.display = 'none';
  input.value = '';
  input.style.height = 'auto';
  document.getElementById('sendBtn').disabled = true;

  addMsg('user', text);
  const tid = showTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify({
        message: text,
        session_id: currentSessionId
      })
    });

    removeTyping(tid);

    if (!res.ok) {
      let e = {};
      try { e = await res.json(); } catch (_) { }
      addMsg('ai', e.reply || '❌ Server error. Please try again.');
      document.getElementById('sendBtn').disabled = false;
      return;
    }

    const data = await res.json();
    addMsg('ai', data.reply, true); // showFeedback = true for new AI responses

    // Update current session ID from response (important for new chats)
    currentSessionId = data.session_id;

    // Refresh sidebar to show the new/updated session
    loadSessions();

  } catch (e) {
    removeTyping(tid);
    addMsg('ai', '❌ Connection error. Please try again.');
  }

  document.getElementById('sendBtn').disabled = false;
}

function askQ(q) {
  document.getElementById('msgInput').value = q;
  sendMsg();
}

function addMsg(role, text, showFeedback = false) {
  const msgs = getMessagesContainer();
  if (!msgs) return;
  const d = document.createElement('div');
  d.className = 'message ' + role;
  const time = new Date().toLocaleTimeString('en-PK', { hour: '2-digit', minute: '2-digit' });
  const label = role === 'ai' ? 'SSUET AI Assistant' : 'You';

  // Add feedback buttons only for new AI messages
  let feedbackHTML = '';
  if (showFeedback && role === 'ai') {
    feedbackHTML = '<div class="feedback-section">' +
      '<button class="feedback-btn" onclick="rateMessage(this, \'up\')">👍 Helpful</button>' +
      '<button class="feedback-btn" onclick="rateMessage(this, \'down\')">👎 Not Helpful</button>' +
      '</div>';
  }

  d.innerHTML = '<div class="avatar ' + (role === 'ai' ? 'ai' : 'user-av') + '">' + (role === 'ai' ? '🤖' : '') + '</div>' +
    '<div class="msg-wrap">' +
    '<div class="msg-label">' + label + ' · ' + time + '</div>' +
    '<div class="bubble">' + fmt(text) + '</div>' +
    feedbackHTML +
    '</div>';
  msgs.appendChild(d);

  // Scroll the outer chat container to the bottom
  const container = getChatContainer();
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

function fmt(t) {
  let s = escapeHtml(t || '');
  return s
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^### (.*$)/gm, '<strong style="font-size:15px;color:var(--purple-dark)">$1</strong>')
    .replace(/^## (.*$)/gm, '<strong style="font-size:16px;color:var(--purple-dark)">$1</strong>')
    .replace(/^- (.*$)/gm, '&nbsp;&nbsp;• $1')
    .replace(/\n/g, '<br>');
}

function showTyping() {
  const msgs = getMessagesContainer();
  const container = getChatContainer();
  const d = document.createElement('div');
  const id = 'typ' + Date.now();
  d.id = id;
  d.className = 'message ai';
  d.innerHTML = '<div class="avatar ai">🤖</div>' +
    '<div class="msg-wrap">' +
    '<div class="msg-label">SSUET AI is thinking...</div>' +
    '<div class="bubble"><div class="typing-indicator"><span></span><span></span><span></span></div></div>' +
    '</div>';
  if (msgs) msgs.appendChild(d);
  if (container) container.scrollTop = container.scrollHeight;
  return id;
}

function removeTyping(id) {
  try {
    const msgs = getMessagesContainer();
    if (!msgs) return;
    const el = document.getElementById(id);
    if (el && el.parentNode) el.parentNode.removeChild(el);
  } catch (e) {
    console.warn('removeTyping error:', e);
  }
}

function clearChat() {
  newChat();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMsg();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// ── VOICE INPUT ──
function startVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    alert('Voice input requires a modern browser (Chrome, Edge, etc.)');
    return;
  }

  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;
  voiceText = '';

  document.getElementById('voiceModal').classList.add('active');
  document.getElementById('voiceTranscript').textContent = 'Listening...';
  document.getElementById('voiceBtn').classList.add('recording');

  recognition.onresult = (e) => {
    let f = '', i = '';
    for (let x = e.resultIndex; x < e.results.length; x++) {
      if (e.results[x].isFinal) f += e.results[x][0].transcript;
      else i += e.results[x][0].transcript;
    }
    if (f) voiceText += f;
    document.getElementById('voiceTranscript').textContent = (voiceText + i) || 'Listening...';
  };

  recognition.onerror = (e) => {
    document.getElementById('voiceStatus').textContent = 'Error: ' + (e.error || 'Unknown error');
  };

  recognition.start();
}

function stopVoice() {
  if (recognition) recognition.stop();
  document.getElementById('voiceModal').classList.remove('active');
  document.getElementById('voiceBtn').classList.remove('recording');
  if (voiceText.trim()) {
    document.getElementById('msgInput').value = voiceText.trim();
    sendMsg();
  }
}

// ── MODALS & SETTINGS ──
function showSettingsModal() {
  document.getElementById('settingsModal').classList.add('active');
  document.getElementById('userDropdown').classList.remove('active');

  // Load current theme setting
  const isDark = localStorage.getItem('theme') === 'dark';
  document.getElementById('themeToggle').classList.toggle('active', isDark);
  if (isDark) document.body.classList.add('dark-theme');
}

function closeSettingsModal() {
  document.getElementById('settingsModal').classList.remove('active');
}

// Toggle rating on message
async function rateMessage(btn, type) {
  btn.classList.add('active');
  const sibling = btn.parentElement.querySelector(`.feedback-btn:not([onclick*="${type}"])`);
  if (sibling) sibling.classList.remove('active');
  
  try {
    await fetch('/api/feedback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify({
        rating: type === 'up' ? 5 : 1,
        category: 'ai_response',
        comment: 'Quick rating: ' + type
      })
    });
  } catch(e) {
    console.warn('Rating failed:', e);
  }
}

function toggleTheme() {
  const isDark = document.body.classList.toggle('dark-theme');
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  document.getElementById('themeToggle').classList.toggle('active', isDark);
}

async function changePassword() {
  const current = document.getElementById('currentPassword').value;
  const newPass = document.getElementById('newPassword').value;
  const confirm = document.getElementById('confirmPassword').value;

  if (!current || !newPass || !confirm) {
    alert('Please fill all fields');
    return;
  }

  if (newPass !== confirm) {
    alert('New passwords do not match');
    return;
  }

  if (newPass.length < 6) {
    alert('Password must be at least 6 characters');
    return;
  }

  try {
    const res = await fetch('/api/change-password', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify({
        current_password: current,
        new_password: newPass
      })
    });

    const data = await res.json();
    if (res.ok) {
      alert(data.message);
      closeSettingsModal();
      document.getElementById('currentPassword').value = '';
      document.getElementById('newPassword').value = '';
      document.getElementById('confirmPassword').value = '';
    } else {
      alert(data.error || 'Failed to change password');
    }
  } catch (err) {
    alert('Connection error');
  }
}

async function exportChatHistory() {
  if (!currentSessionId) {
    alert('No active chat to export');
    return;
  }

  try {
    const res = await fetch(`/api/messages/${currentSessionId}`);
    if (!res.ok) return;
    const data = await res.json();

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-history-${currentSessionId}.json`;
    a.click();
    URL.revokeObjectURL(url);

    alert('Chat history exported successfully!');
  } catch (err) {
    alert('Error exporting chat history');
  }
}

function clearAllData() {
  if (!confirm('Are you sure you want to delete all your local data? This cannot be undone.')) {
    return;
  }

  localStorage.removeItem('theme');
  document.body.classList.remove('dark-theme');
  document.getElementById('themeToggle').classList.remove('active');

  newChat();
  alert('All local data has been cleared.');
}

// ── TICKETS & FEEDBACK ──
function showTicketModal() {
  document.getElementById('ticketModal').classList.add('active');
  document.getElementById('userDropdown').classList.remove('active');
}

function closeTicketModal() {
  document.getElementById('ticketModal').classList.remove('active');
}

function showFeedbackModal() {
  document.getElementById('feedbackModal').classList.add('active');
  document.getElementById('userDropdown').classList.remove('active');
}

function closeFeedbackModal() {
  document.getElementById('feedbackModal').classList.remove('active');
}

function setRating(rating) {
  selectedRating = rating;
  const buttons = document.querySelectorAll('#ratingStars .feedback-btn');
  buttons.forEach((btn, i) => {
    btn.classList.toggle('active', i < rating);
  });
}

async function submitTicket() {
  const subject = document.getElementById('ticketSubject').value;
  const description = document.getElementById('ticketDescription').value;
  const priority = document.getElementById('ticketPriority').value;

  if (!subject || !description) {
    alert('Please fill all fields');
    return;
  }

  try {
    const res = await fetch('/api/tickets', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify({ subject, description, priority })
    });

    const data = await res.json();
    if (res.ok) {
      alert(`Ticket #${data.ticket_id} created!`);
      closeTicketModal();
      document.getElementById('ticketSubject').value = '';
      document.getElementById('ticketDescription').value = '';
    } else {
      alert(data.error || 'Failed to create ticket');
    }
  } catch (e) {
    alert('Error submitting ticket');
  }
}

async function submitFeedback() {
  if (selectedRating === 0) {
    alert('Please select a rating');
    return;
  }

  const category = document.getElementById('feedbackCategory').value;
  const comment = document.getElementById('feedbackComment').value;

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify({ rating: selectedRating, category, comment })
    });

    const data = await res.json();
    if (res.ok) {
      alert('Thank you for your feedback!');
      closeFeedbackModal();
      document.getElementById('feedbackComment').value = '';
      setRating(0);
    } else {
      alert(data.error || 'Failed to submit feedback');
    }
  } catch (err) {
    alert('Error submitting feedback');
  }
}

// ── INITIALIZATION ──
window.addEventListener('DOMContentLoaded', () => {
  loadSessions();

  // Apply saved theme
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'dark') {
    document.body.classList.add('dark-theme');
    const toggle = document.getElementById('themeToggle');
    if (toggle) toggle.classList.add('active');
  }
});

/**
 * PublicLens Chat Client — Multi-board, multi-meeting version with video player
 */

const API_BASE = '';
let conversationHistory = [];
let activeClipId = null;
let activeBoard = null;
let hlsInstance = null;

// Search state
let searchAbortController = null;
let searchDebounceTimer = null;
let searchActiveViewIds = new Set();  // empty = all boards
let allBoardsData = [];  // cached board list for filters

// ─── DOM Elements ───

const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const chatInputArea = document.getElementById('chat-input-area');
const chatHeaderTitle = document.getElementById('chat-header-title');
const emptyState = document.getElementById('empty-state');
const welcomeMessage = document.getElementById('welcome-message');
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');

// Sidebar panels
const boardSelector = document.getElementById('board-selector');
const meetingSelector = document.getElementById('meeting-selector');
const meetingInfo = document.getElementById('meeting-info');

// Video player
const videoPanel = document.getElementById('video-panel');
const videoContainer = document.getElementById('video-container');
const videoEl = document.getElementById('meeting-video');
const videoToggleBtn = document.getElementById('video-toggle-btn');
const videoError = document.getElementById('video-error');

// ─── Initialize ───

document.addEventListener('DOMContentLoaded', () => {
    loadBoards();
    setupEventListeners();
});

function setupEventListeners() {
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        sendMessage();
    });

    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
        sendBtn.disabled = !chatInput.value.trim();
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (chatInput.value.trim()) sendMessage();
        }
    });

    // Back navigation
    document.getElementById('back-to-boards').addEventListener('click', showBoards);
    document.getElementById('back-to-meetings').addEventListener('click', () => {
        if (activeBoard) showMeetings(activeBoard);
    });

    // Sidebar toggle (mobile)
    sidebarToggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        toggleOverlay();
    });

    // Video toggle
    videoToggleBtn.addEventListener('click', () => {
        videoContainer.classList.toggle('collapsed');
        videoToggleBtn.classList.toggle('collapsed');
        if (videoContainer.classList.contains('collapsed')) {
            videoEl.pause();
        }
    });

    // Search — debounced input
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', () => {
        clearTimeout(searchDebounceTimer);
        const query = searchInput.value.trim();

        if (!query) {
            clearSearch();
            return;
        }

        document.getElementById('search-clear-btn').style.display = 'flex';
        searchDebounceTimer = setTimeout(() => performSearch(query), 300);
    });

    // Search — clear button
    document.getElementById('search-clear-btn').addEventListener('click', () => {
        searchInput.value = '';
        clearSearch();
        searchInput.focus();
    });

    // Search — filters toggle
    document.getElementById('search-filters-toggle').addEventListener('click', () => {
        const filtersEl = document.getElementById('search-filters');
        const toggleBtn = document.getElementById('search-filters-toggle');
        const isVisible = filtersEl.style.display !== 'none';
        filtersEl.style.display = isVisible ? 'none' : 'block';
        toggleBtn.classList.toggle('active', !isVisible);
    });

    // Search — date filter changes trigger re-search
    document.getElementById('date-from').addEventListener('change', () => {
        const query = searchInput.value.trim();
        if (query) performSearch(query);
    });
    document.getElementById('date-to').addEventListener('change', () => {
        const query = searchInput.value.trim();
        if (query) performSearch(query);
    });
}

// ─── Board & Meeting Selection ───

async function loadBoards() {
    try {
        const resp = await fetch(`${API_BASE}/api/boards`);
        const boards = await resp.json();

        // Cache for search filters
        allBoardsData = boards;

        const boardList = document.getElementById('board-list');

        if (boards.length === 0) {
            boardList.innerHTML = `
                <div class="empty-boards">
                    <p>No meetings processed yet.</p>
                    <p class="hint">Run the pipeline to add meetings.</p>
                </div>
            `;
            return;
        }

        boardList.innerHTML = boards.map(b => `
            <button class="board-item" data-view-id="${b.view_id}" data-name="${b.name}" data-short="${b.short_name}" data-color="${b.color}" onclick="showMeetings(this.dataset)">
                <span class="board-dot" style="background:${b.color};box-shadow:0 0 8px ${b.color}"></span>
                <span class="board-item-name">${b.name}</span>
                <span class="board-item-count">${b.processed_count}</span>
            </button>
        `).join('');

        // Populate search filter chips
        const chipsContainer = document.getElementById('board-filter-chips');
        chipsContainer.innerHTML = boards.map(b => `
            <button class="board-filter-chip" data-view-id="${b.view_id}" onclick="toggleBoardFilter('${b.view_id}', this)">
                <span class="chip-dot" style="background:${b.color}"></span>
                ${b.short_name}
            </button>
        `).join('');
    } catch (err) {
        console.error('Failed to load boards:', err);
    }
}

async function showMeetings(boardData) {
    activeBoard = boardData;

    // Update UI
    boardSelector.style.display = 'none';
    meetingInfo.style.display = 'none';
    meetingSelector.style.display = 'block';
    document.getElementById('search-results-panel').style.display = 'none';

    document.getElementById('meetings-board-name').textContent = boardData.name;
    const dot = document.getElementById('meetings-board-dot');
    dot.style.background = boardData.color;
    dot.style.boxShadow = `0 0 8px ${boardData.color}`;

    const meetingList = document.getElementById('meeting-list');
    meetingList.innerHTML = '<div class="loading-placeholder"><div class="spinner"></div></div>';

    try {
        const resp = await fetch(`${API_BASE}/api/meetings?view_id=${boardData.viewId || boardData.view_id}`);
        const meetings = await resp.json();

        if (meetings.length === 0) {
            meetingList.innerHTML = '<p class="no-meetings">No meetings processed for this board yet.</p>';
            return;
        }

        meetingList.innerHTML = meetings.map(m => `
            <button class="meeting-item ${m.clip_id === activeClipId ? 'active' : ''}"
                    data-clip-id="${m.clip_id}"
                    onclick="selectMeeting('${m.clip_id}')">
                <div class="meeting-item-date">${m.date}</div>
                <div class="meeting-item-name">${cleanMeetingName(m.name)}</div>
                <div class="meeting-item-duration">${m.duration}</div>
            </button>
        `).join('');
    } catch (err) {
        meetingList.innerHTML = '<p class="error">Failed to load meetings</p>';
        console.error(err);
    }
}

function showBoards() {
    boardSelector.style.display = 'block';
    meetingSelector.style.display = 'none';
    meetingInfo.style.display = 'none';
    document.getElementById('search-results-panel').style.display = 'none';
}

// ─── Cross-Meeting Search ───

async function performSearch(query) {
    // Abort any in-flight search
    if (searchAbortController) {
        searchAbortController.abort();
    }
    searchAbortController = new AbortController();

    const spinner = document.getElementById('search-spinner');
    const clearBtn = document.getElementById('search-clear-btn');
    spinner.style.display = 'flex';
    clearBtn.style.display = 'none';

    // Build filter params
    const viewIds = searchActiveViewIds.size > 0
        ? Array.from(searchActiveViewIds)
        : null;  // null = all boards

    const dateFromEl = document.getElementById('date-from');
    const dateToEl = document.getElementById('date-to');
    let dateFrom = null;
    let dateTo = null;

    if (dateFromEl.value) {
        // month input gives "YYYY-MM" — convert to unix timestamp (start of month)
        dateFrom = Math.floor(new Date(dateFromEl.value + '-01').getTime() / 1000);
    }
    if (dateToEl.value) {
        // End of the selected month
        const d = new Date(dateToEl.value + '-01');
        d.setMonth(d.getMonth() + 1);
        dateTo = Math.floor(d.getTime() / 1000);
    }

    try {
        const resp = await fetch(`${API_BASE}/api/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                view_ids: viewIds,
                date_from: dateFrom,
                date_to: dateTo,
                top_k: 12,
            }),
            signal: searchAbortController.signal,
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Search failed');
        }

        const data = await resp.json();
        renderSearchResults(data, query);
    } catch (err) {
        if (err.name === 'AbortError') return;  // cancelled, ignore
        console.error('Search error:', err);
        const resultsList = document.getElementById('search-results-list');
        resultsList.innerHTML = `<div class="search-no-results"><p>Search error: ${escapeHtml(err.message)}</p></div>`;
    } finally {
        spinner.style.display = 'none';
        if (document.getElementById('search-input').value.trim()) {
            clearBtn.style.display = 'flex';
        }
    }
}

function renderSearchResults(data, query) {
    const resultsPanel = document.getElementById('search-results-panel');
    const resultsHeader = document.getElementById('search-results-header');
    const resultsList = document.getElementById('search-results-list');

    // Show results panel, hide board/meeting selectors
    resultsPanel.style.display = 'flex';
    boardSelector.style.display = 'none';
    meetingSelector.style.display = 'none';
    meetingInfo.style.display = 'none';

    const results = data.results || [];
    const meetingCount = new Set(results.map(r => r.clip_id)).size;

    if (results.length === 0) {
        resultsHeader.textContent = `No results found`;
        resultsList.innerHTML = `
            <div class="search-no-results">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <p>No matches for "${escapeHtml(query)}"</p>
                <p style="font-size:11px;margin-top:4px;">Try different keywords or adjust your filters.</p>
            </div>
        `;
        return;
    }

    resultsHeader.textContent = `${results.length} result${results.length !== 1 ? 's' : ''} across ${meetingCount} meeting${meetingCount !== 1 ? 's' : ''}`;

    // Find max score for relative bar widths
    const maxScore = Math.max(...results.map(r => r.score));

    resultsList.innerHTML = results.map(r => {
        const scorePercent = maxScore > 0 ? Math.round((r.score / maxScore) * 100) : 0;
        const snippet = highlightSnippet(r.text, query);
        const meetingName = cleanMeetingName(r.meeting_name);

        return `
            <div class="search-result-card" onclick="selectSearchResult('${r.clip_id}', ${r.start_time || 0}, '${r.view_id}')">
                <div class="search-result-snippet">${snippet}</div>
                <div class="search-result-meta">
                    <div class="search-result-meeting">
                        <span class="search-result-badge">
                            <span class="badge-dot" style="background:${r.board_color}"></span>
                            ${escapeHtml(r.board_short_name)}
                        </span>
                        <span class="search-result-date">${escapeHtml(r.meeting_date)}</span>
                    </div>
                    <span class="search-result-timestamp">▶ ${escapeHtml(r.timestamp)}</span>
                </div>
                <div class="search-result-score-bar">
                    <div class="search-result-score-fill" style="width:${scorePercent}%"></div>
                </div>
            </div>
        `;
    }).join('');
}

function highlightSnippet(text, query) {
    const escaped = escapeHtml(text);
    if (!query) return escaped;

    // Highlight each word of the query in the snippet
    const words = query.split(/\s+/).filter(w => w.length > 2);
    let result = escaped;
    for (const word of words) {
        const regex = new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        result = result.replace(regex, '<mark>$1</mark>');
    }
    return result;
}

function toggleBoardFilter(viewId, chipEl) {
    chipEl.classList.toggle('active');

    if (searchActiveViewIds.has(viewId)) {
        searchActiveViewIds.delete(viewId);
    } else {
        searchActiveViewIds.add(viewId);
    }

    // Re-run search if there's a query
    const query = document.getElementById('search-input').value.trim();
    if (query) performSearch(query);
}

function clearSearch() {
    // Cancel pending requests
    if (searchAbortController) {
        searchAbortController.abort();
        searchAbortController = null;
    }
    clearTimeout(searchDebounceTimer);

    // Reset UI
    document.getElementById('search-clear-btn').style.display = 'none';
    document.getElementById('search-spinner').style.display = 'none';
    document.getElementById('search-results-panel').style.display = 'none';

    // Show the appropriate sidebar panel
    if (meetingInfo.style.display !== 'none') {
        // Leave meeting info showing
    } else if (meetingSelector.style.display !== 'none') {
        // Leave meeting selector showing
    } else {
        boardSelector.style.display = 'block';
    }
}

async function selectSearchResult(clipId, startTime, viewId) {
    // Find board data for this result
    const board = allBoardsData.find(b => b.view_id === viewId);
    if (board) {
        activeBoard = board;
    }

    // Navigate to the meeting (reuses existing selectMeeting)
    await selectMeeting(clipId);

    // Seek video to the relevant timestamp
    if (startTime > 0) {
        setTimeout(() => seekVideo(startTime), 500);
    }
}

async function selectMeeting(clipId) {
    activeClipId = clipId;
    conversationHistory = [];

    // Highlight active meeting in list
    document.querySelectorAll('.meeting-item').forEach(el => {
        el.classList.toggle('active', el.dataset.clipId === clipId);
    });

    // Show meeting info panel
    meetingSelector.style.display = 'none';
    meetingInfo.style.display = 'block';
    document.getElementById('back-board-name').textContent = activeBoard.name || activeBoard.short;

    // Load meeting data
    try {
        const resp = await fetch(`${API_BASE}/api/meeting?clip_id=${clipId}`);
        const data = await resp.json();

        if (data.meeting) {
            document.getElementById('meeting-name').textContent = cleanMeetingName(data.meeting.name);
            document.getElementById('meeting-date').textContent = data.meeting.date || '—';
            document.getElementById('meeting-duration').textContent = data.meeting.duration || '—';

            // Board label
            const boardLabel = document.getElementById('active-board-label');
            boardLabel.textContent = activeBoard.name || activeBoard.short;
            const badgeDot = document.getElementById('active-badge-dot');
            const color = activeBoard.color;
            badgeDot.style.background = color;
            badgeDot.style.boxShadow = `0 0 8px ${color}`;

            // Initialize video player
            initVideoPlayer(data.meeting.stream_url);
        }

        // Populate summary
        if (data.summary) {
            populateSummary(data.summary);
        }
    } catch (err) {
        console.error('Failed to load meeting:', err);
    }

    // Activate chat area
    emptyState.style.display = 'none';
    chatInputArea.style.display = 'block';
    chatHeaderTitle.textContent = 'Ask about this meeting';

    // Clear old messages, show welcome
    clearChat();
    welcomeMessage.style.display = 'flex';

    // Rebind suggestion chips
    document.querySelectorAll('.chip').forEach(chip => {
        chip.onclick = () => {
            chatInput.value = chip.dataset.question;
            sendBtn.disabled = false;
            sendMessage();
        };
    });
}

function clearChat() {
    // Remove all messages except welcome
    const messages = chatMessages.querySelectorAll('.message:not(#welcome-message)');
    messages.forEach(m => m.remove());
    welcomeMessage.style.display = 'none';
}

function cleanMeetingName(name) {
    return name
        .replace(/^\d{8}\s*/, '')
        .replace(/^(BOF|BOR|BOE)\s+/, '')
        .trim();
}

// ─── Video Player ───

function initVideoPlayer(streamUrl) {
    // Destroy previous HLS instance
    if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
    }

    videoError.style.display = 'none';
    videoEl.style.display = 'block';

    if (!streamUrl) {
        videoPanel.style.display = 'none';
        return;
    }

    videoPanel.style.display = 'block';
    videoContainer.classList.remove('collapsed');
    videoToggleBtn.classList.remove('collapsed');

    if (Hls.isSupported()) {
        hlsInstance = new Hls();
        hlsInstance.loadSource(streamUrl);
        hlsInstance.attachMedia(videoEl);
        hlsInstance.on(Hls.Events.ERROR, (event, data) => {
            console.warn('HLS error:', data);
            if (data.fatal) {
                showVideoError();
            }
        });
    } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
        // Safari native HLS support
        videoEl.src = streamUrl;
    } else {
        showVideoError();
    }
}

function showVideoError() {
    videoEl.style.display = 'none';
    videoError.style.display = 'flex';
}

function seekVideo(seconds) {
    if (!videoEl || !videoPanel || videoPanel.style.display === 'none') return;

    // Expand video if collapsed
    videoContainer.classList.remove('collapsed');
    videoToggleBtn.classList.remove('collapsed');

    videoEl.currentTime = seconds;
    videoEl.play().catch(() => {});

    // Flash highlight on the video panel
    videoPanel.classList.add('seeking');
    setTimeout(() => videoPanel.classList.remove('seeking'), 800);
}

function parseTimestamp(ts) {
    // Parses "HH:MM:SS" or "MM:SS" to seconds
    const parts = ts.split(':').map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return 0;
}

// ─── Summary ───

function populateSummary(summary) {
    const summarySection = document.getElementById('summary-section');
    summarySection.style.display = 'block';

    const summaryText = document.getElementById('summary-text');
    const execSummary = summary.executive_summary || '';
    const firstParagraph = execSummary.split('\n\n')[0];
    summaryText.textContent = firstParagraph.length > 300
        ? firstParagraph.substring(0, 300) + '...'
        : firstParagraph;

    const topicsList = document.getElementById('key-topics');
    const topics = summary.key_topics || [];
    if (topics.length > 0) {
        topicsList.innerHTML = topics.slice(0, 4).map(t => `
            <div class="topic-item">
                <h4>${escapeHtml(t.topic)}</h4>
                <p>${escapeHtml(t.summary)}</p>
            </div>
        `).join('');
    } else {
        topicsList.innerHTML = '';
    }

    const decisions = summary.decisions_and_votes || [];
    const decisionsSection = document.getElementById('decisions-section');
    if (decisions.length > 0) {
        const decisionsList = document.getElementById('decisions-list');
        decisionsSection.style.display = 'block';
        decisionsList.innerHTML = decisions.map(d => {
            const outcome = (d.outcome || '').toLowerCase();
            let cls = 'other';
            if (outcome.includes('pass') || outcome.includes('approv') || outcome.includes('unanimous')) cls = 'passed';
            else if (outcome.includes('fail') || outcome.includes('reject')) cls = 'failed';
            return `
                <div class="decision-item">
                    <p>${escapeHtml(d.description)}</p>
                    <span class="decision-outcome ${cls}">${escapeHtml(d.outcome || 'N/A')}</span>
                </div>
            `;
        }).join('');
    } else {
        decisionsSection.style.display = 'none';
    }
}

// ─── Chat ───

async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question || !activeClipId) return;

    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendBtn.disabled = true;

    const chips = document.querySelector('.suggestion-chips');
    if (chips) chips.style.display = 'none';

    appendMessage('user', question);
    const thinkingEl = appendThinking();
    conversationHistory.push({ role: 'user', content: question });

    try {
        const resp = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: question,
                clip_id: activeClipId,
                history: conversationHistory.slice(-6),
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Chat request failed');
        }

        const data = await resp.json();
        thinkingEl.remove();
        appendMessage('assistant', data.answer, data.sources);
        conversationHistory.push({ role: 'assistant', content: data.answer });
    } catch (err) {
        thinkingEl.remove();
        appendMessage('assistant', `Sorry, I encountered an error: ${err.message}`);
        console.error('Chat error:', err);
    }
}

// ─── UI Helpers ───

function appendMessage(role, content, sources) {
    const isUser = role === 'user';
    const div = document.createElement('div');
    div.className = `message ${isUser ? 'user' : 'assistant'}-message`;

    const avatarSvg = isUser
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>';

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        const chips = sources
            .filter(s => s.timestamp && s.timestamp !== 'N/A')
            .slice(0, 4)
            .map(s => {
                const secs = parseTimestamp(s.timestamp);
                return `<button class="source-chip" onclick="seekVideo(${secs})" title="Jump to ${s.timestamp} in video"><span class="source-play">▶</span><span class="source-time">${escapeHtml(s.timestamp)}</span></button>`;
            })
            .join('');
        if (chips) {
            sourcesHtml = `<div class="message-sources"><div class="sources-label">Jump to transcript</div>${chips}</div>`;
        }
    }

    div.innerHTML = `
        <div class="message-avatar">${avatarSvg}</div>
        <div class="message-content">${formatMarkdown(content)}${sourcesHtml}</div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom();
}

function appendThinking() {
    const div = document.createElement('div');
    div.className = 'message assistant-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
        </div>
        <div class="message-content">
            <div class="thinking-indicator">
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
            </div>
        </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    requestAnimationFrame(() => { chatMessages.scrollTop = chatMessages.scrollHeight; });
}

function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    // Make timestamp ranges clickable — [1:28:02 - 1:31:10] or [35:50 - 38:29]
    html = html.replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (match, startTs, endTs) => {
        const secs = parseTimestamp(startTs);
        return `<button class="timestamp-link" onclick="seekVideo(${secs})" title="Jump to ${startTs}">▶ ${startTs} – ${endTs}</button>`;
    });
    // Make single timestamps clickable — [HH:MM:SS] or [MM:SS]
    html = html.replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (match, ts) => {
        const secs = parseTimestamp(ts);
        return `<button class="timestamp-link" onclick="seekVideo(${secs})" title="Jump to ${ts}">▶ ${ts}</button>`;
    });
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/^[-•]\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/\n/g, '<br>');
    html = html.replace(/<p>\s*<\/p>/g, '');
    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function toggleOverlay() {
    let overlay = document.querySelector('.sidebar-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('visible');
        });
        document.body.appendChild(overlay);
    }
    overlay.classList.toggle('visible', sidebar.classList.contains('open'));
}

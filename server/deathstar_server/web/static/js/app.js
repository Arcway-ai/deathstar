// app.js — Main application logic

(() => {
  // ---- State ----
  let currentRepo = null;
  let currentConversationId = null;
  let currentWorkflow = 'prompt';
  let sending = false;
  let elapsedTimer = null;

  // ---- DOM refs ----
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const menuBtn        = $('#menu-btn');
  const repoBtn        = $('#repo-btn');
  const repoLabel      = $('#repo-label');
  const settingsBtn    = $('#settings-btn');
  const repoPicker     = $('#repo-picker');
  const repoList       = $('#repo-list');
  const sidebar        = $('#sidebar');
  const sidebarBackdrop = $('#sidebar-backdrop');
  const newChatBtn     = $('#new-chat-btn');
  const convoList      = $('#conversation-list');
  const settingsPanel  = $('#settings-panel');
  const tokenInput     = $('#api-token-input');
  const providerSelect = $('#provider-select');
  const modelInput     = $('#model-input');
  const saveSettingsBtn = $('#save-settings-btn');
  const chatView       = $('#chat-view');
  const emptyState     = $('#empty-state');
  const messagesEl     = $('#messages');
  const loadingEl      = $('#loading');
  const elapsedEl      = $('#elapsed');
  const inputBar       = $('#input-bar');
  const messageInput   = $('#message-input');
  const sendBtn        = $('#send-btn');
  const writeChangesRow = $('#write-changes-row');
  const writeChangesToggle = $('#write-changes-toggle');

  // ---- Init ----
  function init() {
    tokenInput.value = Api.getToken();
    modelInput.value = localStorage.getItem('deathstar_model') || '';

    bindEvents();
    loadProviders();

    const savedRepo = localStorage.getItem('deathstar_repo');
    if (savedRepo) {
      selectRepo(savedRepo);
    }
  }

  // ---- Events ----
  function bindEvents() {
    menuBtn.addEventListener('click', toggleSidebar);
    repoBtn.addEventListener('click', openRepoPicker);
    settingsBtn.addEventListener('click', () => settingsPanel.classList.remove('hidden'));
    saveSettingsBtn.addEventListener('click', saveSettings);

    $$('.close-overlay').forEach(btn => {
      btn.addEventListener('click', () => btn.closest('.overlay').classList.add('hidden'));
    });

    sidebarBackdrop.addEventListener('click', closeSidebar);
    newChatBtn.addEventListener('click', () => { startNewChat(); closeSidebar(); });

    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('input', onInputChange);
    messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    $$('.workflow-pill').forEach(pill => {
      pill.addEventListener('click', () => selectWorkflow(pill.dataset.workflow));
    });
  }

  // ---- Repo picker ----
  async function openRepoPicker() {
    repoPicker.classList.remove('hidden');
    repoList.innerHTML = '<div class="empty-state" style="padding:40px"><p>Loading...</p></div>';
    try {
      const repos = await Api.get('/web/api/repos');
      if (repos.length === 0) {
        repoList.innerHTML = '<div class="empty-state" style="padding:40px"><p>No repos found in /workspace/projects</p></div>';
        return;
      }
      repoList.innerHTML = repos.map(r => `
        <div class="repo-card ${r.name === currentRepo ? 'active' : ''}" data-repo="${esc(r.name)}">
          <div>
            <div class="repo-name">${esc(r.name)}</div>
            <div class="repo-meta">
              <span class="repo-branch">${esc(r.branch)}</span>
              ${r.dirty ? '<span class="repo-dirty">modified</span>' : ''}
            </div>
          </div>
        </div>
      `).join('');
      repoList.querySelectorAll('.repo-card').forEach(card => {
        card.addEventListener('click', () => {
          selectRepo(card.dataset.repo);
          repoPicker.classList.add('hidden');
        });
      });
    } catch (err) {
      repoList.innerHTML = `<div class="empty-state" style="padding:40px"><p style="color:var(--red)">${esc(err.message)}</p></div>`;
    }
  }

  function selectRepo(name) {
    currentRepo = name;
    localStorage.setItem('deathstar_repo', name);
    repoLabel.textContent = name;
    inputBar.classList.remove('hidden');
    startNewChat();
    loadConversations();
  }

  // ---- Conversations ----
  async function loadConversations() {
    if (!currentRepo) return;
    try {
      const convos = await Api.get(`/web/api/conversations?repo=${encodeURIComponent(currentRepo)}`);
      renderConversationList(convos);
    } catch { /* ignore */ }
  }

  function renderConversationList(convos) {
    if (convos.length === 0) {
      convoList.innerHTML = '<div style="padding:16px;color:var(--text-dim);font-size:13px">No conversations yet</div>';
      return;
    }
    convoList.innerHTML = convos.map(c => `
      <div class="convo-item ${c.id === currentConversationId ? 'active' : ''}" data-id="${esc(c.id)}">
        <div>
          <div class="convo-title">${esc(c.title)}</div>
          <div class="convo-meta">${c.message_count} messages</div>
        </div>
        <button class="convo-delete" data-id="${esc(c.id)}" title="Delete">&times;</button>
      </div>
    `).join('');

    convoList.querySelectorAll('.convo-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('convo-delete')) return;
        openConversation(item.dataset.id);
        closeSidebar();
      });
    });

    convoList.querySelectorAll('.convo-delete').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await deleteConversation(btn.dataset.id);
      });
    });
  }

  async function openConversation(id) {
    try {
      const detail = await Api.get(`/web/api/conversations/${id}`);
      currentConversationId = id;
      emptyState.classList.add('hidden');
      messagesEl.classList.remove('hidden');
      messagesEl.innerHTML = '';
      detail.messages.forEach(m => appendMessage(m));
      scrollToBottom();
      loadConversations();
    } catch (err) {
      showError(err.message);
    }
  }

  async function deleteConversation(id) {
    try {
      await Api.del(`/web/api/conversations/${id}`);
      if (id === currentConversationId) {
        startNewChat();
      }
      loadConversations();
    } catch { /* ignore */ }
  }

  function startNewChat() {
    currentConversationId = null;
    messagesEl.innerHTML = '';
    messagesEl.classList.add('hidden');
    emptyState.classList.remove('hidden');
    emptyState.querySelector('p').textContent = currentRepo
      ? `Chat with DeathStar about ${currentRepo}`
      : 'Select a repo to get started';
  }

  // ---- Sidebar ----
  function toggleSidebar() {
    if (sidebar.classList.contains('hidden') || !sidebar.classList.contains('visible')) {
      openSidebar();
    } else {
      closeSidebar();
    }
  }

  function openSidebar() {
    sidebar.classList.remove('hidden');
    requestAnimationFrame(() => sidebar.classList.add('visible'));
    sidebarBackdrop.classList.remove('hidden');
    loadConversations();
  }

  function closeSidebar() {
    sidebar.classList.remove('visible');
    sidebarBackdrop.classList.add('hidden');
    setTimeout(() => sidebar.classList.add('hidden'), 200);
  }

  // ---- Settings ----
  async function loadProviders() {
    try {
      const providers = await Api.get('/web/api/providers');
      providerSelect.innerHTML = '<option value="">Auto (first configured)</option>';
      for (const [name, info] of Object.entries(providers)) {
        const label = `${name}${info.configured ? '' : ' (not configured)'}`;
        providerSelect.innerHTML += `<option value="${name}" ${!info.configured ? 'disabled' : ''}>${label}</option>`;
      }
      const saved = localStorage.getItem('deathstar_provider');
      if (saved) providerSelect.value = saved;
    } catch { /* settings will still work */ }
  }

  function saveSettings() {
    Api.setToken(tokenInput.value.trim());
    localStorage.setItem('deathstar_provider', providerSelect.value);
    localStorage.setItem('deathstar_model', modelInput.value.trim());
    settingsPanel.classList.add('hidden');
  }

  // ---- Workflow ----
  function selectWorkflow(wf) {
    currentWorkflow = wf;
    $$('.workflow-pill').forEach(p => p.classList.toggle('active', p.dataset.workflow === wf));
    writeChangesRow.classList.toggle('hidden', wf !== 'patch');
  }

  // ---- Sending messages ----
  function onInputChange() {
    const val = messageInput.value.trim();
    sendBtn.disabled = !val || sending;
    // Auto-grow textarea
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
  }

  async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || !currentRepo || sending) return;

    sending = true;
    sendBtn.disabled = true;
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Show user message
    emptyState.classList.add('hidden');
    messagesEl.classList.remove('hidden');
    appendMessage({ role: 'user', content: text });
    scrollToBottom();

    // Show loading
    loadingEl.classList.remove('hidden');
    const startTime = Date.now();
    elapsedEl.textContent = '0s';
    elapsedTimer = setInterval(() => {
      const secs = Math.round((Date.now() - startTime) / 1000);
      elapsedEl.textContent = `${secs}s`;
    }, 1000);

    try {
      const body = {
        repo: currentRepo,
        message: text,
        conversation_id: currentConversationId,
        workflow: currentWorkflow,
        write_changes: writeChangesToggle.checked,
      };

      const savedProvider = localStorage.getItem('deathstar_provider');
      if (savedProvider) body.provider = savedProvider;
      const savedModel = localStorage.getItem('deathstar_model');
      if (savedModel) body.model = savedModel;

      const resp = await Api.post('/web/api/chat', body);
      currentConversationId = resp.conversation_id;

      appendMessage({
        role: 'assistant',
        content: resp.content || resp.error?.message || 'No response',
        workflow: resp.workflow,
        provider: resp.provider,
        model: resp.model,
        duration_ms: resp.duration_ms,
      });

      loadConversations();
    } catch (err) {
      appendMessage({
        role: 'assistant',
        content: `Error: ${err.message}`,
      });
    } finally {
      clearInterval(elapsedTimer);
      loadingEl.classList.add('hidden');
      sending = false;
      onInputChange();
      scrollToBottom();
    }
  }

  // ---- Rendering ----
  function appendMessage(msg) {
    const div = document.createElement('div');
    div.className = `msg msg-${msg.role}`;

    if (msg.role === 'user') {
      div.textContent = msg.content;
    } else {
      const contentDiv = document.createElement('div');
      contentDiv.className = 'msg-content';
      contentDiv.innerHTML = renderMarkdown(msg.content || '');
      div.appendChild(contentDiv);

      // Post-process: add copy buttons and diff coloring
      postProcessCodeBlocks(div);

      if (msg.model || msg.duration_ms) {
        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        const parts = [];
        if (msg.provider) parts.push(msg.provider);
        if (msg.model) parts.push(msg.model);
        if (msg.workflow) parts.push(msg.workflow);
        if (msg.duration_ms != null) parts.push(`${(msg.duration_ms / 1000).toFixed(1)}s`);
        meta.textContent = parts.join(' · ');
        div.appendChild(meta);
      }
    }

    messagesEl.appendChild(div);
  }

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined' && marked.parse) {
      try {
        const raw = marked.parse(text, { breaks: true, gfm: true });
        if (typeof DOMPurify !== 'undefined') {
          return DOMPurify.sanitize(raw);
        }
        return raw;
      } catch { /* fallback */ }
    }
    return escHtml(text).replace(/\n/g, '<br>');
  }

  function postProcessCodeBlocks(container) {
    container.querySelectorAll('pre code').forEach(codeEl => {
      const pre = codeEl.parentElement;
      const lang = (codeEl.className.match(/language-(\w+)/) || [])[1] || '';
      const text = codeEl.textContent;

      // Detect diffs
      const isDiff = lang === 'diff' || text.includes('diff --git ') ||
        (text.includes('--- ') && text.includes('+++ '));

      if (isDiff) {
        codeEl.innerHTML = text.split('\n').map(line => {
          if (line.startsWith('+') && !line.startsWith('+++')) return `<span class="diff-line-add">${escHtml(line)}</span>`;
          if (line.startsWith('-') && !line.startsWith('---')) return `<span class="diff-line-del">${escHtml(line)}</span>`;
          if (line.startsWith('@@')) return `<span class="diff-line-hunk">${escHtml(line)}</span>`;
          return escHtml(line);
        }).join('\n');
      }

      // Add code header with copy button
      const header = document.createElement('div');
      header.className = 'code-header';
      header.innerHTML = `<span>${esc(lang || 'code')}</span><button class="copy-btn">Copy</button>`;
      header.querySelector('.copy-btn').addEventListener('click', () => {
        navigator.clipboard.writeText(text).then(() => {
          header.querySelector('.copy-btn').textContent = 'Copied!';
          setTimeout(() => { header.querySelector('.copy-btn').textContent = 'Copy'; }, 1500);
        });
      });
      pre.parentElement.insertBefore(header, pre);
    });
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      chatView.scrollTop = chatView.scrollHeight;
    });
  }

  function showError(msg) {
    appendMessage({ role: 'assistant', content: `Error: ${msg}` });
    scrollToBottom();
  }

  // ---- Helpers ----
  function esc(str) {
    const el = document.createElement('span');
    el.textContent = str || '';
    return el.innerHTML;
  }

  function escHtml(str) {
    return (str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---- Boot ----
  init();
})();

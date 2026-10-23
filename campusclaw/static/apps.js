(() => {
  const root = document.getElementById('apps-root');
  if (!root) return;
  const csrf = root.dataset.csrf;
  const $ = (id) => document.getElementById(id);
  let conversation = null, prompts = [], skills = [];
  const api = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { 'X-CSRF-Token': csrf, ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };
  const option = (value, label) => new Option(label, value);
  const report = (error) => { $('chat-status').textContent = error.message || String(error); };
  const refresh = async () => {
    const [appData, promptData, skillData] = await Promise.all([api('/api/apps'), api('/api/prompts'), api('/api/skills')]);
    prompts = promptData.prompts; skills = skillData.skills;
    const current = $('app-key').value;
    $('app-key').replaceChildren(...appData.apps.map(x => option(x.key, x.name)));
    if (current) $('app-key').value = current;
    if ($('prompt-app')) $('prompt-app').replaceChildren(...appData.apps.map(x => option(x.key, x.name)));
    $('skill-id').replaceChildren(option('', '使用应用默认技能'), ...skills.map(x => option(x.builtin ? `builtin:${x.key}` : `skill:${x.id}`, `${x.name}${x.builtin ? ' · 内置' : ''}`)));
    if ($('prompt-edit')) $('prompt-edit').replaceChildren(option('', '新建模板'), ...prompts.map(x => option(x.id, `${x.name} · ${x.app_key}`)));
    if ($('skill-edit')) $('skill-edit').replaceChildren(option('', '新建技能'), ...skills.filter(x => !x.builtin).map(x => option(x.id, x.name)));
    const renderPrompts = () => $('prompt-id').replaceChildren(option('', '使用应用默认提示词'), ...prompts.filter(x => x.app_key === $('app-key').value).map(x => option(x.id, x.name)));
    $('app-key').onchange = renderPrompts; renderPrompts();
  };
  $('chat-start').onsubmit = async (event) => {
    event.preventDefault();
    try {
      const choice = $('skill-id').value;
      const body = { app_key: $('app-key').value, prompt_id: $('prompt-id').value || null,
        skill_id: choice.startsWith('skill:') ? Number(choice.slice(6)) : null,
        builtin_skill: choice.startsWith('builtin:') ? choice.slice(8) : null };
      conversation = (await api('/api/conversations', { method: 'POST', body: JSON.stringify(body) })).conversation.id;
      $('conversation-label').textContent = `#${conversation}`;
      $('chat-history').replaceChildren(); $('chat-panel').hidden = false;
      $('chat-status').textContent = '会话已创建';
    } catch (error) { report(error); }
  };
  $('chat-send').onsubmit = async (event) => {
    event.preventDefault();
    if (!conversation) return;
    const query = $('chat-query').value.trim();
    const question = document.createElement('p'); question.textContent = `你：${query}`;
    const answer = document.createElement('p'); answer.textContent = '助手：';
    $('chat-history').append(question, answer);
    $('chat-query').value = ''; $('chat-status').textContent = '正在生成…';
    $('chat-citations').replaceChildren(); $('chat-tools').replaceChildren();
    try {
      const response = await fetch(`/api/conversations/${conversation}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify({ query }) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, index); buffer = buffer.slice(index + 2);
          const type = frame.match(/^event: (.+)$/m)?.[1]; const raw = frame.match(/^data: (.+)$/m)?.[1];
          if (!type || !raw) continue;
          const data = JSON.parse(raw);
          if (type === 'delta') answer.textContent += data.content;
          if (type === 'meta') {
            $('chat-citations').textContent = `引用：${data.citations.map(x => `${x.title} #${x.chunk_index}`).join('；') || '无'}`;
            $('chat-tools').textContent = `工具：${data.tool_calls.map(x => `${x.tool} (${x.status})`).join('；') || '无'}`;
          }
          if (type === 'done') $('chat-status').textContent = data.status === 'ok' ? '完成' : `失败：${data.error}`;
        }
      }
    } catch (error) { report(error); }
  };
  if ($('prompt-form')) $('prompt-form').onsubmit = async (event) => {
    event.preventDefault(); const form = new FormData(event.target);
    try {
      const edit = $('prompt-edit').value;
      await api(edit ? `/api/prompts/${edit}` : '/api/prompts', { method: edit ? 'PUT' : 'POST', body: JSON.stringify(edit ? { content: form.get('content') } : Object.fromEntries(form)) });
      event.target.reset(); event.target.elements.name.readOnly = false; event.target.elements.app_key.disabled = false;
      await refresh(); $('chat-status').textContent = '模板已保存';
    } catch (error) { report(error); }
  };
  if ($('prompt-edit')) $('prompt-edit').onchange = () => {
    const row = prompts.find(x => String(x.id) === $('prompt-edit').value), form = $('prompt-form');
    form.elements.name.value = row?.name || ''; form.elements.app_key.value = row?.app_key || 'solver'; form.elements.content.value = row?.content || '';
    form.elements.name.readOnly = !!row; form.elements.app_key.disabled = !!row;
  };
  if ($('skill-form')) $('skill-form').onsubmit = async (event) => {
    event.preventDefault(); const form = new FormData(event.target); const tools = (form.get('tools') || '').split(',').map(x => x.trim()).filter(Boolean);
    try {
      const edit = $('skill-edit').value;
      if (edit) { await api(`/api/skills/${edit}`, { method: 'PUT', body: JSON.stringify({ description: form.get('description'), content: form.get('file')?.size ? await form.get('file').text() : form.get('content'), tools }) }); }
      else if (form.get('file')?.size) { form.set('tools', JSON.stringify(tools)); await api('/api/skills', { method: 'POST', body: form }); }
      else { await api('/api/skills', { method: 'POST', body: JSON.stringify({ name: form.get('name'), description: form.get('description'), content: form.get('content'), tools }) }); }
      event.target.reset(); event.target.elements.name.readOnly = false;
      await refresh(); $('chat-status').textContent = '技能已保存';
    } catch (error) { report(error); }
  };
  if ($('skill-edit')) $('skill-edit').onchange = () => {
    const row = skills.find(x => String(x.id) === $('skill-edit').value), form = $('skill-form');
    form.elements.name.value = row?.name || ''; form.elements.description.value = row?.description || '';
    form.elements.content.value = row?.content || ''; form.elements.tools.value = row?.tools.join(',') || '';
    form.elements.name.readOnly = !!row;
  };
  const refreshMcp = async () => {
    if (!$('mcp-servers')) return;
    const [servers, audits] = await Promise.all([api('/api/mcp/servers'), api('/api/mcp/audits')]);
    $('mcp-servers').replaceChildren();
    servers.servers.forEach(x => {
      const row = document.createElement('p'); row.textContent = `${x.name}：${x.connected ? '已连接' : '未连接'}；工具：${x.tools.map(t => t.name).join(', ') || '无'} `;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = x.connected ? '断开' : '连接';
      button.onclick = async () => { try { await api(`/api/mcp/servers/${x.id}/${x.connected ? 'disconnect' : 'connect'}`, { method: 'POST' }); await refreshMcp(); } catch (error) { report(error); } };
      row.append(button); $('mcp-servers').append(row);
    });
    $('mcp-audits').textContent = audits.audits.map(x => `${x.tool} · ${x.status} · 用户 ${x.user_id} · ${x.created_at}`).join('；') || '暂无调用';
  };
  if ($('mcp-form')) $('mcp-form').onsubmit = async (event) => {
    event.preventDefault(); try { await api('/api/mcp/servers', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) }); event.target.reset(); await refreshMcp(); } catch (error) { report(error); }
  };
  refresh().catch(report); refreshMcp().catch(report);
})();

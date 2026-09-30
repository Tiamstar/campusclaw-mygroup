const root = document.querySelector('[data-retrieval-root]');
const form = document.querySelector('#retrieval-form');
const queryInput = document.querySelector('#retrieval-query');
const results = document.querySelector('#retrieval-results');
const status = document.querySelector('#retrieval-status');
const errorBox = document.querySelector('#retrieval-error');
const answerCard = document.querySelector('#answer-card');
const answerText = document.querySelector('#answer-text');

function clearOutput() {
  results.replaceChildren();
  status.textContent = '';
  errorBox.hidden = true;
  answerCard.hidden = true;
}

function sourceCard(hit, number) {
  const article = document.createElement('article');
  article.className = 'search-result';
  const kicker = document.createElement('span');
  kicker.className = 'section-kicker';
  kicker.textContent = `SOURCE / ${String(number).padStart(2, '0')} · CHUNK ${hit.chunk_index}`;
  const heading = document.createElement('h3');
  heading.textContent = hit.title;
  const excerpt = document.createElement('p');
  excerpt.textContent = hit.excerpt;
  const meta = document.createElement('small');
  meta.textContent = `字符 ${hit.start_offset}–${hit.end_offset} · ${hit.offset_basis === 'processed_text' ? '预处理文本' : '原始正文'}`;
  const links = document.createElement('div');
  const source = document.createElement('a');
  source.href = hit.material_url;
  source.textContent = '下载原材料 ↗';
  links.append(source);
  article.append(kicker, heading, excerpt, meta, links);
  return article;
}

function showHits(hits, message) {
  status.textContent = hits.length ? `找到 ${hits.length} 个可追溯切片` : message;
  hits.forEach((hit, index) => results.append(sourceCard(hit, index + 1)));
}

async function callApi(url, payload) {
  const response = await fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  if (response.status === 401) {
    window.location.assign(`${root.dataset.loginUrl}?next=${encodeURIComponent(window.location.pathname)}`);
    return null;
  }
  const data = await response.json();
  if (!response.ok) throw new Error(response.status === 503 ? '向量或模型服务暂时不可用，请稍后重试。' : '请求失败，请检查输入后重试。');
  return data;
}

async function execute(kind) {
  clearOutput();
  const query = queryInput.value.trim();
  if (!query) return;
  form.querySelectorAll('button').forEach(button => { button.disabled = true; });
  status.textContent = kind === 'ask' ? '正在检索依据并生成回答…' : '正在检索本班材料…';
  try {
    if (kind === 'ask') {
      const data = await callApi(root.dataset.askUrl, {query});
      if (!data) return;
      answerText.textContent = data.answer;
      answerCard.hidden = false;
      showHits(data.citations, data.answer);
    } else {
      const mode = form.querySelector('input[name="mode"]:checked').value;
      const data = await callApi(root.dataset.searchUrl, {query, mode});
      if (!data) return;
      showHits(data.hits, data.message);
    }
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    status.textContent = '';
  } finally {
    form.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}

form.addEventListener('submit', event => { event.preventDefault(); execute('search'); });
form.querySelector('[data-action="ask"]').addEventListener('click', () => execute('ask'));

const reindexForm = document.querySelector('#reindex-form');
if (reindexForm) reindexForm.addEventListener('submit', async event => {
  event.preventDefault();
  const materialId = document.querySelector('#reindex-material').value;
  const name = document.querySelector('#reindex-strategy').value;
  const strategy = name === 'custom' ? {name, max_length: 800, overlap_ratio: 0.1, delimiter: 'sentence'} : {name};
  const output = document.querySelector('#reindex-status');
  output.textContent = '正在重建…';
  try {
    const response = await fetch(`${reindexForm.dataset.indexPrefix}${materialId}/index`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': reindexForm.dataset.csrf},
      body: JSON.stringify({strategy}),
    });
    if (!response.ok) throw new Error();
    const data = await response.json();
    output.textContent = `完成，共 ${data.chunk_count} 个切片。`;
  } catch {
    output.textContent = '重建失败，旧索引仍保持可用。';
  }
});

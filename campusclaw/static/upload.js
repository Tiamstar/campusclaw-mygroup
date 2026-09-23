const form = document.querySelector('#upload-form');
const fileInput = document.querySelector('#material-file');
const fileLabel = document.querySelector('#file-label');
const fileHint = document.querySelector('#file-hint');
const errorBox = document.querySelector('#upload-error');
const submitButton = document.querySelector('#upload-submit');
const dropzone = document.querySelector('.dropzone');

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  fileLabel.textContent = file ? file.name : '点击选择教学材料';
  fileHint.textContent = file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击重新选择` : '支持 PDF、TXT、Markdown（.md）';
  errorBox.hidden = true;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;
  errorBox.hidden = true;
  if (file.size > 10 * 1024 * 1024) {
    errorBox.textContent = '文件不能超过 10 MB，请选择更小的文件。';
    errorBox.hidden = false;
    return;
  }
  submitButton.disabled = true;
  submitButton.textContent = '正在上传…';
  try {
    const response = await fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin' });
    if (response.ok) {
      window.location.assign(form.dataset.listUrl);
      return;
    }
    if (response.status === 401) {
      window.location.assign(`${form.dataset.loginUrl}?next=${encodeURIComponent(window.location.pathname)}`);
      return;
    }
    const messages = {
      400: '文件无效。请上传非空的 PDF，或 UTF-8 编码的 TXT / MD 文件。',
      403: '你没有向该班级上传材料的权限。',
      413: '文件不能超过 10 MB，请选择更小的文件。',
    };
    errorBox.textContent = messages[response.status] || '上传失败，请稍后重试。';
    errorBox.hidden = false;
  } catch {
    errorBox.textContent = '网络连接失败，请检查连接后重试。';
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = '确认上传 ↗';
  }
});

dropzone.addEventListener('dragover', (event) => {
  event.preventDefault();
  dropzone.classList.add('is-dragging');
});
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('is-dragging'));
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropzone.classList.remove('is-dragging');
  if (event.dataTransfer.files.length) {
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event('change'));
  }
});

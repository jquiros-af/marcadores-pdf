const fileInput = document.getElementById('file');
const dropzone = document.getElementById('dropzone');
const processButton = document.getElementById('process');
const filename = document.getElementById('filename');
const status = document.getElementById('status');
const statusTitle = document.getElementById('status-title');
const statusText = document.getElementById('status-text');
const progressbar = document.getElementById('progressbar');
const result = document.getElementById('result');
const resultText = document.getElementById('result-text');
const download = document.getElementById('download');
const error = document.getElementById('error');
const errorText = document.getElementById('error-text');
let selectedFile = null;

function chooseFile(file){
  if (!file) return;
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    showError('Selecciona un archivo PDF.');
    return;
  }
  selectedFile = file;
  filename.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
  processButton.disabled = false;
  hide(error); hide(result); hide(status);
}

fileInput.addEventListener('change', e => chooseFile(e.target.files[0]));
['dragenter','dragover'].forEach(evt => dropzone.addEventListener(evt, e => {e.preventDefault(); dropzone.classList.add('dragover');}));
['dragleave','drop'].forEach(evt => dropzone.addEventListener(evt, e => {e.preventDefault(); dropzone.classList.remove('dragover');}));
dropzone.addEventListener('drop', e => chooseFile(e.dataTransfer.files[0]));
dropzone.addEventListener('click', e => { if (!e.target.closest('label')) fileInput.click(); });

function hide(el){el.classList.add('hidden')}
function show(el){el.classList.remove('hidden')}
function showError(message){ errorText.textContent = message; show(error); }

processButton.addEventListener('click', async () => {
  if (!selectedFile) return;
  hide(error); hide(result); show(status);
  processButton.disabled = true;
  statusTitle.textContent = 'Procesando…';
  statusText.textContent = 'Analizando las páginas del índice y construyendo el esquema PDF.';
  progressbar.style.width = '18%';

  const data = new FormData();
  data.append('file', selectedFile);
  data.append('hierarchy', document.getElementById('hierarchy').checked ? 'true' : 'false');

  const progressTimer = setInterval(() => {
    const current = parseInt(progressbar.style.width || '18', 10);
    progressbar.style.width = `${Math.min(88, current + Math.floor(Math.random() * 8 + 2))}%`;
  }, 450);

  try {
    const response = await fetch('/api/process', {method:'POST', body:data});
    if (!response.ok) {
      let message = `Error HTTP ${response.status}`;
      try { const json = await response.json(); message = json.detail || message; } catch {}
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const count = response.headers.get('X-Bookmark-Count') || '?';
    const pages = response.headers.get('X-PDF-Pages') || '?';
    const outName = `${selectedFile.name.replace(/\.pdf$/i,'')}_con_bookmarks.pdf`;

    clearInterval(progressTimer);
    progressbar.style.width = '100%';
    statusTitle.textContent = 'Completado';
    statusText.textContent = 'Se ha generado el esquema del índice.';
    show(result);
    resultText.textContent = `${count} bookmarks · ${pages} páginas. El archivo conserva el contenido del libro y añade el esquema navegable.`;
    download.href = url;
    download.download = outName;
    setTimeout(() => hide(status), 500);
  } catch (err) {
    clearInterval(progressTimer);
    hide(status);
    showError(err.message || 'Error desconocido.');
    processButton.disabled = false;
  }
});

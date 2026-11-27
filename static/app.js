const form = document.querySelector('#analyze-form');
const fileInput = document.querySelector('#receipt-file');
const dropzone = document.querySelector('#dropzone');
const filePreview = document.querySelector('#file-preview');
const fileName = document.querySelector('#file-name');
const fileSize = document.querySelector('#file-size');
const errorBox = document.querySelector('#upload-error');
const submitButton = document.querySelector('#submit-button');
const buttonLabel = document.querySelector('.button-label');
const results = document.querySelector('#results');
let selectedFile = null;

function formatBytes(bytes) {
  return bytes < 1024 * 1024 ? (bytes / 1024).toFixed(1) + ' KB' : (bytes / 1024 / 1024).toFixed(2) + ' MB';
}
function formatRupiah(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value);
}
function setFile(file) {
  errorBox.classList.add('hidden');
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return showError('Pilih gambar JPG, PNG, atau WEBP.');
  if (file.size > 10 * 1024 * 1024) return showError('Ukuran file maksimum 10 MB.');
  selectedFile = file;
  fileName.textContent = file.name;
  fileSize.textContent = formatBytes(file.size);
  filePreview.classList.remove('hidden');
  dropzone.classList.add('hidden');
}
function removeFile() {
  selectedFile = null;
  fileInput.value = '';
  filePreview.classList.add('hidden');
  dropzone.classList.remove('hidden');
}
function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, function (character) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character];
  });
}
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
document.querySelector('#remove-file').addEventListener('click', removeFile);
['dragenter', 'dragover'].forEach(name => dropzone.addEventListener(name, event => {
  event.preventDefault();
  dropzone.classList.add('dragover');
}));
['dragleave', 'drop'].forEach(name => dropzone.addEventListener(name, event => {
  event.preventDefault();
  dropzone.classList.remove('dragover');
}));
dropzone.addEventListener('drop', event => setFile(event.dataTransfer.files[0]));

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.classList.add('hidden');
  if (!selectedFile) return showError('Pilih gambar bukti transfer terlebih dahulu.');
  const amountInput = document.querySelector('#expected-amount').value.trim();
  const amountDigits = amountInput.replace(/[^0-9]/g, '');
  const recipient = document.querySelector('#expected-recipient').value.trim();
  const headers = {
    'Content-Type': selectedFile.type,
    'X-File-Name': encodeURIComponent(selectedFile.name)
  };
  if (amountDigits) headers['X-Expected-Amount'] = amountDigits;
  if (recipient) headers['X-Expected-Recipient'] = encodeURIComponent(recipient);

  submitButton.disabled = true;
  buttonLabel.textContent = 'Sedang menganalisis…';
  try {
    const response = await fetch('/api/analyze', { method: 'POST', headers, body: selectedFile });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Pemeriksaan gagal.');
    renderResult(payload);
    results.classList.remove('hidden');
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showError(error.message || 'Terjadi kesalahan saat menganalisis gambar.');
  } finally {
    submitButton.disabled = false;
    buttonLabel.textContent = 'Analisis bukti transfer';
  }
});

function renderResult(data) {
  const overview = document.querySelector('#result-overview');
  const degrees = Math.round(data.risk_score * 3.6);
  overview.innerHTML = '<div class="score-ring" style="--score:' + degrees + 'deg"><div class="score-ring-inner">' + data.risk_score + '</div></div>' +
    '<div class="overview-copy"><span class="status-chip ' + escapeHtml(data.status) + '">' + escapeHtml(data.status_label) + '</span>' +
    '<h3>Skor risiko gambar: ' + data.risk_score + '/100</h3><p>Skor adalah ringkasan sinyal pemeriksaan, bukan probabilitas penipuan.</p></div>';
  document.querySelector('#findings-list').innerHTML = data.findings.map(item =>
    '<div class="finding"><span class="finding-dot ' + escapeHtml(item.severity) + '"></span><div><b>' +
    escapeHtml(item.title) + '</b><p>' + escapeHtml(item.detail) + '</p></div><span class="points">' +
    (item.points ? '+' + item.points + ' poin' : 'Info') + '</span></div>'
  ).join('');
  document.querySelector('#finding-count').textContent = data.findings.length + ' temuan';
  document.querySelector('#ocr-language').textContent = data.ocr.available ? 'OCR ' + data.ocr.language : 'OCR nonaktif';
  document.querySelector('#ocr-content').textContent = data.ocr.text || (data.ocr.available ? 'Belum ada teks yang berhasil dibaca.' : 'OCR tidak aktif. Instal Tesseract untuk menyalakan pembacaan teks.');
  document.querySelector('#detected-amounts').textContent = data.ocr.amounts_idr.length ? data.ocr.amounts_idr.map(formatRupiah).join(' · ') : 'Tidak terbaca';
  const props = [
    ['Nama file', data.image.filename], ['Format aktual', data.image.format],
    ['Dimensi', data.image.width + ' × ' + data.image.height + ' px'], ['Ukuran', formatBytes(data.image.size_bytes)],
    ['Metadata', data.image.metadata.metadata_present ? data.image.metadata.exif_fields_count + ' field EXIF' : 'Tidak ditemukan'],
    ['SHA-256', data.image.sha256.slice(0, 18) + '…']
  ];
  if (data.image.similar_in_session) {
    props.push([
      'Kemiripan dalam sesi',
      'Jarak ' + data.image.similar_in_session.hamming_distance + ' bit · ' +
      data.image.similar_in_session.previous_sha256_prefix + '…'
    ]);
  }
  document.querySelector('#file-properties').innerHTML = props.map(([label, value]) =>
    '<div class="property"><span>' + escapeHtml(label) + '</span><b>' + escapeHtml(String(value)) + '</b></div>'
  ).join('');
  const ela = document.querySelector('#ela-content');
  if (data.ela && data.ela.available) {
    const hotspots = Array.isArray(data.ela.hotspots) ? data.ela.hotspots : [];
    const hotspotMarkup = hotspots.length
      ? '<div class="hotspot-list"><b>Area dengan perbedaan relatif tertinggi</b>' +
        hotspots.map((region, index) =>
          '<div><span>' + (index + 1) + '</span><small>X ' + region.x + ' · Y ' + region.y +
          ' · ' + region.width + ' × ' + region.height + ' px</small><em>mean ' +
          region.mean_difference + '</em></div>'
        ).join('') + '</div>'
      : '<p class="muted-copy">Tidak ditemukan tile dengan perbedaan relatif yang melewati ambang tampilan. Ini bukan bukti bahwa gambar tidak diedit.</p>';
    ela.innerHTML = '<img src="' + data.ela.preview_data_url + '" alt="Peta ELA dengan kotak area perbedaan relatif">' +
      hotspotMarkup +
      '<p class="muted-copy">Rata-rata perbedaan ' + data.ela.mean_difference + '; persentil 95 ' +
      data.ela.p95_difference + '. ' + escapeHtml(data.ela.interpretation) + '</p>';
  } else {
    ela.innerHTML = '<p class="muted-copy">ELA hanya ditampilkan untuk JPEG. Ini bukan berarti file PNG/WEBP aman atau mencurigakan.</p>';
  }
  document.querySelector('#disclaimer-text').textContent = data.disclaimer;
}
document.querySelector('#new-analysis').addEventListener('click', () => {
  results.classList.add('hidden');
  removeFile();
  form.reset();
  document.querySelector('#analyzer').scrollIntoView({ behavior: 'smooth', block: 'start' });
});
document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const refDropzone = document.getElementById('refDropzone');
  const refFileInput = document.getElementById('refFileInput');
  const referencesList = document.getElementById('referencesList');
  const faceStatusBadge = document.getElementById('faceStatusBadge');

  const referenceCard = document.getElementById('referenceCard');
  const configCard = document.getElementById('configCard');

  const scanForm = document.getElementById('scanForm');
  const scanDirInput = document.getElementById('scanDirInput');
  const thresholdInput = document.getElementById('thresholdInput');
  const thresholdVal = document.getElementById('thresholdVal');
  const faceTolInput = document.getElementById('faceTolInput');
  const faceTolVal = document.getElementById('faceTolVal');
  const dryRunToggle = document.getElementById('dryRunToggle');
  const startScanBtn = document.getElementById('startScanBtn');
  const stopScanBtn = document.getElementById('stopScanBtn');

  const progressSection = document.getElementById('progressSection');
  const progressStatus = document.getElementById('progressStatus');
  const progressCount = document.getElementById('progressCount');
  const stageBadge = document.getElementById('stageBadge');
  const progressBarFill = document.getElementById('progressBarFill');

  const summarySection = document.getElementById('summarySection');
  const statTotal = document.getElementById('statTotal');
  const statKept = document.getElementById('statKept');
  const statMe = document.getElementById('statMe');
  const statOthers = document.getElementById('statOthers');
  const statScenery = document.getElementById('statScenery');
  const statReview = document.getElementById('statReview');
  const statSaved = document.getElementById('statSaved');

  const gallerySection = document.getElementById('gallerySection');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  const countMe = document.getElementById('countMe');
  const countOthers = document.getElementById('countOthers');
  const countScenery = document.getElementById('countScenery');
  const countReview = document.getElementById('countReview');
  const countDuplicates = document.getElementById('countDuplicates');
  const countFailed = document.getElementById('countFailed');

  const gridMe = document.getElementById('gridMe');
  const gridOthers = document.getElementById('gridOthers');
  const gridScenery = document.getElementById('gridScenery');
  const gridReview = document.getElementById('gridReview');
  const listDuplicates = document.getElementById('listDuplicates');
  const listFailed = document.getElementById('listFailed');

  const selectAllBtn = document.getElementById('selectAllBtn');
  const clearSelectBtn = document.getElementById('clearSelectBtn');
  const bulkActionBar = document.getElementById('bulkActionBar');
  const bulkSelectedCount = document.getElementById('bulkSelectedCount');
  const toastContainer = document.getElementById('toastContainer');

  const lightboxModal = document.getElementById('lightboxModal');
  const lightboxBody = document.getElementById('lightboxBody');
  const lightboxMeta = document.getElementById('lightboxMeta');
  const lightboxClose = document.getElementById('lightboxClose');

  let pollInterval = null;
  let activeOutputDir = null;
  let selectedFilePaths = new Set();

  thresholdInput.addEventListener('input', (e) => thresholdVal.textContent = e.target.value);
  faceTolInput.addEventListener('input', (e) => faceTolVal.textContent = parseFloat(e.target.value).toFixed(2));

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // --- References Management with Extracted Face Avatar ---
  async function loadReferences() {
    try {
      const res = await fetch('/api/references');
      const data = await res.json();

      if (data.active) {
        faceStatusBadge.textContent = `Face Filter: ACTIVE (${data.references.length} ref)`;
        faceStatusBadge.className = 'status-pill active';
      } else {
        faceStatusBadge.textContent = 'Face Filter: INACTIVE (No references)';
        faceStatusBadge.className = 'status-pill inactive';
      }

      if (data.references.length === 0) {
        referencesList.innerHTML = '<div class="empty-state">No reference photos uploaded yet.</div>';
        return;
      }

      referencesList.innerHTML = data.references.map(ref => `
        <div class="ref-card">
          <button class="delete-btn" onclick="deleteReference('${ref.filename}')">&times;</button>
          <div class="avatar-box ${ref.status !== 'valid' ? 'warning' : ''}" title="Extracted Face Avatar">
            <img src="${ref.status === 'valid' ? ref.crop_url + '?t=' + Date.now() : ref.url}" alt="Extracted Face">
          </div>
          <img src="${ref.url}" alt="${ref.filename}" class="original-thumb">
          <span class="badge-status ${ref.status}">${ref.status === 'valid' ? '✓ 1 Face Extracted' : '⚠️ ' + ref.face_count + ' Faces'}</span>
        </div>
      `).join('');
    } catch (err) {
      console.error('Failed to load references:', err);
    }
  }

  window.deleteReference = async (filename) => {
    if (!confirm(`Remove ${filename} from references?`)) return;
    try {
      await fetch(`/api/references/${filename}`, { method: 'DELETE' });
      showToast(`Deleted reference ${filename}`, 'info');
      await loadReferences();
    } catch (err) {
      showToast('Failed to delete reference.', 'error');
    }
  };

  refDropzone.addEventListener('click', () => refFileInput.click());
  refFileInput.addEventListener('change', (e) => uploadFiles(e.target.files));

  async function uploadFiles(files) {
    for (let file of files) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch('/api/references/upload', {
          method: 'POST',
          body: formData
        });
        if (res.ok) {
          showToast(`Uploaded ${file.name}`, 'info');
        }
      } catch (err) {
        showToast(`Failed to upload ${file.name}`, 'error');
      }
    }
    await loadReferences();
  }

  // --- Scan Execution & Live Stage Monitor ---
  scanForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const scanDir = scanDirInput.value.trim();
    if (!scanDir) return;

    try {
      setFormLocked(true);
      startScanBtn.classList.add('hidden');
      stopScanBtn.classList.remove('hidden');

      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scan_dir: scanDir,
          threshold: parseInt(thresholdInput.value),
          face_tolerance: parseFloat(faceTolInput.value),
          dry_run: dryRunToggle.checked
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to start scan.');

      progressSection.classList.remove('hidden');
      summarySection.classList.add('hidden');
      gallerySection.classList.add('hidden');
      showToast('Scan started...', 'info');

      pollInterval = setInterval(checkProgress, 1000);
    } catch (err) {
      showToast(err.message, 'error');
      setFormLocked(false);
      startScanBtn.classList.remove('hidden');
      stopScanBtn.classList.add('hidden');
    }
  });

  stopScanBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/scan/stop', { method: 'POST' });
      showToast('Stopping scan...', 'info');
    } catch (err) {
      showToast('Failed to send stop signal.', 'error');
    }
  });

  function setFormLocked(locked) {
    if (locked) {
      referenceCard.classList.add('card-disabled');
      configCard.classList.add('card-disabled');
    } else {
      referenceCard.classList.remove('card-disabled');
      configCard.classList.remove('card-disabled');
    }
  }

  async function checkProgress() {
    try {
      const res = await fetch('/api/scan/progress');
      const data = await res.json();

      if (stageBadge && data.stage) {
        stageBadge.textContent = data.stage;
      }
      progressStatus.textContent = data.message;

      let pct = 0;
      if (data.stage && data.stage.includes('Stage 1')) {
        pct = 15;
      } else if (data.stage && data.stage.includes('Stage 2')) {
        pct = data.total > 0 ? 15 + Math.round((data.current / data.total) * 65) : 75;
        progressCount.textContent = `${data.current} / ${data.total} (${pct}%)`;
      } else if (data.stage && data.stage.includes('Stage 3')) {
        pct = 85;
      } else if (data.stage && data.stage.includes('Stage 4')) {
        pct = 95;
      } else if (data.stage === 'Completed') {
        pct = 100;
      }

      progressBarFill.style.width = `${pct}%`;

      if (!data.running) {
        clearInterval(pollInterval);
        setFormLocked(false);
        startScanBtn.classList.remove('hidden');
        stopScanBtn.classList.add('hidden');

        if (data.output_dir) {
          activeOutputDir = data.output_dir;
          loadResults(data.output_dir);
        }
      }
    } catch (err) {
      console.error('Progress check failed:', err);
    }
  }

  // --- Results & Galleries ---
  async function loadResults(outputDir) {
    try {
      const res = await fetch(`/api/results?output_dir=${encodeURIComponent(outputDir)}`);
      const data = await res.json();

      if (data.summary) {
        statTotal.textContent = data.summary.total_scanned;
        statKept.textContent = data.summary.total_kept;
        statMe.textContent = data.summary.keepers_me;
        statOthers.textContent = data.summary.keepers_others;
        statScenery.textContent = data.summary.keepers_scenery;
        statReview.textContent = data.summary.keepers_review || 0;
        statSaved.textContent = `${data.summary.space_saved_mb} MB`;
        summarySection.classList.remove('hidden');
      }

      countMe.textContent = data.keep_me.length;
      countOthers.textContent = data.keep_others.length;
      countScenery.textContent = data.keep_scenery.length;
      countReview.textContent = data.keep_review.length;
      countDuplicates.textContent = data.duplicates.length;
      countFailed.textContent = data.failed.length;

      clearSelection();

      renderMediaGrid(gridMe, data.keep_me);
      renderMediaGrid(gridOthers, data.keep_others);
      renderMediaGrid(gridScenery, data.keep_scenery);
      renderMediaGrid(gridReview, data.keep_review);
      renderDuplicates(listDuplicates, data.duplicates);
      renderFailed(listFailed, data.failed);

      gallerySection.classList.remove('hidden');
    } catch (err) {
      console.error('Failed to load results:', err);
    }
  }

  function renderMediaGrid(container, items) {
    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state">No media found in this category.</div>';
      return;
    }

    container.innerHTML = items.map(item => `
      <div class="media-card ${selectedFilePaths.has(item.path) ? 'selected' : ''}" data-path="${item.path}">
        <input type="checkbox" class="select-checkbox" ${selectedFilePaths.has(item.path) ? 'checked' : ''} onclick="toggleSelectFile(event, '${item.path}')">
        <div class="thumbnail-wrapper" onclick="openLightbox('${item.media_url}', '${item.media_type}', '${item.filename}', '${formatBytes(item.size)}')">
          ${item.media_type === 'video'
            ? `<video src="${item.media_url}#t=0.5" preload="metadata"></video>`
            : `<img src="${item.media_url}" alt="${item.filename}" loading="lazy">`}
        </div>
        <div class="media-info">
          <div class="media-filename">${item.filename}</div>
          <div class="media-size">${formatBytes(item.size)}</div>
        </div>
      </div>
    `).join('');
  }

  function renderDuplicates(container, groups) {
    if (groups.length === 0) {
      container.innerHTML = '<div class="empty-state">No duplicates found. All files are unique!</div>';
      return;
    }

    container.innerHTML = groups.map(g => `
      <div class="dup-group-card">
        <div class="dup-group-title">👯 ${g.group_name}</div>
        <div class="dup-comparison">
          ${g.winner ? `
            <div class="dup-item winner" onclick="openLightbox('${g.winner.media_url}', 'image', '${g.winner.filename}', 'Winner File')">
              <span class="dup-badge">👑 Selected Winner (Kept)</span>
              <div class="thumbnail-wrapper">
                <img src="${g.winner.media_url}" alt="${g.winner.filename}">
              </div>
              <div class="media-info">
                <div class="media-filename">${g.winner.filename}</div>
              </div>
            </div>
          ` : ''}

          ${g.losers.map(l => `
            <div class="dup-item loser" onclick="openLightbox('${l.media_url}', 'image', '${l.filename}', '${formatBytes(l.size)}')">
              <span class="dup-badge">🗑️ Archived Duplicate</span>
              <div class="thumbnail-wrapper">
                <img src="${l.media_url}" alt="${l.filename}">
              </div>
              <div class="media-info">
                <div class="media-filename">${l.filename}</div>
                <div class="media-size">${formatBytes(l.size)}</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
  }

  function renderFailed(container, items) {
    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state">No failed or corrupt files encountered!</div>';
      return;
    }

    container.innerHTML = items.map(item => `
      <div class="dup-group-card">
        <div class="media-filename">⚠️ ${item.filename}</div>
        <div class="media-size">Path: ${item.path} | Size: ${formatBytes(item.size)}</div>
      </div>
    `).join('');
  }

  window.toggleSelectFile = (e, path) => {
    e.stopPropagation();
    if (selectedFilePaths.has(path)) {
      selectedFilePaths.delete(path);
    } else {
      selectedFilePaths.add(path);
    }
    updateSelectionUI();
  };

  function updateSelectionUI() {
    const cards = document.querySelectorAll('.media-card');
    cards.forEach(card => {
      const p = card.dataset.path;
      if (selectedFilePaths.has(p)) {
        card.classList.add('selected');
      } else {
        card.classList.remove('selected');
      }
    });

    if (selectedFilePaths.size > 0) {
      bulkSelectedCount.textContent = selectedFilePaths.size;
      bulkActionBar.classList.remove('hidden');
      clearSelectBtn.classList.remove('hidden');
    } else {
      bulkActionBar.classList.add('hidden');
      clearSelectBtn.classList.add('hidden');
    }
  }

  function clearSelection() {
    selectedFilePaths.clear();
    updateSelectionUI();
  }

  clearSelectBtn.addEventListener('click', clearSelection);

  selectAllBtn.addEventListener('click', () => {
    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab) {
      const cards = activeTab.querySelectorAll('.media-card');
      cards.forEach(card => {
        if (card.dataset.path) selectedFilePaths.add(card.dataset.path);
      });
      updateSelectionUI();
    }
  });

  window.bulkMoveSelected = async (targetCategory) => {
    if (selectedFilePaths.size === 0) return;

    try {
      const res = await fetch('/api/media/move_bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_paths: Array.from(selectedFilePaths),
          target_category: targetCategory,
          output_dir: activeOutputDir
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Bulk move failed');

      showToast(`Moved ${data.moved_count} items to ${targetCategory}`, 'info');
      clearSelection();

      if (activeOutputDir) {
        loadResults(activeOutputDir);
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetTab = document.getElementById(btn.dataset.tab);
      if (targetTab) targetTab.classList.add('active');
    });
  });

  window.openLightbox = (url, type, name, meta) => {
    if (type === 'video') {
      lightboxBody.innerHTML = `<video src="${url}" controls autoplay style="max-width: 100%; max-height: 70vh;"></video>`;
    } else {
      lightboxBody.innerHTML = `<img src="${url}" style="max-width: 100%; max-height: 70vh; object-fit: contain;">`;
    }

    lightboxMeta.innerHTML = `<h3>${name}</h3><p>${meta}</p>`;
    lightboxModal.classList.remove('hidden');
  };

  lightboxClose.addEventListener('click', () => lightboxModal.classList.add('hidden'));
  lightboxModal.addEventListener('click', (e) => {
    if (e.target === lightboxModal) lightboxModal.classList.add('hidden');
  });

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  loadReferences();
});

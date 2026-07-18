document.addEventListener('DOMContentLoaded', () => {
  // UI Elements
  const refDropzone = document.getElementById('refDropzone');
  const refFileInput = document.getElementById('refFileInput');
  const referencesList = document.getElementById('referencesList');
  const faceStatusBadge = document.getElementById('faceStatusBadge');

  const scanForm = document.getElementById('scanForm');
  const scanDirInput = document.getElementById('scanDirInput');
  const thresholdInput = document.getElementById('thresholdInput');
  const thresholdVal = document.getElementById('thresholdVal');
  const dryRunToggle = document.getElementById('dryRunToggle');
  const startScanBtn = document.getElementById('startScanBtn');

  const progressSection = document.getElementById('progressSection');
  const progressStatus = document.getElementById('progressStatus');
  const progressCount = document.getElementById('progressCount');
  const progressBarFill = document.getElementById('progressBarFill');

  const summarySection = document.getElementById('summarySection');
  const statTotal = document.getElementById('statTotal');
  const statKept = document.getElementById('statKept');
  const statMe = document.getElementById('statMe');
  const statOthers = document.getElementById('statOthers');
  const statScenery = document.getElementById('statScenery');
  const statSaved = document.getElementById('statSaved');

  const gallerySection = document.getElementById('gallerySection');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  const countMe = document.getElementById('countMe');
  const countOthers = document.getElementById('countOthers');
  const countScenery = document.getElementById('countScenery');
  const countDuplicates = document.getElementById('countDuplicates');
  const countFailed = document.getElementById('countFailed');

  const gridMe = document.getElementById('gridMe');
  const gridOthers = document.getElementById('gridOthers');
  const gridScenery = document.getElementById('gridScenery');
  const listDuplicates = document.getElementById('listDuplicates');
  const listFailed = document.getElementById('listFailed');

  const lightboxModal = document.getElementById('lightboxModal');
  const lightboxBody = document.getElementById('lightboxBody');
  const lightboxMeta = document.getElementById('lightboxMeta');
  const lightboxClose = document.getElementById('lightboxClose');

  let pollInterval = null;

  // Threshold Slider Value Update
  thresholdInput.addEventListener('input', (e) => {
    thresholdVal.textContent = e.target.value;
  });

  // --- 1. References Management ---
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
          <img src="${ref.url}" alt="${ref.filename}">
          <button class="delete-btn" onclick="deleteReference('${ref.filename}')">&times;</button>
          <span class="badge-status ${ref.status}">${ref.status === 'valid' ? '✓ 1 Face' : '⚠️ ' + ref.face_count + ' Faces'}</span>
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
      loadReferences();
    } catch (err) {
      alert('Failed to delete reference.');
    }
  };

  // Upload Handlers
  refDropzone.addEventListener('click', () => refFileInput.click());
  refFileInput.addEventListener('change', (e) => uploadFiles(e.target.files));

  refDropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    refDropzone.classList.add('hover');
  });

  refDropzone.addEventListener('dragleave', () => refDropzone.classList.remove('hover'));

  refDropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    refDropzone.classList.remove('hover');
    if (e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  });

  async function uploadFiles(files) {
    for (let file of files) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        await fetch('/api/references/upload', {
          method: 'POST',
          body: formData
        });
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }
    loadReferences();
  }

  // --- 2. Scan Submission & Progress ---
  scanForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const scanDir = scanDirInput.value.trim();
    if (!scanDir) return;

    try {
      startScanBtn.disabled = true;
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scan_dir: scanDir,
          threshold: parseInt(thresholdInput.value),
          dry_run: dryRunToggle.checked
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to start scan.');

      progressSection.classList.remove('hidden');
      summarySection.classList.add('hidden');
      gallerySection.classList.add('hidden');

      pollInterval = setInterval(checkProgress, 1000);
    } catch (err) {
      alert(err.message);
      startScanBtn.disabled = false;
    }
  });

  async function checkProgress() {
    try {
      const res = await fetch('/api/scan/progress');
      const data = await res.json();

      progressStatus.textContent = data.message;
      if (data.total > 0) {
        const pct = Math.round((data.current / data.total) * 100);
        progressCount.textContent = `${data.current} / ${data.total} (${pct}%)`;
        progressBarFill.style.width = `${pct}%`;
      } else {
        progressCount.textContent = '';
        progressBarFill.style.width = '100%';
      }

      if (!data.running) {
        clearInterval(pollInterval);
        startScanBtn.disabled = false;
        if (data.output_dir) {
          loadResults(data.output_dir);
        }
      }
    } catch (err) {
      console.error('Progress check failed:', err);
    }
  }

  // --- 3. Results & Galleries ---
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
        statSaved.textContent = `${data.summary.space_saved_mb} MB`;
        summarySection.classList.remove('hidden');
      }

      // Counts
      countMe.textContent = data.keep_me.length;
      countOthers.textContent = data.keep_others.length;
      countScenery.textContent = data.keep_scenery.length;
      countDuplicates.textContent = data.duplicates.length;
      countFailed.textContent = data.failed.length;

      // Render Media Grids
      renderMediaGrid(gridMe, data.keep_me);
      renderMediaGrid(gridOthers, data.keep_others);
      renderMediaGrid(gridScenery, data.keep_scenery);
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
      <div class="media-card" onclick="openLightbox('${item.media_url}', '${item.media_type}', '${item.filename}', '${formatBytes(item.size)}')">
        <div class="thumbnail-wrapper">
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

  // --- 4. Tabs Switching ---
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetTab = document.getElementById(btn.dataset.tab);
      if (targetTab) targetTab.classList.add('active');
    });
  });

  // --- 5. Lightbox Modal ---
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

  // Initial Load
  loadReferences();
});

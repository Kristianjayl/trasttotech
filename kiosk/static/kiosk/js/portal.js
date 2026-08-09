(function(){
  const state = JSON.parse(document.getElementById('state-data').textContent);
  let localRemaining = state.remaining_seconds || 0;
  let paused = state.paused || false;

  function getCookie(name) {
    const match = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return match ? match.pop() : '';
  }

  function csrfFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
    }, opts.headers || {});
    return fetch(url, opts);
  }

  function fmtTime(totalSeconds) {
    totalSeconds = Math.max(0, totalSeconds | 0);
    const h = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
    const s = String(totalSeconds % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function renderTimer() {
    document.getElementById('timerValue').textContent = fmtTime(localRemaining);
    document.getElementById('pausedTag').classList.toggle('show', paused);
    document.getElementById('connLabel').textContent = paused ? 'PAUSED' : 'CONNECTED';
    document.getElementById('btnPause').innerHTML = paused
      ? 'Resume Time <span class="arrow">&#8250;</span>'
      : 'Pause Time <span class="arrow">&#8250;</span>';
  }

  function setPoints(v) {
    document.getElementById('pointsValue').textContent = v;
    const rb = document.getElementById('redeemBalance');
    if (rb) rb.textContent = v;
    document.querySelectorAll('.redeem-btn').forEach(btn => {
      const cost = Number(btn.dataset.points);
      btn.disabled = v < cost;
    });
  }

  setInterval(() => {
    if (!paused && localRemaining > 0) {
      localRemaining -= 1;
      renderTimer();
    }
  }, 1000);

  function syncStatus() {
    fetch('/api/status/').then(r => r.json()).then(s => {
      localRemaining = s.remaining_seconds;
      paused = s.paused;
      setPoints(s.points);
      renderTimer();
    });
  }
  setInterval(syncStatus, 8000);
  renderTimer();
  setPoints(state.points);

  let toastTimer;
  function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast show' + (type ? ' ' + type : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }

  function openTray(id){ document.getElementById(id).classList.add('show'); }
  function closeTray(id){ document.getElementById(id).classList.remove('show'); }
  document.querySelectorAll('[data-close]').forEach(el => {
    el.addEventListener('click', () => closeTray(el.dataset.close));
  });
  document.querySelectorAll('.tray-backdrop').forEach(el => {
    el.addEventListener('click', (e) => { if (e.target === el) closeTray(el.id); });
  });

  document.getElementById('btnRedeem').addEventListener('click', () => openTray('trayRedeem'));
  document.getElementById('btnRates').addEventListener('click', () => openTray('trayRates'));

  // ---- About / Privacy Policy footer links ----
  document.getElementById('btnAbout').addEventListener('click', (e) => { e.preventDefault(); openTray('trayAbout'); });
  document.getElementById('btnPrivacy').addEventListener('click', (e) => { e.preventDefault(); openTray('trayPrivacy'); });

  document.getElementById('btnPause').addEventListener('click', () => {
    csrfFetch('/api/pause/', {method:'POST'}).then(r => r.json()).then(s => {
      paused = s.paused;
      localRemaining = s.remaining_seconds;
      renderTimer();
      showToast(paused ? 'Time paused' : 'Time resumed');
    });
  });

  let pollHandle;
  let scanDurationSeconds = 90;

  function resetWeighUI(){
    clearInterval(pollHandle);
    document.getElementById('weighCountdown').textContent = '90';
    document.getElementById('weighBarFill').style.width = '0%';
    document.getElementById('weighKg').textContent = 'Waiting...';
    document.getElementById('weighActions').style.display = '';
    document.getElementById('weighResult').style.display = 'none';
    document.getElementById('weighResult').innerHTML = '';
  }

  document.getElementById('btnInsert').addEventListener('click', async () => {
    resetWeighUI();
    openTray('trayInsert');

    try {
      const response = await csrfFetch(
        '/api/insert/start/',
        {method:'POST'}
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.message || data.error || 'Unable to start scanner'
        );
      }

      scanDurationSeconds = data.seconds_left || 90;
      document.getElementById('weighCountdown').textContent =
        scanDurationSeconds;
      document.getElementById('weighKg').textContent =
        'Insert one bottle';

      pollHandle = setInterval(pollWeight, 1000);
      pollWeight();
    }
    catch (error) {
      showScanFailure(error.message);
    }
  });

  async function pollWeight(){
    try {
      const response = await fetch(
        '/api/insert/poll/',
        {
          method: 'GET',
          credentials: 'same-origin',
          cache: 'no-store',
        }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Unable to read scanner');
      }

      document.getElementById('weighCountdown').textContent =
        data.seconds_left;

      const progress = Math.min(
        100,
        Math.max(
          0,
          ((scanDurationSeconds - data.seconds_left) /
            scanDurationSeconds) * 100
        )
      );

      document.getElementById('weighBarFill').style.width =
        progress + '%';

      document.getElementById('weighKg').textContent =
        data.done ? 'Result ready' : 'Scanning camera...';

      if (data.done) {
        clearInterval(pollHandle);
        showDepositResult(data);
      }
    }
    catch (error) {
      clearInterval(pollHandle);
      showScanFailure(error.message);
    }
  }

  // NOTE: must match MIN_POINTS_FOR_VOUCHER in views.py (api_voucher_generate).
  // These are two separate constants that happen to share a value -- if you
  // change one, change the other too.
  const VOUCHER_MIN_POINTS = 50;

  function showDepositResult(data){
    if (typeof data.new_balance === 'number') {
      setPoints(data.new_balance);
    }

    document.getElementById('weighActions').style.display = 'none';
    const box = document.getElementById('weighResult');
    box.style.display = 'block';

    const confidence = data.confidence_percent !== null
      ? Number(data.confidence_percent).toFixed(2) + '%'
      : '';

    if (data.status === 'accepted') {
      const canVoucher = data.new_balance >= VOUCHER_MIN_POINTS;
      box.innerHTML = `
        <div class="weigh-hint" style="background:#E7F7EA; color:#1F6B33;">
          <strong>Bottle Accepted</strong><br>
          ${data.label}${confidence ? ` — ${confidence}` : ''}<br>
          +${data.points_awarded} points. Balance: ${data.new_balance} pts.
        </div>

        <div style="display:flex; gap:8px; margin-bottom:6px;">
          <button id="btnGenVoucher" style="flex:1; border:none; border-radius:7px; padding:10px; background:var(--btn-purple); color:#fff; font-weight:700; cursor:pointer;" ${canVoucher ? '' : 'disabled'}>Generate Voucher</button>
        </div>

        ${canVoucher ? '' : `<div style="font-size:11.5px; color:var(--muted); margin-bottom:6px;">Needs ${VOUCHER_MIN_POINTS} points minimum for a voucher.</div>`}
        <button class="cancel-link" data-close="trayInsert">Done</button>`;

      showToast(
        '+' + data.points_awarded + ' points awarded',
        'success'
      );

      const genBtn = document.getElementById('btnGenVoucher');
      if (genBtn) {
        genBtn.addEventListener(
          'click',
          () => generateVoucher(box)
        );
      }
    }
    else if (data.status === 'rejected' && data.is_invalid) {
      box.innerHTML = `
        <div class="weigh-hint" style="background:#FFF3CD; color:#854D0E;">
          <strong>Invalid Object</strong><br>
          ${data.label}${confidence ? ` — ${confidence}` : ''}<br>
          Please insert a valid plastic bottle. No points awarded.
        </div>
        <button class="cancel-link" data-close="trayInsert">Close</button>`;

      showToast('Invalid object', 'error');
    }
    else if (data.status === 'rejected') {
      box.innerHTML = `
        <div class="weigh-hint" style="background:#FBE9E6; color:#9A2E1C;">
          <strong>Bottle Rejected</strong><br>
          ${data.label}${confidence ? ` — ${confidence}` : ''}<br>
          The bottle was not accepted. No points awarded.
        </div>
        <button class="cancel-link" data-close="trayInsert">Close</button>`;

      showToast('Bottle rejected', 'error');
    }
    else {
      box.innerHTML = `
        <div class="weigh-hint" style="background:#FBE9E6; color:#9A2E1C;">
          <strong>Scan Timed Out</strong><br>
          No stable bottle result was received. Please try again.
        </div>
        <button class="cancel-link" data-close="trayInsert">Close</button>`;

      showToast('Scan timed out', 'error');
    }

    box.querySelectorAll('[data-close]').forEach(el => {
      el.addEventListener(
        'click',
        () => closeTray('trayInsert')
      );
    });
  }

  function showScanFailure(message){
    clearInterval(pollHandle);
    document.getElementById('weighActions').style.display = 'none';

    const box = document.getElementById('weighResult');
    box.style.display = 'block';
    box.innerHTML = `
      <div class="weigh-hint" style="background:#FBE9E6; color:#9A2E1C;">
        <strong>Scanner Unavailable</strong><br>
        ${message}
      </div>
      <button class="cancel-link" data-close="trayInsert">Close</button>`;

    box.querySelectorAll('[data-close]').forEach(el => {
      el.addEventListener(
        'click',
        () => closeTray('trayInsert')
      );
    });

    showToast('Unable to start scanner', 'error');
  }

  function generateVoucher(box){
    csrfFetch('/api/voucher/generate/', {method:'POST', body: JSON.stringify({points: VOUCHER_MIN_POINTS})})
      .then(async r => {
        const d = await r.json();
        if (!r.ok) { showToast('Insufficient Balance', 'error'); return; }
        setPoints(d.new_balance);
        showToast('Voucher Successfully Generated', 'success');
        box.innerHTML = `
          <div class="weigh-hint" style="background:#E7F7EA; color:#1F6B33;">
            Voucher code: <b style="font-family:var(--font-mono);">${d.code}</b><br>Enter this code on any Home Vendo unit to use it.
          </div>
          <button class="cancel-link" data-close="trayInsert">Done</button>`;
        box.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => closeTray('trayInsert')));
      });
  }

  document.getElementById('btnCancelInsert').addEventListener('click', () => {
    clearInterval(pollHandle);
    csrfFetch('/api/insert/cancel/', {method:'POST'});
    closeTray('trayInsert');
  });

  document.querySelectorAll('.redeem-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const points = Number(btn.dataset.points);
      csrfFetch('/api/redeem/wifi/', {method:'POST', body: JSON.stringify({points})})
        .then(async r => {
          const d = await r.json();
          if (!r.ok) {
            showToast(d.error === 'insufficient_points' ? 'Insufficient Points' : 'Redeem failed', 'error');
            return;
          }
          setPoints(d.points);
          localRemaining = d.remaining_seconds;
          paused = false;
          renderTimer();
          showToast('Successfully Redeemed', 'success');
          closeTray('trayRedeem');
        });
    });
  });

  document.getElementById('voucherSubmit').addEventListener('click', () => {
    const code = document.getElementById('voucherInput').value.trim();
    if (!code) return;
    csrfFetch('/api/voucher/submit/', {method:'POST', body: JSON.stringify({code})})
      .then(r => r.json()).then(d => {
        if (d.ok) showToast('Voucher Successfully Used', 'success');
        else showToast('Invalid Voucher', 'error');
        document.getElementById('voucherInput').value = '';
      });
  });

  // ---- Temporary bottle-classifier controls ----
  const classifierInput = document.getElementById('classifierImage');
  const classifierButton = document.getElementById('btnRunClassifier');
  const classifierResult = document.getElementById('classifierResult');

  document.getElementById('btnClassify').addEventListener('click', () => {
    classifierInput.value = '';
    classifierResult.textContent = '';
    classifierResult.className = 'classifier-result';
    openTray('trayClassify');
  });

  classifierButton.addEventListener('click', async () => {
    const image = classifierInput.files[0];

    if (!image) {
      showToast('Choose a bottle picture first', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('image', image);

    classifierButton.disabled = true;
    classifierButton.textContent = 'Checking...';
    classifierResult.textContent = 'Analyzing bottle...';
    classifierResult.className = 'classifier-result show';

    try {
      const response = await fetch('/api/classify-bottle/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'Classification failed');
      }

      const decision = result.is_clean
        ? 'Bottle Accepted'
        : 'Bottle Rejected';

      classifierResult.className =
        'classifier-result show ' +
        (result.is_clean ? 'accepted' : 'rejected');

      classifierResult.innerHTML = `
        <strong>${decision}</strong>
        <span>
          ${result.label} — ${result.confidence_percent.toFixed(2)}%
        </span>
      `;

      showToast(
        decision,
        result.is_clean ? 'success' : 'error'
      );
    }
    catch (error) {
      classifierResult.className =
        'classifier-result show rejected';

      classifierResult.innerHTML = `
        <strong>Unable to check image</strong>
        <span>${error.message}</span>
      `;

      showToast('Classification failed', 'error');
    }
    finally {
      classifierButton.disabled = false;
      classifierButton.textContent = 'Check Bottle';
    }
  });

})();

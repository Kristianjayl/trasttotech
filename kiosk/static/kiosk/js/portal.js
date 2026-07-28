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

  document.getElementById('btnPause').addEventListener('click', () => {
    csrfFetch('/api/pause/', {method:'POST'}).then(r => r.json()).then(s => {
      paused = s.paused;
      localRemaining = s.remaining_seconds;
      renderTimer();
      showToast(paused ? 'Time paused' : 'Time resumed');
    });
  });

  let pollHandle;
  function resetWeighUI(){
    document.getElementById('weighCountdown').textContent = '4';
    document.getElementById('weighBarFill').style.width = '0%';
    document.getElementById('weighKg').textContent = '0.00';
    document.getElementById('weighActions').style.display = '';
    document.getElementById('weighResult').style.display = 'none';
    document.getElementById('weighResult').innerHTML = '';
  }

  document.getElementById('btnInsert').addEventListener('click', () => {
    resetWeighUI();
    openTray('trayInsert');
    csrfFetch('/api/insert/start/', {method:'POST'}).then(() => {
      pollHandle = setInterval(pollWeight, 700);
    });
  });

  function pollWeight(){
    fetch('/api/insert/poll/').then(r => r.json()).then(d => {
      document.getElementById('weighCountdown').textContent = d.seconds_left;
      document.getElementById('weighBarFill').style.width = ((4-d.seconds_left)/4*100) + '%';
      document.getElementById('weighKg').textContent = d.done ? '1 pc' : '...';
      if (d.done) {
        clearInterval(pollHandle);
        confirmDeposit();
      }
    });
  }

  const VOUCHER_MIN_POINTS = 50;

  function confirmDeposit(){
    csrfFetch('/api/insert/confirm/', {method:'POST'}).then(r => r.json()).then(d => {
      setPoints(d.new_balance);
      document.getElementById('weighActions').style.display = 'none';
      const box = document.getElementById('weighResult');
      box.style.display = 'block';
      if (d.points_awarded > 0) {
        const canVoucher = d.new_balance >= VOUCHER_MIN_POINTS;
        box.innerHTML = `
          <div class="weigh-hint" style="background:#E7F7EA; color:#1F6B33;">
            +${d.points_awarded} points awarded for 1 bottle. Balance: ${d.new_balance} pts.
          </div>

          <div style="display:flex; gap:8px; margin-bottom:6px;">
            <button id="btnGenVoucher" style="flex:1; border:none; border-radius:7px; padding:10px; background:var(--btn-purple); color:#fff; font-weight:700; cursor:pointer;" ${canVoucher ? '' : 'disabled'}>Generate Voucher</button>
          </div>

          ${canVoucher ? '' : `<div style="font-size:11.5px; color:var(--muted); margin-bottom:6px;">Needs ${VOUCHER_MIN_POINTS} pts (5 bottles) minimum for a voucher.</div>`}
          <button class="cancel-link" data-close="trayInsert">Done</button>`;
        
        showToast('+' + d.points_awarded + ' points awarded', 'success');
        const genBtn = document.getElementById('btnGenVoucher');
        if (genBtn) genBtn.addEventListener('click', () => generateVoucher(box));
      } 
      else {
        box.innerHTML = `
          <div class="weigh-hint" style="background:#FBE9E6; color:#9A2E1C;">
            Not bottle detected. Please try again.
          </div>
          <button class="cancel-link" data-close="trayInsert">Close</button>`;
      }
      box.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => closeTray('trayInsert')));
    });
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
})();
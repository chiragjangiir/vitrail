'use strict';

// Vitrail Player — popup UI (§3.10). Talks to the background SW via chrome.runtime.sendMessage.

const $ = (id) => document.getElementById(id);

function send(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

function setMsg(text, kind) {
  const el = $('msg');
  el.textContent = text || '';
  el.className = 'msg' + (kind ? ' ' + kind : '');
}

async function refresh() {
  const st = await send({ type: 'status' });
  if (!st || !st.ok) { setMsg('Background unavailable', 'err'); return; }
  $('sec-status').classList.toggle('show', st.configured);
  $('sec-setup').classList.toggle('show', !st.configured);
  if (st.configured) {
    $('run-dot').className = 'dot ' + (st.running ? 'on' : 'off');
    $('run-text').textContent = st.running ? 'Player running' : 'Stopped';
    $('cfg-line').textContent =
      `${st.player_name || '(unnamed)'} · ${st.backend_url}` + (st.is_jwt ? '' : ' · pending registration');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('btn-register').addEventListener('click', async () => {
    const backend_url = $('in-backend').value.trim();
    const token = $('in-token').value.trim();
    const name = $('in-name').value.trim();
    if (!backend_url || !token) { setMsg('Backend URL and token are required', 'err'); return; }
    setMsg('Registering…');
    $('btn-register').disabled = true;
    const r = await send({ type: 'register', backend_url, token, name });
    $('btn-register').disabled = false;
    if (r && r.ok) { setMsg('Registered — player launched', 'ok'); refresh(); }
    else setMsg((r && r.error) || 'Registration failed', 'err');
  });

  $('btn-launch').addEventListener('click', async () => {
    const r = await send({ type: 'launch' });
    if (r && r.ok) { setMsg('Player launched', 'ok'); refresh(); }
    else setMsg((r && r.error) || 'Launch failed', 'err');
  });

  $('btn-stop').addEventListener('click', async () => {
    await send({ type: 'stop' });
    setMsg('Stopped', 'ok'); refresh();
  });

  $('btn-reset').addEventListener('click', async () => {
    await send({ type: 'reset' });
    setMsg('Reset — re-register below', 'ok'); refresh();
  });

  refresh();
});

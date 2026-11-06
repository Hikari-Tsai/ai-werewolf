/* 前端：一個 WebSocket、兩個畫面。所有玩家對前端都長一樣，沒有欄位能看出誰是 AI。 */
(() => {
  const $ = (id) => document.getElementById(id);
  let ws, state = null, pid = localStorage.getItem('tw_pid') || '', code = '';
  let typingTimer = null, isTyping = false, countdownTimer = null, myVote;   // myVote：undefined 還沒投、null 棄票、字串化名
  const bubbles = {}, spectateNotes = [];

  // ---------- 連線 ----------
  function connect(onOpen) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = onOpen;
    ws.onmessage = (e) => handle(JSON.parse(e.data));
    ws.onclose = () => { toast('連線中斷，3 秒後重連'); setTimeout(() => connect(() => { if (code) send({ type: 'join', code, pid }); }), 3000); };
  }
  const send = (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m));

  // ---------- 進房 ----------
  const params = new URLSearchParams(location.search);
  const invitedRoom = (params.get('room') || '').toUpperCase();
  if (invitedRoom) {
    // 從邀請連結進來：只能加入這間房，不給開新房
    $('code').value = invitedRoom;
    $('entry-create').classList.add('hidden');
    $('entry-title').textContent = `加入房間 ${invitedRoom}`;
    $('entry-sub').textContent = '取個暱稱就能進房。遊戲中大家看到的是隨機代號，暱稱要到你出局或遊戲結束才會公開。';
    $('entry-join').querySelector('h2').classList.add('hidden');
    $('entry-join-hint').textContent = '房號已經幫你填好了，房間有設密碼的話填一下，再按加入。';
  }
  $('nickname').value = localStorage.getItem('tw_nick') || '';
  // 房號欄先填一組隨機四碼大寫英文（避開像 0 和 1 的 O、I），想改就直接改
  function randomCode() {
    const letters = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
    return Array.from({ length: 4 }, () => letters[Math.floor(Math.random() * letters.length)]).join('');
  }
  $('new-code').value = randomCode();

  $('btn-create').onclick = () => enter({ type: 'create', nickname: nick(), code: $('new-code').value.trim().toUpperCase() });
  $('btn-join').onclick = () => enter({ type: 'join', code: $('code').value.trim().toUpperCase(), nickname: nick(), password: $('password').value, pid });
  function nick() { const n = $('nickname').value.trim() || '玩家'; localStorage.setItem('tw_nick', n); return n; }
  function enter(msg) {
    $('entry-error').textContent = '';
    if (ws && ws.readyState === 1) send(msg); else connect(() => send(msg));
  }

  // ---------- 收訊 ----------
  function handle(m) {
    switch (m.type) {
      case 'joined':
        pid = m.pid; localStorage.setItem('tw_pid', pid); setCode(m.code);
        $('screen-entry').classList.add('hidden'); $('screen-room').classList.remove('hidden');
        break;
      case 'room_state': state = m; if (m.code !== code) setCode(m.code); render(); break;
      case 'notice': showNotice(m.text); break;
      case 'history': $('chat').innerHTML = ''; m.chat.forEach(addChat); $('chat').scrollTop = $('chat').scrollHeight; break;
      case 'chat': addChat(m); showBubble(m.alias, m.text); break;
      case 'typing': setTyping(m.alias, m.on); break;
      case 'vote_progress': $('vote-progress').textContent = `${m.voted}/${m.total} 已投`; break;
      case 'spectate_init': showSpectate(m.players); break;
      case 'spectate': spectateNotes.push(m); renderNotes(); break;
      case 'game_over': showGameOver(m); break;
      case 'room_closed': toast(m.text); state = null; code = ''; setTimeout(() => { location.href = '/'; }, 1800); break;
      case 'error':
        if (!state) {
          $('entry-error').textContent = m.text;
          // 預填的房號撞到別人的房：換一組新的
          if (/已經有人用了/.test(m.text) && $('new-code').value) $('new-code').value = randomCode();
          // 邀請的房間已經不在了，放開讓他回首頁開新房
          if (invitedRoom && /找不到/.test(m.text)) $('entry-error').innerHTML += ' <a href="/">回首頁</a>';
        } else toast(m.text);
        break;
    }
  }

  // 房號可能被房主改掉：網址、標題、邀請卡一起換
  function setCode(c) {
    code = c; history.replaceState(null, '', `?room=${code}`);
    $('room-code').textContent = code;
    if (document.activeElement !== $('invite-code')) $('invite-code').value = code;
  }
  // 房主在大廳點房號就能改；Enter 或離開欄位才送出
  $('invite-code').addEventListener('change', () => {
    const c = $('invite-code').value.trim().toUpperCase();
    if (c && c !== code) send({ type: 'rename', code: c }); else $('invite-code').value = code;
  });
  $('invite-code').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('invite-code').blur(); });

  // 房主結束遊戲／解散房間：先彈視窗確認
  function askConfirm(text, yes) {
    return new Promise((resolve) => {
      $('confirm-text').textContent = text; $('confirm-yes').textContent = yes;
      $('confirm').classList.remove('hidden');
      const done = (ok) => { $('confirm').classList.add('hidden'); resolve(ok); };
      $('confirm-yes').onclick = () => done(true);
      $('confirm-no').onclick = () => done(false);
      $('confirm').onclick = (e) => { if (e.target === $('confirm')) done(false); };
    });
  }
  $('btn-end').onclick = async () => {
    if (!state) return;
    const lobby = state.phase === 'lobby';
    const ok = await askConfirm(lobby ? '確定要解散房間嗎？所有人都會回到首頁。' : '確定要結束遊戲嗎？這局會直接結束並揭曉所有人的身分，不算勝負。', lobby ? '解散' : '結束遊戲');
    if (ok) send({ type: 'end' });
  };

  // 最後 30 秒的提醒：聊天室一行、上面一條橫幅，到投票就收掉
  function showNotice(text) {
    sysMsg(text); toast(text);
    $('notice').textContent = text; $('notice').classList.remove('hidden');
  }

  // ---------- 畫面 ----------
  function render() {
    const s = state, me = s.you;
    const names = { lobby: '等待中', discuss: '討論', vote: '投票', result: '開票', night: '夜晚', dawn: '天亮', over: '結束' };
    $('phase-name').textContent = names[s.phase] + (s.round ? `｜第 ${s.round} 輪` : '');
    const aiSlots = s.phase === 'lobby' ? (s.cfg?.ai_count || 0) : 0;
    $('round-label').textContent = s.phase === 'lobby' ? `${s.players.length} 人入座${aiSlots ? `，${aiSlots} 個 AI 待命` : ''}` : `第 ${s.round} 輪`;
    // 有通道就用公開網址，否則用現在這個（區網）網址；大廳時顯示連結和 QR code
    const invite = s.public_url ? `${s.public_url}/?room=${s.code}` : `${location.origin}/?room=${s.code}`;
    $('invite').classList.toggle('hidden', s.phase !== 'lobby');
    $('invite-code').readOnly = !s.is_host;
    $('invite-edit-hint').classList.toggle('hidden', !s.is_host);
    const qrSrc = `/api/qr?text=${encodeURIComponent(invite)}`;
    if ($('invite-qr').getAttribute('src') !== qrSrc) $('invite-qr').src = qrSrc;
    $('btn-copy').onclick = () => { navigator.clipboard?.writeText(invite); toast('已複製邀請連結'); };
    $('topic').classList.toggle('hidden', !s.topic || s.phase === 'lobby');
    $('topic').textContent = s.topic ? `本輪話題：${s.topic}` : '';
    // 遺言時間：橫幅提醒大家聽他講完；輪到自己就開聊天欄
    const lastWordsMe = s.phase === 'result' && s.last_words && s.last_words === s.you;
    if (s.phase === 'result' && s.last_words) {
      $('notice').textContent = lastWordsMe ? '你被放逐了，留幾句遺言吧' : `${s.last_words} 的遺言時間`;
      $('notice').classList.remove('hidden');
    } else if (s.phase !== 'discuss') $('notice').classList.add('hidden');
    $('chat-input').placeholder = lastWordsMe ? '遺言：最後一句話…' : '說點什麼…';
    $('btn-end').classList.toggle('hidden', !(s.is_host && s.phase !== 'over'));
    $('btn-end').textContent = s.phase === 'lobby' ? '解散房間' : '結束遊戲';
    $('host-panel').classList.toggle('hidden', !(s.is_host && s.phase === 'lobby'));
    $('wait-hint').classList.toggle('hidden', !(!s.is_host && s.phase === 'lobby'));
    if (s.is_host && s.phase === 'lobby') fillCfg(s.cfg);
    // 房主在遊戲進行中看得到即時費用；大廳還沒花錢就不顯示
    $('cost-live').textContent = (s.cost_usd != null && s.phase !== 'lobby') ? ` ｜ $${s.cost_usd.toFixed(3)}` : '';
    $('chat-form').classList.toggle('hidden', !((s.phase === 'discuss' && s.alive) || lastWordsMe));
    $('vote-bar').classList.toggle('hidden', !(s.phase === 'vote' && s.alive));
    if (s.phase === 'vote') {
      // 重新整理或重連回來：用伺服器記的票還原；開票前都還能改
      if (myVote === undefined && s.voted) myVote = s.vote || null;
      if (myVote === undefined) { $('vote-progress').textContent = ''; $('vote-reason').value = ''; $('vote-hint').textContent = '點上面的頭像投票，開票前都還能改，或'; }
    } else myVote = undefined;
    $('result').classList.toggle('hidden', !(s.phase === 'result' && s.last_result));
    if (s.phase === 'result' && s.last_result) showResult(s.last_result);
    if (s.phase === 'discuss') $('result').classList.add('hidden');
    if (s.phase === 'night') showNight(s);
    if (s.phase === 'dawn' && s.last_night) showDawn(s.last_night);
    startCountdown(s.ends_at, s.server_time);
    renderSeats();
    if (s.phase !== 'discuss' && s.phase !== 'result') $('typing-bar').textContent = '';
  }

  function fillCfg(c) {
    for (const k of ['ai_count', 'discuss_seconds', 'vote_seconds', 'max_rounds', 'model_strategy', 'password']) {
      const el = $('cfg-' + k); if (document.activeElement !== el) el.value = c[k];
    }
    for (const k of ['topics_on', 'ai_know_each_other', 'night_kill', 'reveal_on_exit']) $('cfg-' + k).checked = !!c[k];
  }
  function readCfg() {
    const c = {};
    for (const k of ['ai_count', 'discuss_seconds', 'vote_seconds', 'max_rounds']) c[k] = parseInt($('cfg-' + k).value || 0, 10);
    c.model_strategy = $('cfg-model_strategy').value; c.password = $('cfg-password').value;
    for (const k of ['topics_on', 'ai_know_each_other', 'night_kill', 'reveal_on_exit']) c[k] = $('cfg-' + k).checked;
    return c;
  }
  $('host-panel').addEventListener('change', () => send({ type: 'host_config', cfg: readCfg() }));
  // 手機沒有 hover：點 ? 切換說明，點別處關掉；也擋住 label 的預設點擊
  document.querySelectorAll('.help').forEach(h => h.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); const on = h.classList.contains('open'); document.querySelectorAll('.help.open').forEach(x => x.classList.remove('open')); if (!on) h.classList.add('open'); }));
  document.addEventListener('click', () => document.querySelectorAll('.help.open').forEach(x => x.classList.remove('open')));
  $('btn-start').onclick = () => { send({ type: 'host_config', cfg: readCfg() }); send({ type: 'start' }); };

  function renderSeats() {
    const box = $('seats'), ps = state.players;
    // 大廳先把設定的 AI 數量畫成機器人占位，房主改數量就同步增減；開局後 AI 真的加進來、座位洗牌，占位就消失
    const aiSlots = state.phase === 'lobby' ? (state.cfg?.ai_count || 0) : 0;
    const n = ps.length + aiSlots;
    const W = box.clientWidth || 600, H = box.clientHeight || 400;
    const keep = new Set();
    const place = (el, i) => {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      el.style.left = (W / 2 + Math.cos(a) * W * 0.42) + 'px';
      el.style.top = (H / 2 + Math.sin(a) * H * 0.40 + 10) + 'px';
    };
    for (let j = 0; j < aiSlots; j++) {
      const key = `ai#${j}`; keep.add(key);
      let el = box.querySelector(`[data-alias="${key}"]`);
      if (!el) {
        el = document.createElement('div'); el.className = 'seat anon ai-slot'; el.dataset.alias = key;
        el.style.setProperty('--d', `${(j * 0.4).toFixed(1)}s`);
        el.innerHTML = `<div class="face">${robotSVG()}</div><div class="name">AI</div>`;
        box.appendChild(el);
      }
      place(el, ps.length + j);
    }
    ps.forEach((p, i) => {
      // 大廳階段伺服器不給名字和頭像，座位用序號當 key；開局後換成化名，整桌一起揭曉
      const anon = !p.alias, key = anon ? `#${i}` : p.alias, isMe = anon ? !!p.me : p.alias === state.you;
      keep.add(key);
      let el = box.querySelector(`[data-alias="${key}"]`);
      if (!el) {
        el = document.createElement('div'); el.className = 'seat' + (anon ? ' anon' : ''); el.dataset.alias = key;
        el.innerHTML = `<div class="typing-dots">•••</div><div class="bubble"></div><div class="face">${anon ? '?' : avatarSVG(p.avatar)}</div><div class="name"></div><div class="tag"></div>`;
        el.onclick = () => { if (el.classList.contains('votable')) { send({ type: 'vote', target: p.alias, reason: reason() }); markVoted(p.alias); } };
        box.appendChild(el);
      }
      place(el, i);
      el.querySelector('.name').textContent = anon ? (isMe ? '你' : '？') : p.alias + (isMe ? '（你）' : '');
      el.classList.toggle('me', isMe);
      el.classList.toggle('dead', !p.alive);
      el.classList.toggle('night-taken', p.died === 'taken');
      el.classList.toggle('offline', !p.connected && p.alive);
      el.classList.toggle('typing', !!p.typing && (state.phase === 'discuss' || state.phase === 'result'));
      el.classList.toggle('votable', state.phase === 'vote' && state.alive && p.alive && !isMe);
      el.classList.toggle('voted', state.phase === 'vote' && p.alias === myVote);
    });
    box.querySelectorAll('.seat').forEach(el => { if (!keep.has(el.dataset.alias)) el.remove(); });
  }
  window.addEventListener('resize', () => state && renderSeats());

  function markVoted(alias) {
    myVote = alias;
    document.querySelectorAll('.seat').forEach(el => el.classList.toggle('voted', el.dataset.alias === alias));
    $('vote-hint').textContent = (alias ? `你投了 ${alias}` : '你棄票了') + '，開票前都還能改，或';
  }
  const reason = () => $('vote-reason').value.trim();
  $('btn-abstain').onclick = () => { send({ type: 'vote', target: null, reason: reason() }); markVoted(null); };
  $('reason-form').onsubmit = (e) => { e.preventDefault(); if (reason()) { send({ type: 'vote_reason', reason: reason() }); toast('記下了，謝謝'); } };

  function setTyping(alias, on) {
    const el = document.querySelector(`.seat[data-alias="${alias}"]`); if (el) el.classList.toggle('typing', on);
    const list = [...document.querySelectorAll('.seat.typing')].map(e => e.dataset.alias).filter(a => a !== state?.you);
    $('typing-bar').textContent = list.length ? `${list.join('、')} 正在輸入…` : '';
  }
  function showBubble(alias, text) {
    const el = document.querySelector(`.seat[data-alias="${alias}"] .bubble`); if (!el) return;
    el.textContent = text; el.classList.add('show');
    clearTimeout(bubbles[alias]); bubbles[alias] = setTimeout(() => el.classList.remove('show'), 5000);
  }
  function addChat(m) {
    const d = document.createElement('div');
    d.className = 'msg' + (m.alias === state?.you ? ' me' : '') + (m.last_words ? ' lastwords' : '');
    d.innerHTML = `<span class="who"></span>${m.last_words ? '<span class="lw">遺言</span>' : ''}<span class="text"></span>`;
    d.querySelector('.who').textContent = m.alias; d.querySelector('.text').textContent = m.text;
    appendChat(d);
  }
  function sysMsg(t) { const d = document.createElement('div'); d.className = 'msg sys'; d.textContent = t; appendChat(d); }
  // 新訊息平滑滑到底；如果使用者正在往上翻舊訊息就不打擾
  function appendChat(el) {
    const c = $('chat');
    const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 120;
    c.appendChild(el);
    if (nearBottom) c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' });
  }

  // 打字：先送 typing on，停 2 秒或送出就 off
  $('chat-input').addEventListener('input', () => {
    if (!isTyping) { isTyping = true; send({ type: 'typing', on: true }); }
    clearTimeout(typingTimer); typingTimer = setTimeout(() => { isTyping = false; send({ type: 'typing', on: false }); }, 2000);
  });
  $('chat-form').onsubmit = (e) => {
    e.preventDefault(); const t = $('chat-input').value.trim(); if (!t) return;
    send({ type: 'chat', text: t }); $('chat-input').value = '';
    clearTimeout(typingTimer); isTyping = false; send({ type: 'typing', on: false });
  };

  function startCountdown(endsAt, serverTime) {
    clearInterval(countdownTimer);
    const offset = Date.now() / 1000 - serverTime;
    const tick = () => { const left = Math.max(0, Math.round(endsAt - (Date.now() / 1000 - offset))); $('countdown').textContent = state.phase === 'lobby' || state.phase === 'over' ? '' : left + 's'; };
    tick(); countdownTimer = setInterval(tick, 500);
  }

  let shownResultRound = 0;
  function showResult(r) {
    const first = shownResultRound !== r.round; shownResultRound = r.round;
    let h = `<div>第 ${r.round} 輪開票</div>`;
    const revealed = r.revealed !== false;
    if (r.eliminated && revealed) {
      const who = r.was_ai ? (r.model ? `AI（${esc(r.model)}）` : 'AI') : `真人${r.nickname ? '：' + esc(r.nickname) : ''}`;
      h += `<div class="big">${esc(r.eliminated)} 被放逐，是 <span class="${r.was_ai ? 'ai' : 'human'}">${who}</span></div>`;
    } else if (r.eliminated) h += `<div class="big">${esc(r.eliminated)} 被放逐</div><div class="muted">身分到結局才揭曉</div>`;
    else h += `<div class="big">${r.tie ? '平票，沒有人被放逐' : '沒有人投票'}</div>`;
    const rows = Object.entries(r.votes).map(([a, t]) => `<tr><td>${esc(a)}</td><td>→ ${t ? esc(t) : '棄票'}</td></tr>`).join('');
    h += `<table>${rows}</table>`;
    $('result').innerHTML = h;
    document.querySelectorAll('.seat').forEach(el => el.classList.remove('voted'));
    if (r.eliminated && revealed) tagSeat({ alias: r.eliminated, is_ai: r.was_ai, nickname: r.nickname });
    if (!first) return;   // 同一輪再收到 room_state（有人斷線之類）不要重播
    const ident = revealed ? `（${r.was_ai ? 'AI' : '真人' + (r.nickname ? ' ' + r.nickname : '')}）` : '';
    sysMsg(r.eliminated ? `${r.eliminated} 被放逐${ident}` : '本輪平票');
    if (r.eliminated) {
      const p = state.players.find(x => x.alias === r.eliminated);
      const who = !revealed ? '身分到結局才揭曉' : r.was_ai ? (r.model ? `是 AI（${esc(r.model)}）` : '是 AI') : `是真人${r.nickname ? '：' + esc(r.nickname) : ''}`;
      showOverlay('exile', `<div class="face">${p ? avatarSVG(p.avatar) : ''}</div><div class="title">${esc(r.eliminated)} 被放逐</div>` +
        `<div class="sub ${!revealed ? '' : r.was_ai ? 'ai' : 'human'}">${who}</div>`, 5000, () => exileSeat(r.eliminated));
    } else if (r.tie) showOverlay('tie', `<div class="title">平票</div><div class="sub reveal">這輪沒有人被放逐</div>`, 3000);
  }
  // 夜晚：整段蓋著深藍字卡，直到天亮；天亮：公布誰被帶走，關掉後座位暗掉
  let shownNightRound = 0, shownDawnRound = 0;
  function showNight(s) {
    if (shownNightRound === s.round) return; shownNightRound = s.round;
    const ms = Math.max(1000, (s.ends_at - s.server_time) * 1000);
    showOverlay('night', `<div class="moon">🌙</div><div class="title">夜深了</div><div class="sub reveal">AI 正在挑要帶走誰<span class="dots"></span></div>`, ms);
  }
  function showDawn(n) {
    if (shownDawnRound === n.round) return; shownDawnRound = n.round;
    const p = state.players.find(x => x.alias === n.victim);
    sysMsg(`天亮了，${n.victim} 昨晚被 AI 帶走了${n.nickname ? '（真人 ' + n.nickname + '）' : ''}`);
    showOverlay('dawn', `<div class="face">${p ? avatarSVG(p.avatar) : ''}</div><div class="title">天亮了</div>` +
      `<div class="sub">${esc(n.victim)} 昨晚被 AI 帶走了${n.nickname ? '<br><span class="human">真人：' + esc(n.nickname) + '</span>' : ''}</div>`, 6000, () => takenSeat(n.victim));
    if (n.nickname) tagSeat({ alias: n.victim, is_ai: false, nickname: n.nickname });
  }
  function takenSeat(alias) {
    const el = document.querySelector(`.seat[data-alias="${alias}"]`); if (el) el.classList.add('taken');
  }
  // 蓋板字卡：砸進來、副標題一秒後翻出來、幾秒後淡出；點一下提早關。onClose 在關掉後呼叫
  let overlayTimer = null, overlayOnClose = null, overlaySeq = 0;
  function showOverlay(cls, html, ms, onClose) {
    clearTimeout(overlayTimer); overlaySeq++;
    // 上一張還沒關完就被新的蓋掉（夜晚接天亮）：先把它的收尾做掉，免得等一下的關閉把新卡也關了
    const prev = overlayOnClose; overlayOnClose = onClose || null; if (prev) prev();
    const ov = $('overlay'), card = $('overlay-card');
    ov.className = cls; card.className = cls; card.innerHTML = html + '<div class="hint">點一下跳過</div>';
    const sub = card.querySelector('.sub:not(.reveal)');
    if (sub) setTimeout(() => sub.classList.add('reveal'), 1100);
    overlayTimer = setTimeout(hideOverlay, ms);
  }
  function hideOverlay() {
    const ov = $('overlay'); if (ov.classList.contains('hidden') || ov.classList.contains('closing')) return;
    clearTimeout(overlayTimer); ov.classList.add('closing'); const seq = overlaySeq;
    setTimeout(() => { if (seq !== overlaySeq) return; ov.className = 'hidden'; const f = overlayOnClose; overlayOnClose = null; if (f) f(); }, 500);
  }
  $('overlay').onclick = hideOverlay;
  // 放逐動畫：座位抖一下、放大、往上飄走，再以灰掉的樣子回到位子上
  function exileSeat(alias) {
    const el = document.querySelector(`.seat[data-alias="${alias}"]`); if (!el) return;
    el.classList.add('exiled');   // 不拿掉：拿掉會讓入座動畫重播一次
  }
  function showGameOver(m) {
    const aiLeft = m.players.some(p => p.is_ai && p.alive);
    const title = m.aborted ? '遊戲結束' : m.winner === 'ai' ? 'AI 獲勝' : '真人獲勝';
    const why = m.aborted ? '房主提早結束了這局' : m.winner === 'ai' ? 'AI 的數量追平真人了' : aiLeft ? '撐到最後一輪，AI 沒能追平' : 'AI 全部被揪出來了';
    const side = m.aborted ? 'none' : m.winner === 'ai' ? 'ai' : 'humans';
    showOverlay(`win win-${side}`, `<div class="title">${title}</div><div class="sub ${side === 'ai' ? 'ai' : side === 'humans' ? 'human' : ''}">${why}</div>`, 6000);
    const nick = (a) => { const p = m.players.find(x => x.alias === a); return p && !p.is_ai && p.nickname ? `${a}（${p.nickname}）` : a; };
    const awards = (m.awards || []).map(a => `<div class="award"><span class="award-title">${esc(a.title)}</span>${a.aliases.map(x => esc(nick(x))).join('、')}<span class="award-detail">${esc(a.detail)}</span></div>`).join('');
    const h = `<div class="big ${side === 'ai' ? 'ai' : side === 'humans' ? 'human' : ''}">${title}</div>` +
      (awards ? `<div id="awards">${awards}</div>` : '') +
      `<table>${m.players.map(p => `<tr><td>${esc(p.alias)}</td><td class="${p.is_ai ? 'ai' : 'human'}">${p.is_ai ? 'AI ' + esc(p.model) : '真人 ' + esc(p.nickname)}</td><td>${p.alive ? '' : '出局'}</td></tr>`).join('')}</table>` +
      (m.cost_usd != null ? `<div class="muted">本局 API 費用約 $${m.cost_usd}</div>` : '') +
      `<div class="row" style="justify-content:center"><button onclick="location.href='/'">回大廳</button></div>` +
      uploadBox(m);
    $('result').innerHTML = h; $('result').classList.remove('hidden');
    $('chat-form').classList.add('hidden'); $('vote-bar').classList.add('hidden'); $('notice').classList.add('hidden');
    m.players.forEach(p => tagSeat(p));
    wireUpload(m);
  }

  // ---------- 對局紀錄：下載／上傳到 GitHub Issue ----------
  function uploadBox(m) {
    if (!m.log_id) return '';
    return `<div id="upload-box">
      <div>想幫 AI 變得更像人？可以把這局的聊天紀錄分享出來，用來改進 AI 的人設。紀錄裡沒有暱稱和 API key，但有大家的聊天內容，<b>請先確認同房的人都同意公開</b>。</div>
      <div class="row">
        <button id="btn-download" class="small">下載紀錄</button>
        <button id="btn-upload" class="small primary">上傳到 GitHub</button>
      </div>
      <div class="muted">按鈕打不開的話，自己開這個網址貼上：<a id="issue-link" href="${issueUrl(m)}" target="_blank" rel="noopener">${esc(issueUrl(m))}</a></div></div>`;
  }
  function issueUrl(m) {
    return `https://github.com/${m.github_repo}/issues/new?template=upload-log.yml&title=${encodeURIComponent('[log] ' + m.log_id)}`;
  }
  function wireUpload(m) {
    const dl = $('btn-download'); if (!dl) return;
    dl.onclick = () => { location.href = `/api/log/${m.log_id}`; };
    const up = $('btn-upload'); if (!up) return;
    up.onclick = async () => {
      const r = await fetch(`/api/log/${m.log_id}`); if (!r.ok) return toast('還拿不到紀錄');
      const text = await r.text();
      const base = issueUrl(m);
      // Issue Form 可以用網址預填，但網址有長度上限；太長就改成複製到剪貼簿再貼
      const url = base + '&log=' + encodeURIComponent(text);
      if (url.length < 7500) { window.open(url, '_blank'); return; }
      try { await navigator.clipboard.writeText(text); toast('紀錄已複製，貼到表單的「對局紀錄」欄位就好'); }
      catch { toast('請先按「下載紀錄」，再把檔案內容貼到表單'); }
      window.open(base, '_blank');
    };
  }
  function tagSeat(p) {
    const el = document.querySelector(`.seat[data-alias="${p.alias}"] .tag`); if (!el) return;
    el.textContent = p.is_ai ? 'AI' : '真人' + (p.nickname ? ' ' + p.nickname : ''); el.className = 'tag ' + (p.is_ai ? 'ai' : 'human');
  }
  function showSpectate(players) {
    $('spectate').classList.remove('hidden');
    $('spectate-list').innerHTML = players.map(p => `<span class="${p.is_ai ? 'ai' : ''}">${esc(p.alias)}：${p.is_ai ? 'AI（' + esc(p.model) + '）' : '真人 ' + esc(p.nickname)}</span>`).join('');
    players.forEach(tagSeat); renderNotes();
  }
  function renderNotes() {
    if ($('spectate').classList.contains('hidden')) return;
    $('spectate-notes').innerHTML = spectateNotes.slice(-40).map(n => `<div><b>${esc(n.alias)}</b>：${esc(n.note)}</div>`).join('');
  }

  // ---------- 頭像：用種子畫簡單 2D 臉 ----------
  function avatarSVG(seed) {
    const skins = ['#f6d6b8', '#e8b88f', '#d79a6a', '#b97a52', '#f2c9a9', '#c98a63'];
    const hairs = ['#2b1d12', '#5a3a1f', '#111', '#8a5a2b', '#d9b36a', '#3a3a3a', '#c0392b', '#2c3e50', '#6c3483', '#1abc9c', '#e67e22', '#7f8c8d'];
    const bgs = ['#3b5998', '#2a9d8f', '#e76f51', '#8e44ad', '#f4a261', '#264653', '#e9c46a', '#06d6a0', '#ef476f', '#118ab2', '#ffd166', '#8d99ae'];
    const r = (n) => (seed * 9301 + 49297 + n * 233) % 233280 / 233280;
    const skin = skins[Math.floor(r(1) * skins.length)], hair = hairs[seed % hairs.length], bg = bgs[seed % bgs.length];
    const style = seed % 4;
    const hairPath = ['<path d="M16 30 Q32 8 48 30 L48 24 Q32 4 16 24 Z"/>', '<path d="M14 34 Q32 6 50 34 L50 50 L46 50 L46 34 Q32 16 18 34 L18 50 L14 50 Z"/>',
      '<circle cx="32" cy="22" r="18"/>', '<path d="M14 30 Q32 10 50 30 Q44 20 32 20 Q20 20 14 30 Z"/>'][style];
    const mouth = r(2) > 0.5 ? '<path d="M26 42 Q32 47 38 42" stroke="#5a2d1a" stroke-width="2" fill="none"/>' : '<line x1="27" y1="43" x2="37" y2="43" stroke="#5a2d1a" stroke-width="2"/>';
    const glasses = r(3) > 0.7 ? '<g fill="none" stroke="#222" stroke-width="1.5"><circle cx="25" cy="33" r="5"/><circle cx="39" cy="33" r="5"/><line x1="30" y1="33" x2="34" y2="33"/></g>' : '';
    return `<svg viewBox="0 0 64 64"><rect width="64" height="64" fill="${bg}"/><circle cx="32" cy="34" r="17" fill="${skin}"/><g fill="${hair}">${hairPath}</g><circle cx="25" cy="33" r="2" fill="#222"/><circle cx="39" cy="33" r="2" fill="#222"/>${mouth}${glasses}</svg>`;
  }

  // 大廳的 AI 占位：簡單的機器人臉，眼睛會眨
  function robotSVG() {
    return `<svg viewBox="0 0 64 64"><rect width="64" height="64" fill="#1c2340"/><line x1="32" y1="10" x2="32" y2="18" stroke="#8fa3ff" stroke-width="3"/><circle cx="32" cy="8" r="3" fill="#8fa3ff" class="bulb"/>
      <rect x="14" y="18" width="36" height="30" rx="8" fill="#4a5a9a"/><rect x="20" y="26" width="24" height="12" rx="4" fill="#0e1430"/>
      <g class="eyes"><circle cx="26" cy="32" r="3" fill="#8fe3ff"/><circle cx="38" cy="32" r="3" fill="#8fe3ff"/></g>
      <rect x="22" y="50" width="20" height="6" rx="3" fill="#4a5a9a"/></svg>`;
  }

  function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function toast(t) { const el = $('toast'); el.textContent = t; el.classList.remove('hidden'); setTimeout(() => el.classList.add('hidden'), 2500); }
})();

/* Wall dashboard for an old tablet: live camera, the print, spools, alerts.
   Plain script, no optional chaining or ?? : older tablet browsers must run it too. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var STATE = { 0: 'Prête', 1: 'Mise en origine', 5: 'Pause…', 6: 'En pause', 7: 'Arrêt…', 8: 'Arrêtée', 9: 'Terminée', 12: 'Reprise',
                13: 'Impression', 14: 'Erreur', 15: 'Nivellement', 16: 'Préchauffe', 27: 'Changement de couleur', 28: 'Filament chargé', 29: 'Déchargement' };
  var IDLE = [0, 8, 9, 14];
  var ctx = { control: false }, busy = false, paused = false, lightOn = false, nightByUser = null, wake = null, sound = true;

  // a G-code name to read: the model and the layer height, as in the workshop ("…_canvas_0.20mm_PLA….gcode" -> "… · 0,20 mm")
  function nice(n) {
    var g = /^(.*?)(?:_canvas)?_(\d+(?:\.\d+)?)mm_.*\.gcode$/i.exec(n || '');
    var base = (g ? g[1] : String(n || '').replace(/\.[^.]+$/, '')).replace(/^\d{8}-\d{6}_/, '').replace(/_/g, ' ').trim();
    return (base || n) + (g ? ' · ' + g[2].replace('.', ',') + ' mm' : '');
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function get(path) {
    return fetch(path, { cache: 'no-store' }).then(function (r) {
      if (r.status === 401) { location.href = '/lab/login.html'; throw new Error('code'); }
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }
  function post(path, body) {
    return fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.detail || r.status); return j; }); });
  }
  function dur(s) { if (!s || s <= 0) return '–'; s = Math.round(s); var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? h + ' h ' + (m < 10 ? '0' : '') + m : m + ' min'; }
  function hm(d) { return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }); }
  function g(x) { return x >= 1000 ? (x / 1000).toFixed(2).replace('.', ',') + ' kg' : Math.round(x) + ' g'; }
  function euro(e) { return (e || 0).toFixed(2).replace('.', ',') + ' €'; }
  function when(t) { var d = new Date(t * 1000); return d.toDateString() === new Date().toDateString() ? hm(d) : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }); }
  var toastTimer = 0;
  function toast(title, detail, level) {
    var old = document.querySelector('.toast'); if (old) old.remove();
    var t = document.createElement('div'); t.className = 'toast ' + (level || '');
    t.innerHTML = '<b>' + esc(title) + '</b>' + (detail ? '<small>' + esc(detail) + '</small>' : '');
    document.body.appendChild(t); clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.remove(); }, level === 'bad' ? 60000 : 12000);
    t.onclick = function () { t.remove(); };
  }
  function beep(level) {
    if (!sound) return;
    try {
      var A = window.AudioContext || window.webkitAudioContext, a = new A(), notes = level === 'ok' ? [660, 880] : level === 'bad' ? [440, 330, 440, 330] : [550, 550];
      notes.forEach(function (f, i) { var o = a.createOscillator(), gn = a.createGain(); o.frequency.value = f; o.connect(gn); gn.connect(a.destination);
        var t = a.currentTime + i * 0.2; gn.gain.setValueAtTime(0.0001, t); gn.gain.exponentialRampToValueAtTime(0.3, t + 0.02); gn.gain.exponentialRampToValueAtTime(0.0001, t + 0.18); o.start(t); o.stop(t + 0.19); });
    } catch (e) {}
  }

  /* theme, same choice as the workshop on this device */
  try { var th = localStorage.getItem('cc2-theme'); if (th) document.documentElement.dataset.theme = th; } catch (e) {}

  /* colours: the spool engaged now and the next changes, every 15 s while printing */
  var cnAt = 0;
  function soon(m) { return m == null ? '' : m < 1 ? 'maintenant' : m < 60 ? 'dans ' + m + ' min' : 'dans ' + Math.floor(m / 60) + ' h ' + ('0' + (m % 60)).slice(-2); }
  function colours(on) {
    if (!on) { $('cn').hidden = true; cnAt = 0; return; }
    if (Date.now() - cnAt < 15000) return;
    cnAt = Date.now();
    get('/lab/api/couleurs').then(function (d) {
      if (!d.total) { $('cn').hidden = true; return; }
      function dot(c) { return '<span class="cn-dot" style="background:' + esc(c.hex) + '"></span>'; }
      var m = d.maintenant;
      $('cn').innerHTML = '<div class="cn-now">' + dot(m) + '<div><small>Couleur en cours</small><b>' + esc(m.nom) + '</b> <small style="display:inline">· bobine ' + m.bobine + '</small></div></div>'
        + (d.suivants.length ? '<div class="cn-next">' + d.suivants.slice(0, 3).map(function (n) {
            return '<div>' + dot(n) + '<div>' + esc(n.nom) + '<small>couche ' + n.couche + (n.min != null ? ' · ' + soon(n.min) : '') + '</small></div></div>';
          }).join('') + '</div>' : '')
        + '<p class="note" style="margin-top:8px">' + (d.restants ? d.restants + ' changement' + (d.restants > 1 ? 's' : '') + ' de couleur restant' + (d.restants > 1 ? 's' : '') : 'Plus de changement de couleur') + '</p>'
        // purges still to come, colour by colour ("21 / 65"); widths inline: old tablets lack CSS variables
        + ((d.purge || []).filter(function (p) { return p.total; }).length ? '<div class="cn-purge"><small>Purges restantes, par couleur</small>'
          + d.purge.filter(function (p) { return p.total; }).map(function (p) {
            return '<div>' + dot(p) + '<span class="n">' + esc(p.nom) + '</span><b>' + p.reste + '</b><small> / ' + p.total + '</small>'
              + '<i><i style="width:' + Math.round(100 * p.reste / p.total) + '%"></i></i></div>';
          }).join('') + '</div>' : '');
      $('cn').hidden = false;
    }).catch(function () { $('cn').hidden = true; });
  }

  /* section: the part seen from the front (printed layers in colour, the rest grey) and the layer being printed
     seen from above, drawn in 2D from the print's G-code in the library (nothing shown for a print started elsewhere) */
  var cp = { file: '', missing: '', layer: -1, wait: false, front: null, last: null };
  function coupe(file, layer) {
    if (!file || !layer || file === cp.missing) { $('coupe').hidden = true; return; }
    if (cp.wait || (file === cp.file && layer === cp.layer)) return;
    var first = file !== cp.file; cp.wait = true;
    get('/lab/api/models/' + encodeURIComponent(file) + '/coupe?couche=' + layer + '&face=' + (first ? 'true' : 'false')).then(function (d) {
      cp.wait = false;
      if (first) { cp.file = file; cp.front = d.front; }
      cp.layer = layer; cp.last = d; $('coupe').hidden = false; drawCoupe();
    }).catch(function () { cp.wait = false; cp.missing = file; $('coupe').hidden = true; });
  }
  function fit(cv) {
    var r = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.round(w * r); cv.height = Math.round(h * r);
    var g = cv.getContext('2d'); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, w, h);
    return { g: g, w: w, h: h };
  }
  function drawCoupe() {
    var d = cp.last; if (!d || !cp.front) return;
    var cols = d.colours.length ? d.colours : ['#d7dbe2'], box = d.box, n = d.layers.length, li = d.layer, pad = 10;
    var accent = getComputedStyle(document.documentElement).getPropertyValue('--acc') || '#ff9f0a';
    // front: X across, height up, one band per layer
    var f = fit($('cp-front')), top = d.layers[n - 1] || 1, bw = box[2] - box[0] || 1;
    var s = Math.min((f.w - 2 * pad) / bw, (f.h - 2 * pad) / top), x0 = (f.w - bw * s) / 2, y0 = f.h - pad;
    for (var i = 0; i < n; i++) {
      var z = d.layers[i], zp = i ? d.layers[i - 1] : 0, y = y0 - z * s, hh = Math.max(1, (z - zp) * s);
      for (var k = 0; k < cp.front[i].length; k++) {
        var run = cp.front[i][k];
        f.g.fillStyle = i < li ? cols[run[2] % cols.length] : 'rgba(150,150,160,.18)';
        f.g.fillRect(x0 + run[0] * d.bin * s, y, (run[1] - run[0] + 1) * d.bin * s, hh + .5);
      }
    }
    var yc = y0 - (d.layers[li - 1] || 0) * s;
    f.g.fillStyle = accent; f.g.fillRect(4, yc - 1, f.w - 8, 2);
    // above: the layer's paths, X across, Y up (the front of the plate down), same part box
    var t = fit($('cp-top')), bh = box[3] - box[1] || 1, q = Math.min((t.w - 2 * pad) / bw, (t.h - 2 * pad) / bh);
    var tx = (t.w - bw * q) / 2, ty = (t.h + bh * q) / 2, sec = d.section;
    t.g.lineWidth = Math.max(1, .45 * q); t.g.lineCap = 'round';
    for (var j = 0; j < d.tools.length; j++) {
      var o = j * 4;
      t.g.strokeStyle = cols[d.tools[j] % cols.length]; t.g.beginPath();
      t.g.moveTo(tx + (sec[o] - box[0]) * q, ty - (sec[o + 1] - box[1]) * q);
      t.g.lineTo(tx + (sec[o + 2] - box[0]) * q, ty - (sec[o + 3] - box[1]) * q); t.g.stroke();
    }
    $('cp-t').textContent = 'couche ' + li + ' / ' + n + ' · ' + (d.layers[li - 1] || 0).toFixed(1).replace('.', ',') + ' mm';
  }
  window.addEventListener('resize', drawCoupe);

  /* camera: one whole picture at a time through the workshop, the next asked once the last is shown:
     never late or frozen, and paused while the screen is hidden */
  var camImg = null, camRun = 0;
  function camera() {
    var run = ++camRun, fails = 0;
    function step() {
      if (run !== camRun || document.hidden) return;     // visibilitychange calls camera() again
      var nx = new Image(), guard = 0, done = false; nx.alt = 'Caméra de l\'imprimante';
      function again(ms) { done = true; clearTimeout(guard); setTimeout(step, ms); }
      nx.onload = function () {
        if (done || run !== camRun) return;
        if (camImg && camImg.parentNode) camImg.parentNode.replaceChild(nx, camImg); else $('cam').insertBefore(nx, $('cam').firstChild);
        camImg = nx; fails = 0; $('cam-msg').hidden = true; again(100);
      };
      nx.onerror = function () {
        if (done || run !== camRun) return;
        if (++fails >= 2) { if (camImg) camImg.remove(); camImg = null; $('cam-msg').hidden = false; $('cam-msg').textContent = 'Caméra indisponible : nouvel essai…'; }
        again(fails > 5 ? 15000 : 3000);
      };
      guard = setTimeout(function () { nx.onerror(); }, 12000);   // a picture that never arrives
      nx.src = '/lab/api/camera?t=' + Date.now();
    }
    step();
  }

  /* the print */
  function status() {
    return get('/status').then(function (s) {
      var ps = s.print_status || 0, raw = s.raw || {}, info = raw.PrintInfo || {}, cc = raw._cc2 || {};
      busy = IDLE.indexOf(ps) < 0; paused = ps === 5 || ps === 6;
      var prog = busy || ps === 9 ? (s.progress || 0) : 0;
      $('state').textContent = STATE[ps] || ('État ' + ps);
      $('pill').className = 'pill ' + (ps === 14 ? 'bad' : paused ? 'warn' : busy ? 'busy' : '');
      $('pill-t').textContent = ps === 14 ? 'Erreur' : paused ? 'En pause' : busy ? 'En cours' : 'Disponible';
      $('file').textContent = busy ? nice((s.filename || '').split('/').pop()) : '';
      $('pct').textContent = busy || ps === 9 ? prog + ' %' : '–';
      $('ring').setAttribute('stroke-dashoffset', String(314.16 * (1 - prog / 100)));
      $('bar').style.width = (busy ? prog : 0) + '%';
      var left = cc.remaining_time_sec != null ? cc.remaining_time_sec : (info.TotalTicks || 0) - (info.CurrentTicks || 0);
      var layer = s.layer || {};
      var rows = busy ? [['Reste', dur(left)], ['Fin vers', left > 0 ? hm(new Date(Date.now() + left * 1000)) : '–'],
                         ['Couche', layer.current != null ? layer.current + (layer.total ? ' / ' + layer.total : '') : '–'],
                         ['Écoulé', dur(info.CurrentTicks)]]
                      : [['Plateau', 'libre ?'], ['Buse', Math.round(((s.temperatures || {}).nozzle || {}).actual || 0) + ' °C']];
      coupe(busy ? (s.filename || '').split('/').pop() : '', busy ? layer.current : 0);
      colours(busy);
      $('kv').innerHTML = rows.map(function (r) { return '<span>' + r[0] + '</span><b>' + esc(r[1]) + '</b>'; }).join('');
      var T = s.temperatures || {};
      $('temps').innerHTML = [['nozzle', 'Buse'], ['bed', 'Plateau'], ['chamber', 'Caisson']].map(function (r) {
        var t = T[r[0]] || {}, a = Math.round(t.actual || 0), tg = Math.round(t.target || 0);
        return '<div><div class="v">' + a + '°</div><div class="l">' + r[1] + '</div><div class="g">' + (tg ? '→ ' + tg + '°' : 'arrêté') + '</div></div>';
      }).join('');
      lightOn = !!(raw.LightStatus && raw.LightStatus.SecondLight);
      $('b-light').className = 'btn' + (lightOn ? ' on' : '');
      $('b-pause').querySelector('span').textContent = paused ? 'Reprendre' : 'Pause';
      $('b-pause').disabled = !ctx.control || !busy || ps === 5;
      $('b-stop').disabled = !ctx.control || !busy;
      $('b-light').disabled = !ctx.control;
      [].forEach.call(document.querySelectorAll('#spd [data-speed]'), function (b) {   // the CC2 only takes a speed during a print
        b.className = 'btn' + (busy && +b.getAttribute('data-pct') === info.PrintSpeedPct ? ' on' : '');
        b.disabled = !ctx.control || !busy;
      });
      $('idle').hidden = busy;
      autoNight();
    }).catch(function () { $('state').textContent = 'Imprimante injoignable'; $('pill').className = 'pill bad'; $('pill-t').textContent = 'Hors ligne'; });
  }

  /* spools: CANVAS (live) + the workshop's stock */
  function spools() {
    return Promise.all([get('/canvas').catch(function () { return null; }), get('/lab/api/bobines').catch(function () { return null; })]).then(function (r) {
      var c = (r[0] && r[0].canvas_info) || {}, st = r[1], unit = (c.canvas_list || [])[0] || {}, trays = unit.tray_list || [];
      $('refill').textContent = c.auto_refill ? 'recharge auto' : '';
      if (st) $('month').textContent = 'ce mois : ' + st.mois.impressions + ' · ' + g(st.mois.g) + ' · ' + euro(st.mois.eur);
      $('spools').innerHTML = trays.length ? trays.map(function (t, pos) {
        var col = String(t.filament_color || t.color || ''), on = t.status === 1 || t.status === 2, k = st && st.trays.filter(function (x) { return x.tray === pos; })[0];
        var pct = k ? Math.round(100 * k.restant_g / k.poids_g) : 0;
        return '<div class="sp' + (t.tray_id === c.active_tray_id ? ' on' : '') + '"><div class="c" style="background:' + (on && /^#[0-9A-Fa-f]{6}$/.test(col) ? col : 'transparent') + '"></div>'
          + '<div class="n">T' + pos + ' · ' + esc(on ? (t.filament_type || t.type || '?') : 'vide') + '</div>'
          + (on && k ? '<div class="gauge' + (k.restant_g < st.low_g ? ' low' : '') + '"><i style="width:' + pct + '%"></i></div><div class="g">' + g(k.restant_g) + '</div>' : '<div class="g">' + esc(on ? t.filament_name || '' : '') + '</div>') + '</div>';
      }).join('') : '<p class="note">CANVAS non détecté</p>';
      // a spool just put in: same one as before, or a new one? (the likeliest answer is already counted)
      $('ask').innerHTML = (st ? st.trays : []).filter(function (k) { return k.question; }).map(function (k) {
        var n = k.tray + 1, same = '<button class="btn" data-ask="' + k.tray + '" data-same="' + k.restant_g + '">';
        return '<div class="ask"><b>Bobine ' + n + ' : ' + esc(k.nom) + (k.question.remise ? ' reconnue' : ', nouvelle') + '</b>'
          + (k.question.remise ? '<small>La même qu\'avant (' + g(k.restant_g) + ' restants) ou une neuve ?</small>' + same + 'La même</button><button class="btn" data-ask="' + k.tray + '" data-new="1">Une neuve</button>'
             : '<small>Neuve (' + g(k.poids_g) + ') ou déjà entamée ?</small>' + same + 'Neuve</button><button class="btn" data-ask="' + k.tray + '" data-left="1">Déjà entamée…</button>') + '</div>';
      }).join('');
    });
  }
  $('ask').addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('[data-ask]') : null, body;
    if (!b) return;
    if (b.getAttribute('data-new')) body = { nouvelle: true };
    else if (b.getAttribute('data-left')) {
      var v = parseFloat(String(window.prompt('Combien de grammes restent sur cette bobine ?', '') || '').replace(',', '.'));
      if (!(v >= 0)) return;
      body = { restant_g: v };
    } else body = { restant_g: +b.getAttribute('data-same') };
    post('/lab/api/bobines/' + b.getAttribute('data-ask'), body).then(function () { toast('Bobine mise à jour', '', 'ok'); spools(); })
      .catch(function (e) { toast(e.message, '', 'bad'); });
  });

  /* camera AI */
  function ai() {
    return get('/lab/api/surveillance').then(function (s) {
      var L = s.live || {}, on = s.modele && s.ia;
      $('ia').hidden = !on || !L.en_cours;
      $('ia').className = 'pill ' + (L.etat === 'pause' ? 'bad' : L.etat === 'suspect' ? 'warn' : '');
      $('ia-t').textContent = L.etat === 'pause' ? 'IA : raté, en pause' : L.etat === 'suspect' ? 'IA : suspect' : 'IA : tout va bien';
    }).catch(function () {});
  }

  /* idle: last print, maintenance */
  function idle() {
    get('/lab/api/galerie').then(function (list) {
      var e = list.filter(function (x) { return x.issue !== 'en cours'; })[0];
      $('last').innerHTML = e ? (e.photo ? '<img alt="" src="/lab/api/galerie/' + encodeURIComponent(e.id) + '/' + encodeURIComponent(e.photo) + '">' : '<div></div>')
        + '<div><b>' + esc(e.fichier.replace(/\.gcode$/, '')) + '</b><div class="note">' + when(e.debut) + ' · ' + dur(e.duree_s) + (e.g ? ' · ' + g(e.g) + ' · ' + euro(e.eur) : '')
        + '</div><div class="note">' + ({ terminee: 'Terminée', arretee: 'Arrêtée', erreur: 'Erreur' }[e.issue] || e.issue) + '</div></div>' : '<p class="note">Aucune impression enregistrée.</p>';
    }).catch(function () {});
    get('/lab/api/entretien').then(function (l) {
      var due = l.filter(function (t) { return t.a_faire; });
      $('maint').textContent = due.length ? 'Entretien à faire : ' + due.map(function (t) { return t.titre.toLowerCase(); }).join(', ') + '.' : 'Entretien à jour.';
    }).catch(function () {});
  }

  /* alerts: live stream, last ones listed */
  var events = [];
  function renderEvents() {
    $('events').innerHTML = events.length ? events.slice(0, 5).map(function (e) {
      return '<div class="ev ' + esc(e.level) + '"><span class="d"></span><div>' + esc(e.title) + '<small>' + esc(e.detail || '') + '</small></div><time>' + when(e.t) + '</time></div>';
    }).join('') : '<p class="note">Rien pour l\'instant.</p>';
  }
  function alerts() {
    get('/lab/api/events').then(function (l) { events = l; renderEvents(); }).catch(function () {});
    if (!window.EventSource) return;
    var es = new EventSource('/lab/api/events/stream');
    es.addEventListener('alerte', function (m) {
      var e = JSON.parse(m.data);
      if (e.update) { idle(); return; }
      events.unshift(e); renderEvents();
      if (e.level !== 'info' || e.kind === 'debut') { toast(e.title, e.detail, e.level); beep(e.level); }
      if (e.level === 'bad' || e.kind === 'fin' || e.kind === 'froid') setNight(false);   // wake the screen up: a problem, or a part to take
      status(); if (e.kind === 'fin' || e.kind === 'arret') { idle(); spools(); }
    });
  }

  /* night: dim at night when nothing prints, or by hand */
  function setNight(on) { document.body.classList.toggle('nuit', on); $('b-night').className = 'btn' + (on ? ' on' : ''); }
  function autoNight() {
    if (nightByUser !== null) return;
    var h = new Date().getHours();
    setNight(!busy && (h >= 22 || h < 7));
  }
  $('b-night').onclick = function () { nightByUser = !document.body.classList.contains('nuit'); setNight(nightByUser); };
  document.body.addEventListener('click', function (ev) {      // a touch on a dimmed screen brightens it
    if (document.body.classList.contains('nuit') && !ev.target.closest('#b-night')) { nightByUser = false; setNight(false); }
  }, true);

  /* controls */
  function act(path, body, ok) {
    return post(path, body).then(function () { if (ok) toast(ok, '', 'ok'); setTimeout(status, 800); })
      .catch(function (e) { toast(path === '/print/resume' ? 'Reprise refusée en réseau' : 'Commande refusée', path === '/print/resume' ? 'Reprends depuis l\'écran de l\'imprimante.' : e.message, 'bad'); });
  }
  $('b-light').onclick = function () { act('/light', { on: !lightOn }); };
  $('spd').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-speed]'); if (b && !b.disabled) act('/print/speed', { mode: b.getAttribute('data-speed') }, 'Vitesse changée');
  });
  $('b-pause').onclick = function () {
    if (paused) { act('/print/resume', null, 'Reprise demandée'); return; }
    if (confirm('Mettre l\'impression en pause ?')) act('/print/pause', null, 'Pause demandée');
  };
  var hold = 0, holdStart = 0;
  function holdDown(ev) {
    if ($('b-stop').disabled) return;
    ev.preventDefault(); holdStart = Date.now();
    hold = setInterval(function () {
      var p = Math.min(1, (Date.now() - holdStart) / 2000);
      $('stop-fill').style.width = (p * 100) + '%';
      if (p >= 1) { holdUp(); act('/print/stop', null, 'Arrêt demandé'); }
    }, 50);
  }
  function holdUp() { clearInterval(hold); $('stop-fill').style.width = '0'; }
  ['mousedown', 'touchstart'].forEach(function (n) { $('b-stop').addEventListener(n, holdDown); });
  ['mouseup', 'mouseleave', 'touchend', 'touchcancel'].forEach(function (n) { $('b-stop').addEventListener(n, holdUp); });

  /* keep the screen on (Wake Lock needs HTTPS: the workshop's phone address has it) */
  function keepAwake() {
    if (!('wakeLock' in navigator)) return;
    navigator.wakeLock.request('screen').then(function (w) { wake = w; }).catch(function () {});
  }
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') { keepAwake(); camera(); } });
  $('back').onclick = function () {
    var ex = document.exitFullscreen || document.webkitExitFullscreen;
    if (ex && (document.fullscreenElement || document.webkitFullscreenElement)) try { ex.call(document); } catch (e) {}
    location.href = '/lab/';
  };
  $('go').onclick = function () {
    $('start').hidden = true;
    var el = document.documentElement, fs = el.requestFullscreen || el.webkitRequestFullscreen;
    if (fs) try { fs.call(el); } catch (e) {}
    keepAwake(); beep('info');
  };

  get('/lab/api/context').then(function (c) {
    ctx = c;
    if (!ctx.control) $('ctl-note').textContent = 'Lecture seule : l\'atelier tourne sans --control.';
  }).catch(function () {}).then(function () {
    camera(); status(); spools(); ai(); idle(); alerts();
    setInterval(status, 3000); setInterval(spools, 20000); setInterval(ai, 10000); setInterval(idle, 120000);
  });
})();

import { hooks, nice, $, BUSY, STATE, act, api, ctl, ctx, dur, esc, euro, fmtG, size, toast } from './core.js';
import * as THREE from 'three';
import { buildPaths, cam, files, frame, grid, info, launchFile, miniViewer, trays, upload } from './lab.js';

/* printer status */
async function pollPrinter() {
  try {
    const s = await (await fetch('/status')).json(), ps = s.print_status ?? 0, busy = ![0, 8, 9].includes(ps);
    $('printer').className = 'pill ' + (busy ? 'busy' : 'ok');
    $('printer-txt').textContent = `${STATE[ps] || 'État ' + ps}${busy && s.progress != null ? ' · ' + s.progress + ' %' : ''}`;
    $('printer-temp').textContent = ` · buse ${Math.round(s.temperatures?.nozzle?.actual ?? 0)} °C`;
  } catch { $('printer').className = 'pill'; $('printer-txt').textContent = 'Injoignable'; $('printer-temp').textContent = ''; }
  setTimeout(pollPrinter, 4000);
}

/* ---------------- printer view ---------------- */
// commands the CC2 may refuse over LAN (Elegoo's SDK disables them): say where to do it instead
let pvTimer = null, pvOpen = false, lastSt = null;

function openPrinter() {
  pvOpen = true;
  loadQueue();
  $('pv-ro').hidden = !!ctx.control;
  document.querySelectorAll('#pv [data-ctl]').forEach(el => el.disabled = !ctx.control);
  openCamera(); pvStatus(); pvCanvas(); pvFiles(); svLoad(); mcLoad(); mtLoad();
}
/* camera: one whole picture at a time, the next asked once the last is shown (a slow phone gets fewer
   pictures, never late or frozen ones); paused while the page is hidden */
let camRun = 0;
function closeCamera() { pvOpen = false; camRun++; $('pv-cam').querySelectorAll('img').forEach(i => i.remove()); $('pv-cam-msg').hidden = false; }
function openCamera() {
  const run = ++camRun, box = $('pv-cam');
  let fails = 0, guard = 0;
  const step = () => {
    if (run !== camRun) return;
    if (document.hidden) { document.addEventListener('visibilitychange', step, { once: true }); return; }
    const nx = new Image(); nx.alt = 'Caméra de l\'imprimante';
    const again = ms => { clearTimeout(guard); nx.onload = nx.onerror = null; setTimeout(step, ms); };
    nx.onload = () => {
      if (run !== camRun) return;
      const cur = box.querySelector('img'); cur ? cur.replaceWith(nx) : box.append(nx);
      fails = 0; $('pv-cam-msg').hidden = true; again(70);
    };
    nx.onerror = () => {
      if (run !== camRun) return;
      if (++fails >= 2) {
        box.querySelectorAll('img').forEach(i => i.remove()); $('pv-cam-msg').hidden = false;
        $('pv-cam-msg').innerHTML = 'Caméra indisponible, nouvel essai…<br><span style="font-size:12px">Vérifie que l\'imprimante est allumée et en mode LAN</span>';
      }
      again(fails > 5 ? 10000 : 2000);
    };
    guard = setTimeout(() => { nx.src = ''; nx.onerror?.(); }, 12000);   // a picture that never arrives
    nx.src = '/lab/api/camera?t=' + Date.now();
  };
  step();
}

/* colours: the spool engaged now (CANVAS) and the next changes (G-code), every 15 s while printing */
let cnTimer = 0, cnFor = '';
const cnWhen = m => m == null ? '' : m < 1 ? 'maintenant' : m < 60 ? `dans ${m} min` : `dans ${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
async function colourPlan(busy, name) {
  const box = $('pv-cn');
  if (!busy || !name) { box.hidden = true; cnFor = ''; return; }
  if (cnFor === name && Date.now() - cnTimer < 15000) return;
  cnFor = name; cnTimer = Date.now();
  let d;
  try { d = await api('/couleurs'); } catch { box.hidden = true; return; }   // started from the printer: no G-code here
  if (!d.total) { box.hidden = true; return; }    // one colour: nothing to follow
  const dot = c => `<span class="cn-dot" style="background:${esc(c.hex)}"></span>`;
  box.innerHTML = `<div class="cn-now">${dot(d.maintenant)}<div><small>Couleur en cours</small><b>${esc(d.maintenant.nom)}</b> <small style="display:inline">· bobine ${d.maintenant.bobine}</small></div></div>`
    + (d.suivants.length ? `<div class="cn-next">${d.suivants.map(n => `<div>${dot(n)}<div>${esc(n.nom)}<small>couche ${n.couche}${n.min != null ? ' · ' + cnWhen(n.min) : ''}</small></div></div>`).join('')}</div>` : '')
    + `<div class="cn-foot">${d.restants ? `${d.restants} changement${d.restants > 1 ? 's' : ''} de couleur restant${d.restants > 1 ? 's' : ''} sur ${d.total}` : 'Plus de changement de couleur jusqu\'à la fin'}</div>`;
  box.hidden = false;
}

/* layer by layer: the print's own G-code from the library, printed layers in colour, the rest greyed */
let lv = null, lvFor = '', lvParts = null, lvLayers = [], lvLoading = false;
async function layersTrack(busy, name, cur) {
  const card = $('pv-layers'), file = (name || '').split('/').pop();
  if (!busy || !file) { card.hidden = true; return; }
  if (file !== lvFor) {
    if (lvLoading) return;
    lvLoading = true; lvFor = file; lvParts = null;
    let d = null;
    try { d = await api(`/models/${encodeURIComponent(file)}/paths`); } catch {}   // started from elsewhere: not in the library
    lvLoading = false;
    lv = lv || (d && miniViewer('pv-3d', () => pvOpen && !card.hidden && !document.hidden));
    if (!d || !lv || file !== lvFor) { card.hidden = true; return; }
    const { group, parts } = buildPaths(d), grey = new THREE.LineBasicMaterial({ color: 0x8a97a8, transparent: true, opacity: .16 });
    parts.forEach(p => {   // the rest: the same lines, drawn from the current layer on
      const g = new THREE.BufferGeometry(); g.setAttribute('position', p.lines.geometry.getAttribute('position'));
      p.rest = new THREE.LineSegments(g, grey); p.rest.visible = p.lines.visible; group.add(p.rest);
    });
    lvParts = parts; lvLayers = d.layers; card.hidden = false; lv.set(group, true);
    lv.c.position.lerp(lv.ctl.target, .35);   // closer than the generic fit: lines need it more than a solid
  }
  if (!lvParts) return;
  const nl = lvLayers.length, l = Math.max(0, Math.min(nl, cur || 0)), mm = v => (v ?? 0).toFixed(1).replace('.', ',');
  lvParts.forEach(p => {
    const done = p.start[l] * 2, all = p.start[nl] * 2;
    p.lines.geometry.setDrawRange(0, done); p.rest.geometry.setDrawRange(done, all - done);
  });
  $('pv-lnote').textContent = `Couche ${l} / ${nl} · ${mm(lvLayers[l - 1])} mm sur ${mm(lvLayers[nl - 1])} mm`;
}

hooks.afterAct = () => pvStatus();
async function pvStatus() {
  clearTimeout(pvTimer);
  try {
    const s = await (await fetch('/status')).json(); lastSt = s;
    const ps = s.print_status ?? 0, raw = s.raw || {}, info = raw.PrintInfo || {}, cc = raw._cc2 || {};
    const busy = BUSY.has(ps), paused = ps === 6, prog = busy || ps === 9 ? (s.progress ?? 0) : 0;
    // the title is what is printing, the pill says how it goes (printing, paused, changing filament…)
    $('pv-state').textContent = s.filename ? nice(s.filename) : ps === 9 ? 'Impression terminée' : busy ? STATE[ps] : 'Rien en cours';
    $('pv-state').title = s.filename || '';
    $('pv-job').classList.toggle('idle', !busy);
    queueState(busy);
    layersTrack(busy, s.filename, s.layer?.current);
    colourPlan(busy, s.filename);
    $('pv-pill').className = 'pill ' + (busy ? 'busy' : 'ok'); $('pv-pill-t').textContent = busy ? (STATE[ps] || 'En cours') : ps === 9 ? 'Terminée' : 'Disponible';
    $('pv-file').textContent = busy || ps === 9 ? '' : 'Aucune impression en cours';
    $('pv-prog').style.width = prog + '%'; $('pv-cam').style.setProperty('--p', prog + '%'); $('pv-cam').classList.toggle('live', busy); $('pv-pct').textContent = prog + ' %';
    $('pv-layer').textContent = busy && s.layer?.current != null ? `${s.layer.current}${s.layer.total ? ' / ' + s.layer.total : ''}` : '–';
    const left = cc.remaining_time_sec ?? ((info.TotalTicks || 0) - (info.CurrentTicks || 0));
    $('pv-left').textContent = busy ? dur(left) : '–';
    $('pv-end').textContent = busy && left > 0 ? new Date(Date.now() + left * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '–';
    $('pv-pause').hidden = paused; $('pv-resume').hidden = !paused;
    document.querySelectorAll('[data-start]').forEach(b => { b.disabled = !ctx.control || busy; b.title = busy ? 'Une impression est déjà en cours' : ''; });
    $('pv-pause').disabled = !ctx.control || !busy || ps === 5; $('pv-stop').disabled = !ctx.control || !busy;
    // temperatures
    const T = s.temperatures || {}, rows = [['nozzle', 'Buse', 300], ['bed', 'Plateau', 110], ['chamber', 'Caisson', 60]];
    if (!$('pv-temps').children.length) $('pv-temps').innerHTML = rows.map(([k, l, max]) => `<div class="temp"><div><div class="lbl">${l}</div><div class="now" id="t-${k}">–</div><span class="heat"><i id="th-${k}"></i></span></div>
      <input type="number" min="0" max="${max}" step="5" id="tv-${k}" aria-label="Consigne ${l}" data-ctl ${ctx.control ? '' : 'disabled'}><button class="btn" data-ctl data-settemp="${k}" ${ctx.control ? '' : 'disabled'}>Régler</button></div>`).join('');
    for (const [k] of rows) {
      const t = T[k] || {}, a = Math.round(t.actual ?? 0), g = Math.round(t.target ?? 0);
      $('t-' + k).innerHTML = `${a}°<small> ${g ? '→ ' + g + '°' : 'arrêté'}</small>`;
      $('th-' + k).style.width = g ? Math.min(100, 100 * a / g) + '%' : '0';
      if (document.activeElement !== $('tv-' + k)) $('tv-' + k).placeholder = g || 0;
    }
    $('pv-light').checked = !!raw.LightStatus?.SecondLight;
    $('pv-cam-light').hidden = !!raw.LightStatus?.SecondLight || !raw.LightStatus;   // light off: the camera shows black
  } catch { $('pv-state').textContent = 'Imprimante injoignable'; $('pv-pill').className = 'pill'; $('pv-pill-t').textContent = 'Hors ligne'; }
  if (pvOpen) pvTimer = setTimeout(pvStatus, 2000);
}

let stockData = null, trayEdit = null;
$('pv-trays').addEventListener('click', e => {
  const b = e.target.closest('[data-tray]'); if (!b || !stockData) return;
  const k = stockData.trays.find(x => x.tray === +b.dataset.tray); if (!k) return;
  trayEdit = k.tray; $('tray-t').textContent = `Bobine ${k.tray + 1}${k.nom ? ' · ' + k.nom : ''}`;
  $('tray-left').value = Math.round(k.restant_g); $('tray-full').value = Math.round(k.poids_g); $('tray-price').value = k.prix_kg;
  $('tray-dlg').showModal();
});
async function traySave(body) {
  try { await api('/bobines/' + trayEdit, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); $('tray-dlg').close(); toast('Bobine mise à jour', 'ok'); pvCanvas(); }
  catch (e) { toast(e.message, 'bad'); }
}
$('tray-save').onclick = () => traySave({ poids_g: +$('tray-full').value, restant_g: +$('tray-left').value, prix_kg: +$('tray-price').value });
$('tray-new').onclick = () => traySave({ poids_g: +$('tray-full').value, prix_kg: +$('tray-price').value, nouvelle: true });
async function pvCanvas() {
  try {
    const c = (await (await fetch('/canvas')).json()).canvas_info || {};
    const trays = (c.canvas_list || [])[0]?.tray_list || [];
    $('pv-refill').checked = !!c.auto_refill;
    const st = await api('/bobines').catch(() => null); stockData = st;
    const left = id => st?.trays.find(x => x.tray === id);
    // Elegoo's SDK says filament_color / filament_type and status 2 when loaded; the simulator's older capture said color / type
    const norm = (t, pos) => { const col = String(t.filament_color || t.color || ''), on = t.status === 1 || t.status === 2;
      return { pos, id: t.tray_id, on, colour: /^#[0-9A-Fa-f]{6}$/.test(col) ? col : '#888888', type: t.filament_type || t.type || '', name: t.filament_name || '' }; };
    $('pv-trays').innerHTML = trays.length ? trays.map(norm).map(t => { const k = left(t.pos), pct = k ? Math.round(100 * k.restant_g / k.poids_g) : 0;
      return `<button class="tray ${t.id === c.active_tray_id ? 'active' : ''}" data-tray="${t.pos}" title="Modifier le stock de la bobine ${t.pos + 1}">
      <div class="spool-c" style="background:${t.on ? t.colour : 'transparent'}"></div><div class="tn">${t.pos + 1} · ${esc(t.on ? t.type || '?' : 'vide')}</div>
      <div class="tt">${t.on ? esc(t.name) : 'Vide'}</div>
      ${t.on && k ? `<div class="gauge ${k.restant_g < st.low_g ? 'low' : ''}"><i style="width:${pct}%"></i></div><div class="tt"><b>${fmtG(k.restant_g)}</b> restants</div>` : ''}</button>`; }).join('')
      : '<div class="empty" style="grid-column:1/-1">CANVAS non détecté</div>';
    $('pv-month').textContent = st ? `Ce mois : ${st.mois.impressions} impression${st.mois.impressions > 1 ? 's' : ''} · ${fmtG(st.mois.g)} · ${euro(st.mois.eur)}` : '';
  } catch { $('pv-trays').innerHTML = '<div class="empty" style="grid-column:1/-1">CANVAS injoignable</div>'; }
  if (pvOpen) setTimeout(pvCanvas, 10000);
}

async function pvFiles() {
  const [f, h] = await Promise.allSettled([(await fetch('/files')).json(), (await fetch('/history')).json()]);
  const files = f.status === 'fulfilled' ? f.value.file_list || [] : null;
  $('pv-files').innerHTML = files == null ? '<div class="empty">Liste indisponible (certains firmwares ne la fournissent pas)</div>'
    : files.length ? `<table class="list"><thead><tr><th>Fichier</th><th class="m-hide" style="text-align:right">Couches</th><th style="text-align:right">Durée</th><th class="m-hide" style="text-align:right">Taille</th><th></th></tr></thead><tbody>${files.map(x => `<tr><td class="fcell" title="${esc(x.filename)}">${esc(nice(x.filename))}</td>
      <td class="r m-hide">${x.layer ?? '–'}</td><td class="r">${dur(x.print_time)}</td><td class="r m-hide">${size(x.size || 0)}</td>
      <td class="r"><button class="btn" data-ctl data-start="${esc(x.filename)}" ${ctx.control ? '' : 'disabled'}><svg class="i"><use href="#i-play"/></svg><span class="m-hide">Imprimer</span></button>
      <button class="btn ghost" data-ctl data-rm="${esc(x.filename)}" title="Supprimer" ${ctx.control ? '' : 'disabled'}><svg class="i"><use href="#i-trash"/></svg></button></td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Aucun fichier. Envoie un G-code depuis l\'atelier.</div>';
  const hist = h.status === 'fulfilled' ? (h.value.history_task_list || []).slice().reverse() : [];
  $('pv-hist').innerHTML = hist.length ? `<table class="list"><tbody>${hist.slice(0, 15).map(x => `<tr><td class="fcell" title="${esc(x.task_name || '')}">${esc(x.task_name ? nice(x.task_name) : '?')}</td>
    <td class="r">${x.begin_time ? new Date(x.begin_time * 1000).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}</td>
    <td class="r">${x.end_time && x.begin_time ? dur(x.end_time - x.begin_time) : ''}</td>
    <td class="r ${x.task_status === 1 ? 'ok-t' : 'bad-t'}">${x.task_status === 1 ? 'Terminée' : x.task_status === 2 ? 'Annulée' : 'État ' + x.task_status}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Aucune impression pour l\'instant.</div>';
}

$('pv-refresh').onclick = pvFiles;
$('pv-pause').onclick = e => act(e.currentTarget, '/print/pause', null, 'Pause demandée');
$('pv-resume').onclick = e => act(e.currentTarget, '/print/resume', null, 'Reprise demandée');
$('pv-stop').onclick = e => { if (confirm('Arrêter l\'impression en cours ?\n\nElle ne pourra pas être reprise.')) act(e.currentTarget, '/print/stop', null, 'Arrêt demandé'); };
$('pv-light').onchange = e => act(null, '/light', { on: e.target.checked });
$('pv-cam-light').onclick = e => act(e.currentTarget, '/light', { on: true });
// the CC2 cannot switch itself off over the network: the closest is everything that heats, blows or lights, off
$('pv-rest').onclick = async e => {
  if (!confirm('Mettre l\'imprimante au repos ?\n\nChauffes, ventilateurs et lumière coupés. Pour l\'éteindre complètement, utilise son interrupteur.')) return;
  const b = e.currentTarget; b.disabled = true;
  // the CC2 refuses temperatures over the network (error 1003): only ask when something is actually heating
  const heating = Object.values(lastSt?.temperatures || {}).some(t => (t?.target ?? 0) > 0);
  const steps = [...(heating ? [['chauffes', '/print/temperature', { nozzle: 0, bed: 0, chamber: 0 }]] : []),
    ['ventilateurs', '/print/fan', { model: 0, auxiliary: 0, chamber: 0 }], ['lumière', '/light', { on: false }]], refused = [];
  for (const [what, path, body] of steps) { try { await ctl(path, body); } catch { refused.push(what); } }   // one refusal must not keep the rest on
  toast(refused.length ? `Au repos, sauf : ${refused.join(', ')} (à couper sur l'écran de l'imprimante)` : 'Imprimante au repos', refused.length ? 'bad' : 'ok');
  b.disabled = !ctx.control; setTimeout(pvStatus, 600);
};
$('pv-refill').onchange = e => act(null, '/canvas/refill', { enabled: e.target.checked }, e.target.checked ? 'Recharge auto activée' : 'Recharge auto désactivée');
document.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => { const [n, bed] = b.dataset.preset.split(',').map(Number); act(b, '/print/temperature', { nozzle: n, bed }, n ? `Chauffe : buse ${n}°, plateau ${bed}°` : 'Refroidissement'); });
$('pv').addEventListener('click', e => {
  const set = e.target.closest('[data-settemp]'), start = e.target.closest('[data-start]'), rm = e.target.closest('[data-rm]');
  if (set) { const k = set.dataset.settemp, v = $('tv-' + k).value; if (v === '') return toast('Indique une température', 'bad'); act(set, '/print/temperature', { [k]: +v }, 'Consigne envoyée'); $('tv-' + k).value = ''; }
  if (start) launchFile(start.dataset.start, { upload: false, button: start }).then(pvFiles);
  if (rm && confirm(`Supprimer ${rm.dataset.rm} de l'imprimante ?`)) act(rm, '/files/delete', { filenames: [rm.dataset.rm] }, 'Fichier supprimé').then(pvFiles);
});


/* machine */
async function mcLoad() {
  const [a, d, o] = await Promise.all([fetch('/attributes').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/disk').then(r => r.ok ? r.json() : null).catch(() => null), api('/lancement').catch(() => null)]);
  if (a) {
    $('mc-fw').textContent = a.firmware_version ? 'firmware ' + a.firmware_version : '';
    const total = d?.total_bytes, used = d?.used_bytes;
    $('mc-info').innerHTML = [['Nom', a.name], ['Modèle', a.machine_name], ['N° de série', a.mainboard_id],   // the CC2 does not report its storage
      ...(total ? [['Stockage', `${size(total - used)} libres sur ${size(total)}`]] : [])].map(([k, v]) => `<span>${k}</span><span title="${esc(v || '')}">${esc(v || '–')}</span>`).join('');
  } else $('mc-info').innerHTML = '<span>État</span><span>imprimante injoignable</span>';
  if (o) { $('mc-level').checked = o.bedlevel_force; $('mc-check').checked = o.printer_check; $('mc-video').checked = o.delay_video; }
}
for (const [id, key] of [['mc-level', 'bedlevel_force'], ['mc-check', 'printer_check'], ['mc-video', 'delay_video']])
  $(id).onchange = () => api('/lancement', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [key]: $(id).checked }) })
    .then(() => toast('Option enregistrée pour les prochains lancements', 'ok')).catch(e => toast(e.message, 'bad'));

/* maintenance */
function mtRender(list) {
  const due = list.filter(t => t.a_faire).length;
  $('mt-sum').textContent = due ? `${due} à faire` : 'à jour';
  const row = t => `<div class="mt ${t.a_faire ? 'due' : ''}"><div class="mt-h"><b>${esc(t.titre)}</b><button class="btn ghost" data-mt="${t.id}">Fait</button></div>
    <div class="gauge ${t.a_faire ? 'low' : ''}"><i style="width:${Math.min(100, 100 * t.avancement)}%"></i></div>
    <div class="note" style="margin:2px 0 0">${t.heures} h d'impression et ${t.jours} j depuis la dernière fois · tous les ${esc(t.intervalle)}</div>
    ${t.a_faire ? `<p class="note" style="margin:4px 0 0;color:var(--dim)">${esc(t.geste)}</p>` : ''}</div>`;
  // what is due stays in sight; the rest folds into one line saying which comes next
  const ok = list.filter(t => !t.a_faire), next = [...ok].sort((a, b) => b.avancement - a.avancement)[0];
  const open = $('mt-list').querySelector('.mt-more')?.open ? ' open' : '';
  $('mt-list').innerHTML = list.filter(t => t.a_faire).map(row).join('') + (ok.length ? `<details class="mt-more"${open}><summary>${due
    ? `${ok.length} autre${ok.length > 1 ? 's' : ''} à jour`
    : `Tout est à jour · prochain : ${esc(next.titre)} (${Math.round(100 * next.avancement)} %)`}</summary>${ok.map(row).join('')}</details>` : '');
  $('mt-list').querySelectorAll('[data-mt]').forEach(b => b.onclick = async () => { mtRender(await api('/entretien/' + b.dataset.mt, { method: 'POST' })); toast('Entretien noté', 'ok'); });
}
async function mtLoad() { const l = await api('/entretien').catch(() => null); if (l) mtRender(l); }

/* camera watch */
let svTimer = 0;
async function svLoad() {
  clearTimeout(svTimer);
  const s = await api('/surveillance').catch(() => null); if (!s) return;
  $('sv-model').hidden = s.modele; $('sv-ia').checked = s.ia; $('sv-pause').checked = s.pause_auto; $('sv-tl').checked = s.timelapse;
  $('sv-ia').disabled = $('sv-pause').disabled = $('sv-sens').disabled = !s.modele;
  if (document.activeElement !== $('sv-sens')) $('sv-sens').value = s.sensibilite;
  $('sv-sens-v').textContent = ({ 0.5: 'basse', 1: 'normale', 2: 'haute' })[s.sensibilite] || `× ${s.sensibilite}`;
  const dl = s.telechargement;
  if (dl.state === 'running') { $('sv-dl').disabled = true; $('sv-dl').innerHTML = `<span class="spin"></span>${dl.total ? Math.round(100 * dl.done / dl.total) : 0} %`; }
  else { $('sv-dl').disabled = false; $('sv-dl').innerHTML = '<svg class="i"><use href="#i-download"/></svg>Installer l\'IA'; if (dl.state === 'error') toast(dl.error, 'bad'); }
  const L = s.live, on = s.modele && s.ia;
  const [cls, txt] = !on ? ['', 'IA désactivée'] : !L?.en_cours ? ['ok', 'Prête'] : L.etat === 'pause' ? ['busy', 'Pause par l\'IA'] : L.etat === 'suspect' ? ['busy', 'Suspect'] : ['ok', 'Tout va bien'];
  $('sv-pill').className = 'pill ' + cls; $('sv-pill-t').textContent = txt;
  const h = L?.history || [];
  $('sv-spark').innerHTML = h.length > 1 ? `<line x1="0" x2="120" y1="${24 - 24 * 0.78 / 2}" y2="${24 - 24 * 0.78 / 2}"/><path d="${h.map((v, i) => `${i ? 'L' : 'M'}${(120 * i / (h.length - 1)).toFixed(1)},${(24 - 24 * Math.min(v, 2) / 2).toFixed(1)}`).join('')}"/>` : '';
  $('sv-note').textContent = !on ? '' : L?.en_cours ? (L.frames < 30 ? `Analyse en cours : ${L.frames} image${L.frames > 1 ? 's' : ''} (l'IA juge à partir de 30, soit 5 minutes).` : `${L.frames} images analysées, une toutes les 10 s.`) : 'L\'IA regardera la caméra pendant la prochaine impression.';
  if (pvOpen) svTimer = setTimeout(svLoad, dl.state === 'running' ? 1500 : 10000);
}
const svSave = async body => { try { await api('/surveillance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); svLoad(); } catch (e) { toast(e.message, 'bad'); } };
$('sv-ia').onchange = () => svSave({ ia: $('sv-ia').checked });
$('sv-pause').onchange = () => svSave({ pause_auto: $('sv-pause').checked });
$('sv-tl').onchange = () => svSave({ timelapse: $('sv-tl').checked });
$('sv-sens').onchange = () => svSave({ sensibilite: +$('sv-sens').value });
$('sv-dl').onclick = async () => { await api('/surveillance/modele', { method: 'POST' }).catch(e => toast(e.message, 'bad')); svLoad(); };


export { closeCamera, lastSt, mcLoad, mtLoad, mtRender, openCamera, openPrinter, pollPrinter, pvCanvas, pvFiles, pvOpen, pvStatus, pvTimer, stockData, svLoad, svSave, svTimer, trayEdit, traySave };

/* print queue: shown when something waits; the next print starts by hand once the bed is cleared */
let queue = [], queueBusy = true;
async function loadQueue() { queue = await api('/queue').catch(() => queue); renderQueue(); }
function queueState(busy) { if (busy !== queueBusy) { queueBusy = busy; loadQueue(); } }
function renderQueue() {
  $('pv-queue').hidden = !queue.length;
  $('q-n').textContent = queue.length ? `${queue.length} en attente` : '';
  $('q-next').hidden = queueBusy;
  $('q-hint').textContent = queueBusy ? 'La suivante se lance quand l\'impression en cours est finie et le plateau vidé.' : 'Retire la pièce et nettoie le plateau avant de lancer.';
  $('q-list').innerHTML = queue.map((n, i) => `<div class="q-row"><span class="q-i">${i + 1}</span><span class="q-n" title="${esc(n)}">${esc(n)}</span>
    <button class="btn ghost" data-qmove="${i}" data-to="${i - 1}" ${i ? '' : 'disabled'} aria-label="Monter">↑</button>
    <button class="btn ghost" data-qmove="${i}" data-to="${i + 1}" ${i < queue.length - 1 ? '' : 'disabled'} aria-label="Descendre">↓</button>
    <button class="btn ghost" data-qdel="${i}" aria-label="Retirer de la file"><svg class="i"><use href="#i-x"/></svg></button></div>`).join('');
  const json = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  $('q-list').querySelectorAll('[data-qmove]').forEach(b => b.onclick = () => api('/queue/move', json({ index: +b.dataset.qmove, to: +b.dataset.to })).then(q => { queue = q; renderQueue(); }).catch(e => toast(e.message, 'bad')));
  $('q-list').querySelectorAll('[data-qdel]').forEach(b => b.onclick = () => api('/queue/' + b.dataset.qdel, { method: 'DELETE' }).then(q => { queue = q; renderQueue(); }).catch(e => toast(e.message, 'bad')));
}
$('q-next').onclick = () => {
  const name = queue[0]; if (!name) return;
  launchFile(name, { upload: true, button: $('q-next'),
    onStarted: () => api('/queue/0', { method: 'DELETE' }).then(q => { queue = q; renderQueue(); }) });
};
loadQueue();

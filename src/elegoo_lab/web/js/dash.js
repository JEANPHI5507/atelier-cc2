import * as THREE from 'three';
import { GLTFLoader } from '../vendor/addons/GLTFLoader.js';
import { BUSY, api, ctl, nice, toast } from './core.js';

/* Tableau de bord live : toutes les données viennent du serveur (/status, /canvas, /lab/api/*).
   Aucun chiffre en dur : si l'imprimante est injoignable, on l'affiche. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const get = async p => {
  const r = await fetch(p);
  if (r.status === 401) { location.href = '/lab/login.html'; throw new Error('Code d\'accès requis'); }
  return r.json();
};
/* ---- état ---- */
const PAUSED = new Set([5, 6]);                                  // PAUSING / PAUSED (pycentauri)
let lastStatus = null;

const fmtT = t => (t == null ? '–' : Math.round(t) + '°');
const pct = (a, b) => (!b ? 0 : Math.max(0, Math.min(100, Math.round(100 * a / b))));

async function refresh() {
  let st = null;
  try { st = await get('/status'); } catch { st = null; }
  lastStatus = st;

  const [bob, queue, surv, events, attrs] = await Promise.allSettled([
    api('/bobines'), api('/queue'), api('/surveillance'), api('/events'), get('/attributes'),
  ]);
  const canvas = await get('/canvas').catch(() => null);

  /* carte imprimante (sidebar) */
  const name = attrs.status === 'fulfilled' ? (attrs.value.machine_name || 'Centauri Carbon 2') : 'Centauri Carbon 2';
  const host = $('#side-host');
  if (host) {
    if (!st) host.textContent = 'Imprimante injoignable';
    else if (BUSY.has(st.print_status)) host.textContent = 'Impression en cours';
    else host.textContent = 'Prête · au repos';
  }
  const brand = document.querySelector('.side-card b'); if (brand) brand.textContent = name;
  document.querySelector('.side-card .led')?.classList.toggle('off', !st);

  /* en-tête : progression (à 0 quand la machine est au repos) */
  const file = st && st.filename && st.filename !== '-' ? st.filename : null;
  const busy = st && BUSY.has(st.print_status);
  const prog = st && (busy || file) ? Math.round(st.progress || 0) : 0;
  loadModelFor(file);
  if ($('#hello-pct')) $('#hello-pct').textContent = prog + ' %';
  if ($('#hello-name')) $('#hello-name').textContent = file ? nice(file) : 'aucune impression'; $('#hello-name').title = file || '';
  if ($('#hello-eta')) {
    const lc = st && st.layer && st.layer.total ? `couche ${st.layer.current ?? '?'} / ${st.layer.total}` : (busy ? 'en cours' : 'au repos');
    $('#hello-eta').textContent = lc;
  }
  if ($('#ring-txt')) $('#ring-txt').textContent = prog + '%';
  if ($('#ring-fg')) $('#ring-fg').style.strokeDashoffset = String(100 - prog);

  /* KPI buse / plateau */
  if ($('#t-noz')) {
    const n = st?.temperatures?.nozzle;
    $('#t-noz').textContent = fmtT(n?.actual);
    $('#t-noz-t').textContent = '/' + fmtT(n?.target);
    $('#b-noz').style.width = pct(n?.actual, n?.target) + '%';
  }
  if ($('#t-bed')) {
    const b = st?.temperatures?.bed;
    $('#t-bed').textContent = fmtT(b?.actual);
    $('#t-bed-t').textContent = '/' + fmtT(b?.target);
    $('#b-bed').style.width = pct(b?.actual, b?.target) + '%';
  }

  /* KPI CANVAS : vraies bobines (couleur lue + stock atelier) */
  const trays = canvas?.canvas_info?.canvas_list?.[0]?.tray_list || [];
  const stock = bob.status === 'fulfilled' ? bob.value.trays || [] : [];
  const spoolEls = $$('.spool');
  spoolEls.forEach((el, i) => {
    const t = trays.find(x => x.tray_id === i || x.tray === i) || trays[i] || {};
    const k = stock.find(x => x.tray === i) || {};
    const col = /^#[0-9A-Fa-f]{6}$/.test(String(t.filament_color || t.color || '')) ? (t.filament_color || t.color) : '#888';
    const on = t.status === 1 || t.status === 2 || t.status === '1' || t.status === '2';
    const fill = el.querySelector('.fill');
    if (fill) { fill.setAttribute('fill', on ? col : '#888'); fill.style.opacity = on && k.poids_g ? String(Math.max(0.08, k.restant_g / k.poids_g)) : 0.12; }
    const rim = el.querySelector('.rim'); if (rim) rim.classList.toggle('empty', !on);
    const p = on && k.poids_g ? Math.round(100 * k.restant_g / k.poids_g) : 0;
    const lab = el.querySelector('small'); if (lab) lab.textContent = on ? p + '%' : 'vide';
    el.dataset.msg = `Bobine ${i + 1} — ${k.nom || t.filament_name || t.filament_type || 'inconnue'}${on ? `, ~${Math.round(k.restant_g || 0)} g restants` : ', absente'}`;
    el.onclick = () => toast(el.dataset.msg);
  });

  /* KPI file d'attente */
  const q = queue.status === 'fulfilled' ? queue.value : [];
  if ($('#q-count')) $('#q-count').textContent = String(q.length);
  if ($('#dq-next')) $('#dq-next').textContent = q.length ? `Prochaine : « ${q[0]} »` : 'File vide';

  /* file d'impression (liste) */
  const ql = $('#qlist');
  if (ql) {
    ql.innerHTML = '';
    if (file) {
      const li = document.createElement('li');
      li.className = 'on';
      li.innerHTML = `<span class="st run"></span><div><b></b><small>En cours · ${prog} %</small></div><div class="bar slim"><i style="width:${prog}%"></i></div>`;
      li.querySelector('b').textContent = nice(file);
      ql.appendChild(li);
    }
    q.slice(0, 4).forEach(n => {
      const li = document.createElement('li');
      li.innerHTML = `<span class="st wait"></span><div><b></b><small>En attente</small></div>`;
      li.querySelector('b').textContent = n;
      ql.appendChild(li);
    });
    if (!ql.children.length) ql.innerHTML = '<li><span class="st wait"></span><div><b>Aucune impression en file</b></div></li>';
  }

  /* caméra live + IA */
  const cam = $('#cam-img');
  if (cam && !document.hidden) cam.src = '/lab/api/camera?t=' + Date.now();
  if ($('#ia-pill')) {
    const s = surv.status === 'fulfilled' ? surv.value : null;
    const live = s?.live || {};
    const on = s?.modele && live.en_cours;
    const etat = live.etat || 'ok';
    $('#ia-pill').textContent = !s?.modele ? 'IA : modèle absent' : on ? `IA active · ${etat}` : 'IA prête';
    $('#ia-pill').className = 'pill ' + (etat === 'suspect' ? 'warn' : 'ok');
  }

  /* activité récente : vrais événements */
  if ($('#flist')) {
    const ev = events.status === 'fulfilled' ? (Array.isArray(events.value) ? events.value : events.value.evenements || []) : [];
    const list = ev.slice(-4).reverse();
    $('#flist').innerHTML = '';
    list.forEach(e => {
      const li = document.createElement('li');
      const icon = e.level === 'warn' || e.level === 'bad' ? 'i-warn' : e.kind === 'debut' ? 'i-bolt' : 'i-check';
      const cls = e.level === 'warn' || e.level === 'bad' ? 'warn-i' : icon === 'i-check' ? 'ok-i' : 'acc';
      const when = e.t ? new Date(e.t * 1000).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
      li.innerHTML = `<svg class="i ${cls}"><use href="#${icon}"/></svg><div><b></b> — <span></span><small>${when}</small></div>`;
      li.querySelector('b').textContent = e.title || e.kind || 'Événement';
      li.querySelector('span').textContent = (e.detail || '').slice(0, 60);
      $('#flist').appendChild(li);
    });
  }

  /* bouton pause / reprendre / arrêter */
  const bp = $('#q-pause');
  if (bp && st) {
    const paused = PAUSED.has(st.print_status);
    bp.title = paused ? 'Reprendre' : 'Mettre en pause';
    bp.onclick = async () => {
      try {
        await ctl(paused ? '/print/resume' : '/print/pause');
        toast(paused ? 'Impression reprise' : 'Impression mise en pause', 'ok');
      } catch (e) { toast(e.message, 'bad'); }
    };
  }
  const bs = $('#q-stop');
  if (bs) bs.onclick = async () => {
    if (!confirm('Arrêter l\'impression en cours ?')) return;
    try { await ctl('/print/stop'); toast('Impression arrêtée', 'ok'); }
    catch (e) { toast(e.message, 'bad'); }
  };
}

export function startDash() {   // le premier rafraîchissement vient du clic sur l'onglet (pas de requêtes inutiles ailleurs)
  setInterval(() => { if (!document.hidden && !document.getElementById('dash').hidden) refresh(); }, 2500);
  init3d();
}
export const refreshDash = () => refresh();

/* ---- vue 3D réelle : le modèle associé à l'impression en cours ---- */
let renderer, scene, camera, model, spinning = true, loadedFor = null;
function init3d() {
  const el = $('#view3d'); if (!el || renderer) return;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 4000);
  scene.add(new THREE.AmbientLight(0xffffff, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(150, 260, 120); scene.add(key);
  const plate = new THREE.Mesh(new THREE.BoxGeometry(256, 4, 256), new THREE.MeshStandardMaterial({ color: 0x23262c, roughness: .85 }));
  plate.position.y = -2; scene.add(plate);
  const grid = new THREE.GridHelper(256, 16, 0x4a505c, 0x31353d); grid.position.y = 0.02; scene.add(grid);
  const fit = () => { const r = el.getBoundingClientRect(); if (!r.width) return; renderer.setSize(r.width, r.height, false); camera.aspect = r.width / r.height; camera.updateProjectionMatrix(); };
  fit(); new ResizeObserver(fit).observe(el);
  const loop = () => { requestAnimationFrame(loop); if (spinning && model) model.rotation.y += 0.008; renderer.render(scene, camera); };
  loop();
  $('#v-rot').onclick = () => { spinning = !spinning; toast(spinning ? 'Rotation auto' : 'Rotation arrêtée', 'ok'); };
  $('#v-fit').onclick = () => fitCam();
}
function fitCam() {   // cadre le modèle ET le plateau, même dans un cadre étroit (téléphone en portrait)
  if (!model || !camera) return;
  const b = new THREE.Box3().setFromObject(model), c = b.getCenter(new THREE.Vector3());
  const s = Math.max(b.getSize(new THREE.Vector3()).length(), 230) / Math.min(1, camera.aspect || 1);
  camera.position.set(c.x + s * .9, c.y + s * .65, c.z + s * 1.05);
  camera.lookAt(c.x, c.y * .6, c.z);
}
const failed = new Set();   // modèles dont l'aperçu a échoué : on n'insiste pas
let loadKey = null;
const showThumb = url => {
  let im = $('#dthumb');
  if (!im) { im = document.createElement('img'); im.id = 'dthumb'; im.alt = 'Vignette de l\'impression'; $('#dplate').prepend(im); }
  im.hidden = !url; if (url) im.src = url;
  if (renderer) renderer.domElement.style.visibility = url ? 'hidden' : 'visible';
};
async function show3d(m) {
  const g = await new GLTFLoader().loadAsync('/lab/api/models/' + encodeURIComponent(m) + '/preview.glb?v=' + Date.now());
  if (model) scene.remove(model);
  const mesh = g.scene;
  const b = new THREE.Box3().setFromObject(mesh), c = b.getCenter(new THREE.Vector3()), sz = b.getSize(new THREE.Vector3());
  const k = 190 / Math.max(sz.x, sz.y, sz.z, 1);
  mesh.scale.setScalar(k);
  mesh.position.set(-c.x * k, -b.min.y * k, -c.z * k);   // pièce centrée sur le plateau, posée dessus
  model = new THREE.Group(); model.add(mesh);            // le pivot est au centre : la pièce tourne SUR PLACE
  scene.add(model); fitCam(); showThumb(null);
}
/* Ce qui s'imprime vraiment : le modèle source du G-code en cours (sinon sa vignette). Jamais un autre modèle. */
async function loadModelFor(file) {
  if (!scene || loadKey === (file || '')) return;   // inutile de relister la bibliothèque à chaque rafraîchissement
  loadKey = file || '';
  const tag = $('#plate-tag');
  try {
    const models = (await api('/models')) || [];
    if (file) {
      const entry = models.find(x => x.name === file);
      const stem = file.replace(/\.gcode$/i, '');
      const guess = models.map(x => x.name).filter(n => n && !/\.gcode$/i.test(n) && stem.startsWith(n.replace(/\.[^.]+$/, ''))).sort((a, b) => b.length - a.length)[0];
      const src = entry?.source || guess;
      if (src && !failed.has(src)) {
        try { await show3d(src); if (tag) tag.textContent = nice(file) + ' · en cours'; return; } catch { failed.add(src); }
      }
      if (entry || src) {   // pas de 3D possible : la vignette embarquée dans le G-code montre la vraie impression
        showThumb('/lab/api/models/' + encodeURIComponent(entry ? file : src) + '/thumb.png');
        if (tag) tag.textContent = nice(file) + ' · en cours';
        return;
      }
      if (tag) tag.textContent = nice(file) + ' · aperçu indisponible';
      showThumb(null); return;
    }
    // au repos : le modèle le plus récent de la bibliothèque
    showThumb(null);
    const byDate = models.filter(x => x.mtime && !/\.gcode$/i.test(x.name)).sort((a, b) => b.mtime - a.mtime).map(x => x.name);
    for (const m of byDate.filter(n => !failed.has(n)).slice(0, 3)) {
      try { await show3d(m); if (tag) tag.textContent = nice(m) + ' · dernier modèle'; return; } catch { failed.add(m); }
    }
    if (tag) tag.textContent = 'CC2 · plateau 256 × 256';
  } catch { if (tag) tag.textContent = 'Aperçu 3D indisponible'; loadKey = null; }
}

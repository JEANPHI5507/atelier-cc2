import { $, nice, api, ctx, dur, esc, euro, evTime, fmtG, toast } from './core.js';
import { buildPaths, grid, launchFile, miniViewer, upload } from './lab.js';

/* gallery */
const ISSUE = { terminee: ['ok', 'Terminée'], arretee: ['warn', 'Arrêtée'], erreur: ['bad', 'Erreur'], interrompue: ['', 'Suivi interrompu'], 'en cours': ['', 'En cours'] };
const galUrl = (e, n) => `/lab/api/galerie/${encodeURIComponent(e.id)}/${encodeURIComponent(n)}`;
async function loadGallery() {
  const list = await api('/galerie').catch(() => []);
  const done = list.filter(e => e.issue === 'terminee'), g = list.reduce((a, e) => a + (e.g || 0), 0), eur = list.reduce((a, e) => a + (e.eur || 0), 0);
  $('gal-sum').textContent = list.length ? `${list.length} impression${list.length > 1 ? 's' : ''} · ${done.length} réussie${done.length > 1 ? 's' : ''} · ${fmtG(g)} · ${euro(eur)}` : '';
  $('gal-list').innerHTML = list.length ? list.map((e, i) => { const [lvl, lab] = ISSUE[e.issue] || ['', e.issue];
    return `<div class="gcard"><button class="gthumb" data-gview="${i}" aria-label="Voir">${e.issue === 'en cours' ? `<img alt="Caméra en direct" src="/snapshot?ts=${Date.now()}" onerror="this.remove()">` : e.photo ? `<img loading="lazy" alt="" src="${galUrl(e, e.photo)}">` : ''}
      ${e.video ? '<span class="play"><span><svg class="i"><use href="#i-play"/></svg></span></span>' : ''}<span class="chip ${lvl}">${lab}${e.issue !== 'terminee' && e.progression != null ? ' · ' + e.progression + ' %' : ''}</span></button>
      <div class="gbody"><div class="t" title="${esc(e.fichier)}">${esc(nice(e.fichier))}</div>
      <div class="m">${evTime(e.debut)}${e.duree_s ? ' · ' + dur(e.duree_s) : ''}${e.g ? ' · ' + fmtG(e.g) + ' · ' + euro(e.eur) : ''}</div>
      ${e.bilan ? `<div class="m" style="color:${e.bilan.issues?.length ? 'var(--warn)' : 'var(--ok)'}">${e.bilan.issues?.length ? 'Bilan : ' + esc((e.bilan.titres || e.bilan.issues).join(', ').toLowerCase()) : '✓ Bilan : réussie'}${e.bilan.notes?.global !== undefined ? ' · ' + e.bilan.notes.global + ' / 5' : ''}</div>` : ''}
      ${e.alertes?.length ? `<div class="m" style="color:var(--warn)">⚠ ${e.alertes.length} alerte${e.alertes.length > 1 ? 's' : ''} de l'IA</div>` : ''}</div>
      <div class="gacts">${e.issue === 'en cours' ? '<span class="note" style="margin:0;align-self:center">Vidéo prête à la fin de l\'impression</span>' : ''}${e.dans_bibliotheque && e.issue !== 'en cours' ? `<button class="btn" data-greprint="${esc(e.fichier)}" ${ctx.control ? '' : 'disabled'}><svg class="i"><use href="#i-play"/></svg>Réimprimer</button>` : ''}
      ${e.video ? `<a class="btn ghost" href="${galUrl(e, e.video)}" download title="Télécharger la vidéo"><svg class="i"><use href="#i-download"/></svg></a>` : ''}
      ${e.issue !== 'en cours' ? `<button class="btn" data-gbilan="${i}">${e.bilan ? '✓ Bilan' : 'Bilan'}</button>` : ''}
      <button class="btn ghost" data-gdel="${esc(e.id)}" title="Supprimer"><svg class="i"><use href="#i-trash"/></svg></button></div></div>`; }).join('')
    : '<div class="empty" style="grid-column:1/-1">Aucune impression pour l\'instant. Chaque impression lancée apparaîtra ici avec sa vidéo en accéléré, sa photo et son coût.</div>';
  $('gal-list').querySelectorAll('[data-gview]').forEach(b => b.onclick = () => {
    const e = list[+b.dataset.gview];
    if (e.issue === 'en cours') { $('t-ui').click(); return; }   // live: the printer tab has the camera
    $('vid-t').textContent = e.fichier;
    const v = $('vid-v'); v.hidden = !e.video; if (e.video) v.src = galUrl(e, e.video); else v.removeAttribute('src');
    $('vid-img').innerHTML = (!e.video && e.photo ? `<img alt="" style="display:block;width:100%" src="${galUrl(e, e.photo)}">` : '')
      + (e.alertes || []).map(a => `<div style="padding:12px 16px;border-top:1px solid var(--line)"><b style="color:var(--warn)">Alerte de l'IA · ${evTime(a.t)}</b><img alt="" style="display:block;width:100%;margin-top:8px;border-radius:8px" src="${galUrl(e, a.photo)}"></div>`).join('');
    $('vid').showModal();
  });
  $('gal-list').querySelectorAll('[data-gdel]').forEach(b => b.onclick = async () => {
    if (!confirm('Supprimer cette impression de la galerie (vidéo et photos) ?')) return;
    await api('/galerie/' + encodeURIComponent(b.dataset.gdel), { method: 'DELETE' }).catch(e => toast(e.message, 'bad')); loadGallery();
  });
  $('gal-list').querySelectorAll('[data-greprint]').forEach(b => b.onclick = () => sendAndStart(b.dataset.greprint, b));
  $('gal-list').querySelectorAll('[data-gbilan]').forEach(b => b.onclick = () => openBilan(list[+b.dataset.gbilan]));
}
$('vid').addEventListener('close', () => { $('vid-v').pause(); });
/* after a print: what to do now, what went wrong, the correction kept for next time */
async function openBilanById(id) {   // from a phone notification or a link: the print's review, straight away
  const e = (await api('/galerie').catch(() => [])).find(x => x.id === id);
  if (!e) return toast('Impression introuvable dans la galerie', 'bad');
  $('t-gal').click(); openBilan(e);
}
/* the print in 3D, as in the printer tab's layer view: the part pale, the supports in orange.
   Without WebGL or without the G-code in the library: the top view drawn from the server's grid */
let blView = null, blSeq = 0;
async function supportsView(e, carte) {
  const seq = ++blSeq, box = $('bl-3d-box');
  box.hidden = true; drawSupportMap(null);
  if (!carte) return;
  blView = blView || (e.dans_bibliotheque ? miniViewer('bl-3d', 'bilan') : null);
  if (!blView || !e.dans_bibliotheque) return drawSupportMap(carte);
  box.hidden = false; $('bl-3d-note').textContent = 'Lecture du G-code…'; blView.set(null);
  let p;
  try { p = await api(`/models/${encodeURIComponent(e.fichier)}/paths?leger=1200000`); } catch { p = null; }
  if (seq !== blSeq) return;
  if (!p) { box.hidden = true; return drawSupportMap(carte); }
  const { group, parts } = buildPaths(p);
  parts[0].lines.material.transparent = true; parts[0].lines.material.opacity = .28;   // the part fades, the supports stand out
  parts[2].lines.visible = false;                                                       // no wipe tower: it is not on the part
  blView.set(group, true);
  blView.c.position.lerp(blView.ctl.target, .2);   // closer than the generic fit, as in the printer tab: lines need it
  $('bl-3d-note').textContent = "En orange : les supports à retirer. En clair : la pièce. Tourne avec un doigt, zoome en pinçant.";
}
/* top view: the part in grey, the supports in the accent colour; y up is the back of the printer */
function drawSupportMap(m) {
  const box = $('bl-map');
  box.hidden = !m;
  if (!m) { box.innerHTML = ''; return; }
  const c = m.cell, all = m.part.concat(m.supports);
  const x0 = Math.min(...all.map(p => p[0])), x1 = Math.max(...all.map(p => p[0])) + c;
  const y0 = Math.min(...all.map(p => p[1])), y1 = Math.max(...all.map(p => p[1])) + c;
  const rect = (p, cls) => `<rect class="${cls}" x="${p[0] - x0}" y="${y1 - p[1] - c}" width="${c}" height="${c}"/>`;
  const w = x1 - x0, h = y1 - y0, fs = Math.max(w, h) / 22;   // labels sized to the drawing, whatever the part's size
  box.innerHTML = `<svg viewBox="${-fs * 4} ${-fs * 2} ${w + fs * 8} ${h + fs * 4}" style="font-size:${fs}px" role="img" aria-label="Plan vu de dessus : la pièce en gris, les supports en orange">`
    + m.part.map(p => rect(p, 'mp')).join('') + m.supports.map(p => rect(p, 'ms')).join('')
    + `<text x="${w / 2}" y="${-fs * 0.5}" text-anchor="middle">Arrière</text><text x="${w / 2}" y="${h + fs * 1.4}" text-anchor="middle">Avant</text>`
    + `<text x="${-fs * 0.5}" y="${h / 2}" text-anchor="end">Gauche</text><text x="${w + fs * 0.5}" y="${h / 2}">Droite</text></svg>`
    + '<p class="note">Vu de dessus, devant l\'imprimante. Gris : la pièce. Orange : là où étaient les supports.</p>';
}
async function openBilan(e) {
  const d = await api(`/bilan/${encodeURIComponent(e.id)}`).catch(err => { toast(err.message, 'bad'); return null; });
  if (!d) return;
  const picked = new Set(d.bilan?.issues || []);
  $('bl-t').textContent = nice(e.fichier); $('bl-note').value = d.bilan?.note || '';
  $('bl-tips').innerHTML = d.tips.map(t => `<li>${esc(t)}</li>`).join('');
  supportsView(e, d.carte);
  const marks = { ...(d.bilan?.notes || {}) };
  const rate = () => {
    $('bl-rate').innerHTML = d.questions.map(q => `<div class="rate-row" role="radiogroup" aria-label="${esc(q.title)}"><span>${esc(q.title)}</span><span class="rate-n">`
      + [0, 1, 2, 3, 4, 5].map(n => `<button type="button" role="radio" class="${marks[q.key] === n ? 'on' : ''}" aria-checked="${marks[q.key] === n}" data-q="${q.key}" data-n="${n}">${n}</button>`).join('') + '</span></div>').join('');
    $('bl-rate').querySelectorAll('[data-q]').forEach(b => b.onclick = () => {
      const q = d.questions.find(x => x.key === b.dataset.q), n = +b.dataset.n;
      marks[q.key] = n;
      if (n <= 2 && q.issue) picked.add(q.issue);   // a low mark ticks the matching defect, so its correction is offered
      rate(); draw();
    });
  };
  const draw = () => {
    $('bl-issues').innerHTML = d.issues.map(x => `<button class="chip-btn ${picked.has(x.key) ? 'on' : ''}" data-is="${x.key}" aria-pressed="${picked.has(x.key)}">${esc(x.title)}</button>`).join('');
    $('bl-issues').querySelectorAll('[data-is]').forEach(b => b.onclick = () => { picked.has(b.dataset.is) ? picked.delete(b.dataset.is) : picked.add(b.dataset.is); draw(); });
    $('bl-why').innerHTML = d.issues.filter(x => picked.has(x.key)).map(x => `<div class="opt-step"><span>→</span><div><b>${esc(x.title)}</b><p>${esc(x.cause)} ${esc(x.todo)}</p></div></div>`).join('');
  };
  rate(); draw();
  $('bl-go').onclick = async () => {
    try {
      const r = await api(`/bilan/${encodeURIComponent(e.id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issues: [...picked], note: $('bl-note').value, notes: marks }) });
      $('bilan').close();
      toast(r.source && r.issues.length ? `Corrections gardées : elles seront proposées la prochaine fois que tu prépares ${nice(r.source)}.` : 'Bilan enregistré.', 'ok');
      loadGallery();
    } catch (err) { toast(err.message, 'bad'); }
  };
  $('bilan').showModal();
}
async function sendAndStart(name, b) { return launchFile(name, { upload: true, button: b }); }


export { ISSUE, galUrl, loadGallery, openBilan, openBilanById, sendAndStart };

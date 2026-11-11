import { $, nice, api, ctx, dur, esc, euro, evTime, fmtG, toast } from './core.js';
import { grid, launchFile, upload } from './lab.js';

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
      ${e.bilan ? `<div class="m" style="color:${e.bilan.issues?.length ? 'var(--warn)' : 'var(--ok)'}">${e.bilan.issues?.length ? 'Bilan : ' + esc((e.bilan.titres || e.bilan.issues).join(', ').toLowerCase()) : '✓ Bilan : réussie'}</div>` : ''}
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
async function openBilan(e) {
  const d = await api(`/bilan/${encodeURIComponent(e.id)}`).catch(err => { toast(err.message, 'bad'); return null; });
  if (!d) return;
  const picked = new Set(d.bilan?.issues || []);
  $('bl-t').textContent = nice(e.fichier); $('bl-note').value = d.bilan?.note || '';
  $('bl-tips').innerHTML = d.tips.map(t => `<li>${esc(t)}</li>`).join('');
  const draw = () => {
    $('bl-issues').innerHTML = d.issues.map(x => `<button class="chip-btn ${picked.has(x.key) ? 'on' : ''}" data-is="${x.key}" aria-pressed="${picked.has(x.key)}">${esc(x.title)}</button>`).join('');
    $('bl-issues').querySelectorAll('[data-is]').forEach(b => b.onclick = () => { picked.has(b.dataset.is) ? picked.delete(b.dataset.is) : picked.add(b.dataset.is); draw(); });
    $('bl-why').innerHTML = d.issues.filter(x => picked.has(x.key)).map(x => `<div class="opt-step"><span>→</span><div><b>${esc(x.title)}</b><p>${esc(x.cause)} ${esc(x.todo)}</p></div></div>`).join('');
  };
  draw();
  $('bl-go').onclick = async () => {
    try {
      const r = await api(`/bilan/${encodeURIComponent(e.id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issues: [...picked], note: $('bl-note').value }) });
      $('bilan').close();
      toast(r.source && r.issues.length ? `Corrections gardées : elles seront proposées la prochaine fois que tu prépares ${nice(r.source)}.` : 'Bilan enregistré.', 'ok');
      loadGallery();
    } catch (err) { toast(err.message, 'bad'); }
  };
  $('bilan').showModal();
}
async function sendAndStart(name, b) { return launchFile(name, { upload: true, button: b }); }


export { ISSUE, galUrl, loadGallery, openBilan, openBilanById, sendAndStart };

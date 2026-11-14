import { $, api, esc, evTime, nice, toast } from './core.js';
import { loadGallery, openBilanById } from './gallery.js';
import { info } from './lab.js';
import { termPush } from './printer.js';

/* follow-up and alerts */
let evUnread = 0, evSound = true;
try { evSound = localStorage.getItem('cc2-sound') !== '0'; } catch {}
const evRow = e => `<div class="ev ${esc(e.level)}"><span class="dot"></span><div><b>${esc(e.title)}</b><div class="d">${esc((e.detail || '').replace(/\S+?\.gcode\b/gi, nice))}</div>${e.photo ? `<img loading="lazy" alt="Photo de fin d'impression" src="/lab/api/photos/${encodeURIComponent(e.photo)}">` : ''}</div><time>${evTime(e.t)}</time></div>`;
function evBadge() { $('ev-badge').hidden = !evUnread; $('ev-badge').textContent = evUnread > 9 ? '9+' : evUnread; }
function beep(level) {
  if (!evSound) return;
  try {
    const a = new (window.AudioContext || window.webkitAudioContext)(), notes = level === 'ok' ? [660, 880] : level === 'bad' ? [440, 330, 440] : [550];
    notes.forEach((f, i) => { const o = a.createOscillator(), g = a.createGain(); o.frequency.value = f; o.connect(g); g.connect(a.destination);
      const t = a.currentTime + i * 0.18; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.2, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16); o.start(t); o.stop(t + 0.17); });
  } catch {}
  navigator.vibrate?.(level === 'bad' ? [200, 100, 200, 100, 200] : [150]);
}
function startAlerts() {
  const es = new EventSource('/lab/api/events/stream');
  es.addEventListener('ligne', m => termPush(JSON.parse(m.data)));
  es.addEventListener('alerte', m => {
    const e = JSON.parse(m.data);
    if (e.update) { if ($('ev').open) evLoad(); if (!$('gal').hidden) loadGallery(); return; }  // photo / gallery entry added
    const t = document.createElement('div'); t.className = 'toast ' + (e.level === 'info' ? '' : e.level);
    t.innerHTML = `<b>${esc(e.title)}</b>${esc((e.detail || '').replace(/\S+?\.gcode\b/gi, nice))}`; $('toasts').append(t);
    if (e.bilan) {   // a finished print: its review is one tap away, and the message stays until it is used or closed
      const b = document.createElement('button'); b.className = 'btn primary'; b.textContent = 'Faire le bilan';
      b.onclick = () => { t.remove(); openBilanById(e.bilan); }; t.append(b);
      const x = document.createElement('button'); x.className = 'btn ghost'; x.textContent = 'Plus tard'; x.onclick = () => t.remove(); t.append(x);
    } else setTimeout(() => t.remove(), e.level === 'bad' ? 20000 : 8000);
    if (e.level !== 'info') beep(e.level);
    if (window.Notification?.permission === 'granted' && document.hidden) {
      const n = new Notification(e.title, { body: (e.detail || '').replace(/\S+?\.gcode\b/gi, nice), tag: 'cc2-' + e.kind });
      if (e.bilan) n.onclick = () => { window.focus(); openBilanById(e.bilan); };
    }
    evUnread++; evBadge(); if ($('ev').open) evLoad();
  });
}
async function evLoad() {
  const list = await api('/events').catch(() => []);
  $('ev-list').innerHTML = list.length ? list.map(evRow).join('') : '<div class="empty">Rien pour l\'instant. Lance une impression : chaque étape importante apparaîtra ici.</div>';
}
$('ev-open').onclick = () => {
  evUnread = 0; evBadge(); $('ev-sound').checked = evSound;
  $('ev-notif').hidden = !(window.isSecureContext && window.Notification && Notification.permission === 'default');
  evLoad(); phoneLoad(); $('ev').showModal();
};
$('ev-sound').onchange = () => { evSound = $('ev-sound').checked; try { localStorage.setItem('cc2-sound', evSound ? '1' : '0'); } catch {} if (evSound) beep('info'); };
$('ev-notif').onclick = async () => { await Notification.requestPermission(); $('ev-notif').hidden = true; };


export { beep, evBadge, evLoad, evRow, evSound, evUnread, startAlerts };

/* alerts on the phone with the app closed: the free ntfy app, on a private topic made here */
async function phoneLoad() {
  const { ntfy } = await api('/alertes/telephone').catch(() => ({}));
  const topic = ntfy && ntfy.split('/').pop();
  $('ev-phone').innerHTML = topic
    ? `<b>Alertes sur le téléphone : activées</b>
       <p class="note">Dans l'appli <a href="https://ntfy.sh/app" target="_blank" rel="noopener">ntfy</a> (gratuite), abonne-toi au sujet
       <code id="ev-topic">${esc(topic)}</code>. Erreurs, fin et plus de filament arrivent même appli fermée.
       Garde ce sujet pour toi : qui le connaît lit tes alertes.</p>
       <div class="row-btns" style="margin-top:8px"><a class="btn primary" href="ntfy://ntfy.sh/${esc(topic)}">Ouvrir dans ntfy</a>
       <button class="btn" id="ev-ph-test">Envoyer un test</button><button class="btn ghost" id="ev-ph-off">Désactiver</button></div>`
    : `<b>Alertes sur le téléphone, appli fermée</b>
       <p class="note">Passe par le service ntfy.sh (gratuit) : les alertes quittent la maison, sans ton nom ni tes fichiers.</p>
       <button class="btn primary" id="ev-ph-on">Activer</button>`;
  const set = action => api('/alertes/telephone', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
  if ($('ev-ph-on')) $('ev-ph-on').onclick = () => set('on').then(phoneLoad).catch(e => toast(e.message, 'bad'));
  if ($('ev-ph-off')) $('ev-ph-off').onclick = () => set('off').then(phoneLoad).catch(e => toast(e.message, 'bad'));
  if ($('ev-ph-test')) $('ev-ph-test').onclick = () => set('test').then(() => toast('Test envoyé : regarde ton téléphone', 'ok')).catch(e => toast(e.message, 'bad'));
}

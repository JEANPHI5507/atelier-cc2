import { startAlerts } from './alerts.js';
import { $, BUSY, api, cfg, ctx, esc, toast } from './core.js';
import { loadGallery, openBilanById } from './gallery.js';
import { grid, loadFiles, phone, plateMat, renderAdvanced, renderUsages, setUsage } from './lab.js';
import { closeCamera, openPrinter, pollPrinter } from './printer.js';
import { openStart } from './setup.js';

/* theme */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelectorAll('[data-theme-pick]').forEach(b => b.classList.toggle('on', b.dataset.themePick === t));
  try { localStorage.setItem('cc2-theme', t); } catch {}
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());   // phone status bar
  if (plateMat) { const v = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim(); if (!plateMat.map) plateMat.color.set(v('--plate')); grid.material.color.set(v('--grid')); }   // the PEI plate keeps its own look
}
const THEMES = [...document.querySelectorAll('[data-theme-pick]')].map(b => b.dataset.themePick);
const narrow = () => matchMedia('(max-width: 600px)').matches;
// on a phone only the current swatch shows: tapping it moves to the next theme
document.querySelectorAll('[data-theme-pick]').forEach(b => b.onclick = () =>
  applyTheme(narrow() && b.classList.contains('on') ? THEMES[(THEMES.indexOf(b.dataset.themePick) + 1) % THEMES.length] : b.dataset.themePick));

/* tabs & dialogs */
for (const t of ['start', 'lab', 'ui', 'gal']) $('t-' + t).onclick = () => {
  $('lab').hidden = t !== 'lab'; $('pv').hidden = t !== 'ui'; $('start').hidden = t !== 'start'; $('gal').hidden = t !== 'gal';
  ['start', 'lab', 'ui', 'gal'].forEach(x => $('t-' + x).classList.toggle('on', x === t));
  if (t === 'start') openStart();
  if (t === 'gal') loadGallery();
  try { localStorage.setItem('cc2-tab', t); } catch {}
  if (t === 'ui') openPrinter(); else closeCamera();
};
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => b.closest('dialog').close());

/* boot */
if ('serviceWorker' in navigator && isSecureContext) navigator.serviceWorker.register('sw.js', { scope: '/lab/' }).catch(() => {});
let savedTheme = 'noir'; try { savedTheme = localStorage.getItem('cc2-theme') || 'noir'; } catch {}
applyTheme(savedTheme);
Object.assign(ctx, await api('/context'));
$('phone-open').hidden = !ctx.lan || !ctx.local;   // the guide is for the PC: on the phone it's already done
startAlerts();
$('phone-open').onclick = async () => {
  const ph = await api('/phone');
  $('phone-qr').innerHTML = ph.qr; $('phone-url').textContent = ph.url; $('board-url').textContent = ph.url.replace(/\/lab\/$/, '/lab/tableau.html');
  $('ph-ca').hidden = !ph.https; $('ph-n2').textContent = ph.https ? '2' : '1';
  $('ph-net').innerHTML = ph.tailscale
    ? `Avec l'appli <b>Tailscale</b> active sur le téléphone (même compte que ce PC), l'atelier marche partout : chez toi comme dehors. Déjà installée avec l'ancienne adresse ? Réinstalle-la avec celle-ci. Sans Tailscale, à la maison : <code>${esc(ph.local_url)}</code>`
    : 'Le téléphone doit être sur le même Wi-Fi que ce PC.';
  if (ph.https) { $('ph-ca-qr').innerHTML = ph.ca_qr; $('ph-ca-url').textContent = ph.ca_url; }
  $('phone').showModal();
};
document.querySelectorAll('#ph-os button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#ph-os button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('#phone .ph-os').forEach(p => p.hidden = !p.classList.contains(b.dataset.os));
});
if (/iPhone|iPad/.test(navigator.userAgent)) document.querySelector('#ph-os [data-os="ios"]').click();
else if (/CrOS/.test(navigator.userAgent)) document.querySelector('#ph-os [data-os="chromeos"]').click();
/* install button (Android / Chrome offer it once the app is installable) */
let installEv = null;
addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); installEv = e; $('install').hidden = false;
  if (matchMedia('(max-width: 860px)').matches) toast('Tu peux installer l\'atelier comme une appli : bouton orange en haut.');
});
addEventListener('appinstalled', () => { $('install').hidden = true; toast('Appli installée : retrouve « Atelier CC2 » sur l\'écran d\'accueil.', 'ok'); });
$('install').onclick = async () => { if (!installEv) return; installEv.prompt(); await installEv.userChoice; installEv = null; $('install').hidden = true; };
Object.assign(cfg, await api('/slicer').catch(() => ({ available: false })));
if (cfg.available) { $('quality').innerHTML = cfg.qualities.map(q => `<option ${q === cfg.default_quality ? 'selected' : ''}>${esc(q)}</option>`).join(''); renderAdvanced(); renderUsages(); setUsage('decoratif'); }
else { $('go').disabled = true; $('go').title = cfg.error || 'Slicer indisponible'; }
loadFiles(); pollPrinter();
// on a phone the printer comes first (and the first-day guide is for the PC)
try { let t = location.hash === '#imprimante' ? 'ui' : localStorage.getItem('cc2-tab'); if (narrow() && (!t || t === 'start')) t = 'ui'; if (t && t !== 'lab') $('t-' + t).click(); } catch {}

/* a link from the phone notification (ntfy « Faire le bilan ») opens that print's review */
function bilanFromHash() {   // also when the workshop is already open in that tab: only the hash changes
  const m = /^#bilan=(.+)$/.exec(location.hash);
  if (m) { history.replaceState(null, '', location.pathname); openBilanById(decodeURIComponent(m[1])); }
}
bilanFromHash(); addEventListener('hashchange', bilanFromHash);

/* phone: a print in progress opens straight on the follow-up view */
if (narrow()) fetch('/status').then(r => r.json()).then(s => { if (BUSY.has(s.print_status ?? 0) && $('pv').hidden) $('t-ui').click(); }).catch(() => {});

/* rarely used cards fold under their title (on a phone; the printer's files and history everywhere): tap the title */
document.querySelectorAll('#pv .card.o2, #pv .card.late').forEach(c => {
  c.classList.add('fold');
  c.querySelector('.card-h').addEventListener('click', e => {
    if (!(narrow() || c.classList.contains('fold-all')) || e.target.closest('a, button, input, label, select')) return;
    c.classList.toggle('open');
  });
});


export { applyTheme, installEv, savedTheme };


/* phone: the preparation panel shows purpose and height; the rest sits under "Plus d'options" */
['split', 'split-note', 'plate', 'rot', 'pauses', 'copies', 'quality', 'infill', 'supports', 'plate-row', 'adv', 'mode-box'].forEach(id => {
  const el = $(id); (el?.closest('.field, .switch, details') || el)?.classList.add('m-more');
});
$('orients')?.closest('.field')?.classList.add('m-more');
$('m-more').onclick = () => {
  const sect = $('m-more').closest('.sect'); sect.classList.toggle('m-open');
  $('m-more').textContent = sect.classList.contains('m-open') ? 'Moins d\'options' : 'Plus d\'options';
};

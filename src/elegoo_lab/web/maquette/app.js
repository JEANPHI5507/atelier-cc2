const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

$$('.nav-i').forEach(b => b.onclick = () => {
  $$('.nav-i').forEach(x => x.classList.toggle('on', x === b));
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === b.dataset.tab));
});

const root = document.documentElement;
let theme = null;
try { theme = localStorage.getItem('maquette-theme'); } catch {}
if (!theme) theme = matchMedia('(prefers-color-scheme: light)').matches ? 'clair' : 'sombre';
root.dataset.theme = theme;
$('#theme-t use').setAttribute('href', theme === 'sombre' ? '#i-sun' : '#i-moon');
$('#theme-t').onclick = () => {
  theme = theme === 'sombre' ? 'clair' : 'sombre';
  root.dataset.theme = theme;
  $('#theme-t use').setAttribute('href', theme === 'sombre' ? '#i-sun' : '#i-moon');
  try { localStorage.setItem('maquette-theme', theme); } catch {}
  toast(theme === 'sombre' ? 'Thème sombre OLED' : 'Thème clair', true);
};

function toast(msg, ok) {
  const t = document.createElement('div');
  t.className = 'toast' + (ok ? ' ok' : '');
  t.textContent = msg;
  $('#toasts').appendChild(t);
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 2600);
}

$('#new-btn').onclick = () => toast('Nouveau projet envoyé au trancheur ✅', true);
$('#bell').onclick = () => toast('3 alertes : 1 critique résolue, 2 info');
$('#help-t').onclick = () => toast('Maquette de démonstration — 3 tutos dans l\'appli réelle');
$('#q-pause').onclick = () => toast('Impression mise en pause ⏸');
$$('.spool').forEach(s => s.onclick = () => toast(s.dataset.msg));

requestAnimationFrame(() => { $('#ring-fg').style.strokeDashoffset = String(100 - 72); });

setInterval(() => { $('#t-noz').textContent = 217 + Math.round(Math.random() * 2) + '°'; }, 2000);
const tick = () => { $('#clock').textContent = new Date().toLocaleTimeString('fr-FR'); };
tick();
setInterval(tick, 1000);

import { $, api, cfg, ctx, esc, shortTime, toast } from './core.js';
import { files, info, launchFile, loadFiles, select, upload } from './lab.js';

/* ---------------- first-day setup ---------------- */
let setup = null, lastCheck = null;
const ticks = (() => { try { return JSON.parse(localStorage.getItem('cc2-ticks') || '{}'); } catch { return {}; } })();
const saveTicks = () => { try { localStorage.setItem('cc2-ticks', JSON.stringify(ticks)); } catch {} };
async function openStart() {
  setup = await api('/setup');
  $('pc-ip').textContent = setup.pc_ip || 'réseau local';
  if (!$('cfg-host').value) $('cfg-host').value = setup.printer.host || '';
  $('cfg-code').placeholder = setup.printer.code_set ? 'déjà enregistré (ressaisis-le pour tester)' : 'ex. Ab3dEf';
  $('s1-h').classList.toggle('done', !!setup.printer.host && setup.printer.code_set);
  renderTests(); renderPlays(); loadBackup();
}

/* R2.4: backup status + one-shot copy + hourly automatic backup (systemd user timer) */
async function loadBackup() {
  const s = await api('/sauvegarde').catch(() => null);
  if (!s) return;
  const last = s.ok ? new Date(s.ok * 1000).toLocaleString('fr-FR') + (s.vers ? ' vers ' + s.vers : '') : 'jamais';
  $('bk-status').textContent = 'Dernière sauvegarde : ' + last + '.'
    + (s.erreur ? ' Dernier essai en erreur : ' + s.erreur + '.' : '')
    + (s.en_retard ? ' ' + s.en_retard : '')
    + (s.disque ? '' : ' Aucun disque USB détecté.');
  $('bk-auto').textContent = s.auto ? 'Désactiver la sauvegarde auto' : 'Activer la sauvegarde auto';
  $('bk-auto').dataset.on = s.auto ? '1' : '';
}
$('bk-now').onclick = async () => {
  try { const r = await api('/sauvegarde/faire', { method: 'POST' }); toast(r.message, 'ok'); }
  catch (e) { toast(e.message, 'bad'); }
  loadBackup();
};
$('bk-auto').onclick = async () => {
  const on = $('bk-auto').dataset.on !== '1';
  try {
    const r = await api('/sauvegarde/auto', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activer: on, vers: $('bk-vers').value.trim() || null }) });
    toast(r.message, 'ok');
  } catch (e) { toast(e.message, 'bad'); }
  loadBackup();
};
$('cfg-test').onclick = async () => {
  const b = $('cfg-test'); b.disabled = true; b.innerHTML = '<span class="spin"></span>Test en cours…'; $('cfg-save').disabled = true; $('cfg-after').hidden = true;
  try {
    lastCheck = await api('/setup/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host: $('cfg-host').value, access_code: $('cfg-code').value }) });
    $('cfg-checks').innerHTML = lastCheck.steps.map(st => `<div class="check-row"><span class="${st.ok ? 'ok-i' : 'ko-i'}">${st.ok ? '✔' : '✘'}</span><span><b>${esc(st.step)}</b> — ${esc(st.detail)}</span>${st.fix ? `<span class="fix">${esc(st.fix)}</span>` : ''}</div>`).join('');
    $('cfg-save').disabled = !lastCheck.ok;
  } catch (e) { $('cfg-checks').innerHTML = `<div class="check-row"><span class="ko-i">✘</span><span>${esc(e.message)}</span></div>`; }
  b.disabled = false; b.textContent = 'Tester la connexion';
};
$('cfg-save').onclick = async () => {
  await api('/setup/printer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host: $('cfg-host').value, access_code: $('cfg-code').value, serial: lastCheck?.serial }) });
  $('cfg-after').hidden = false;
  $('cfg-after').innerHTML = 'Enregistré dans <code>config.toml</code>. Relance l\'atelier sur la vraie imprimante : arrête-le puis lance <code>uv run cc2 --control dash</code>.';
  toast('Imprimante enregistrée', 'ok'); $('s1-h').classList.add('done');
};

function renderTests() {
  $('tests').innerHTML = setup.tests.map(t => `<div class="tcard" data-test="${t.key}">
    <h3>${esc(t.title)}</h3><div class="tmeta">${esc(t.purpose)}${t.colours > 1 ? ` · ${t.colours} bobines` : ''}</div>
    <ul>${t.look_for.map((l, i) => { const id = `${t.key}-${i}`; return `<li><label><input type="checkbox" data-tick="${id}" ${ticks[id] ? 'checked' : ''}><span>${esc(l)}</span></label></li>`; }).join('')}</ul>
    <div class="grow"></div><div class="tmeta" data-tinfo></div>
    <div class="two"><button class="btn" data-prep>Préparer</button><button class="btn primary" data-print disabled>Imprimer</button></div></div>`).join('');
  $('tests').querySelectorAll('[data-tick]').forEach(c => c.onchange = () => { ticks[c.dataset.tick] = c.checked; saveTicks(); });
  $('tests').querySelectorAll('.tcard').forEach(card => {
    const key = card.dataset.test, info = card.querySelector('[data-tinfo]'), prep = card.querySelector('[data-prep]'), pr = card.querySelector('[data-print]');
    prep.onclick = async () => {
      prep.disabled = true; prep.innerHTML = '<span class="spin"></span>Tranchage…';
      try {
        const r = await api(`/setup/tests/${key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const g = r.gcode[0]; card.dataset.gcode = g;
        info.innerHTML = `${esc(shortTime(r.time))} · ${r.total_m ?? r.filament_m} m${r.colour_changes ? ` · ${r.colour_changes} changements de couleur` : ''} · <a href="#" data-see>voir le tranchage</a>`;
        if (r.bands?.length) info.innerHTML += `<details class="bands"><summary>Valeur de chaque bande (hauteur mesurée depuis le plateau)</summary><table class="list">${r.bands.map(b =>
          `<tr><td>${b.from_mm.toFixed(1).replace('.', ',')} – ${b.to_mm.toFixed(1).replace('.', ',')} mm</td><td class="r">${key === 'debit' ? b.value + ' %' : b.value.toFixed(3).replace('.', ',')}</td></tr>`).join('')}</table></details>`;
        info.querySelector('[data-see]').onclick = ev => { ev.preventDefault(); $('t-lab').click(); loadFiles().then(() => select(files.find(f => f.name === g))); };
        pr.disabled = !ctx.control;
        pr.title = ctx.control ? '' : 'Lecture seule : relance avec cc2 --control dash';
        loadFiles();
      } catch (e) { info.textContent = e.message; }
      prep.disabled = false; prep.textContent = 'Refaire';
    };
    pr.onclick = async () => {
      const g = card.dataset.gcode;
      if (g) await launchFile(g, { upload: true, button: pr });
    };
  });
}
function renderPlays() {
  const cur = setup.dowel_play;
  $('plays').innerHTML = setup.plays.map((p, i) => `<button class="btn ${Math.abs(p - cur) < 1e-6 ? 'on' : ''}" data-play="${p}">${'|'.repeat(i + 1)}&nbsp; ${p.toFixed(2).replace('.', ',')} mm</button>`).join('');
  $('plays').querySelectorAll('[data-play]').forEach(b => b.onclick = async () => {
    const fd = new FormData(); fd.append('play', b.dataset.play);
    const r = await api('/setup/dowel', { method: 'POST', body: fd }); setup.dowel_play = r.dowel_play; renderPlays();
    toast(`Jeu des chevilles : ${r.dowel_play} mm`, 'ok');
  });
}


export { lastCheck, openStart, renderPlays, renderTests, saveTicks, setup, ticks };

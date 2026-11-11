

const $ = id => document.getElementById(id);
const SLOT = ['#E53935', '#1E88E5', '#43A047', '#FDD835'];
const MESH = ['stl', '3mf', 'obj', 'glb', 'gltf', 'ply'];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const api = async (p, o) => { const r = await fetch('/lab/api' + p, o); if (r.status === 401) { location.href = '/lab/login.html'; throw new Error('Code d\'accès requis'); } const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || r.statusText); return j; };
const toast = (msg, kind = '') => { const t = document.createElement('div'); t.className = 'toast ' + kind; t.textContent = msg; $('toasts').append(t); setTimeout(() => t.remove(), kind === 'bad' ? 9000 : 5000); };
const shortTime = t => !t ? '–' : t.replace(/(\d+)d\s*/, '$1 j ').replace(/(\d+)h\s*(\d+)m.*/, '$1 h $2').replace(/^(\d+)m\s*\d+s$/, '$1 min');
const size = b => b > 1e9 ? (b / 1e9).toFixed(1).replace('.', ',') + ' Go' : b > 1e6 ? (b / 1e6).toFixed(1) + ' Mo' : Math.max(1, Math.round(b / 1e3)) + ' Ko';

// a file name to read: no generation timestamp, no extension; a G-code keeps its model and layer height
// ("atelier_couleurs_00015_clean_canvas_0.24mm_PLA_Silk_Noel-PLA.gcode" -> "atelier couleurs 00015 clean · 0,24 mm")
const nice = n => {
  const g = /^(.*?)(?:_canvas)?_(\d+(?:\.\d+)?)mm_.*\.gcode$/i.exec(n || '');
  const base = (g ? g[1] : String(n || '').replace(/\.[^.]+$/, '')).replace(/^\d{8}-\d{6}_/, '').replace(/_/g, ' ').trim();
  return (base || n) + (g ? ` · ${g[2].replace('.', ',')} mm` : '');
};
const hooks = {};   // set by other modules (core imports nobody, so it is always ready first)
const ctx = {}, cfg = {};   // filled once at boot (Object.assign: other modules hold these objects)
const spools = {};

const durSec = t => { if (!t) return 0; let s = 0; for (const [, n, u] of t.matchAll(/(\d+)([dhms])/g)) s += +n * { d: 86400, h: 3600, m: 60, s: 1 }[u]; return s; };
const fmtG = g => g >= 1000 ? (g / 1000).toFixed(2).replace('.', ',') + ' kg' : Math.round(g) + ' g';
const euro = e => (e ?? 0).toFixed(2).replace('.', ',') + ' €';
const STATE = { 0: 'Prête', 1: 'Mise en origine', 5: 'Pause…', 6: 'En pause', 7: 'Arrêt…', 8: 'Arrêtée', 9: 'Terminée', 12: 'Reprise', 13: 'Impression', 14: 'Erreur', 15: 'Nivellement', 16: 'Préchauffe', 27: 'Changement de filament' };
const BUSY = new Set([1, 5, 6, 7, 12, 13, 15, 16, 27, 28, 29]);
const ctl = async (path, body) => {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || r.statusText); return j;
};
const SCREEN_ONLY = { '/print/resume': 'Reprise refusée en réseau : reprends depuis l\'écran de l\'imprimante.',
  '/print/temperature': 'Température refusée en réseau : règle-la depuis l\'écran de l\'imprimante.' };
const act = async (btn, path, body, okMsg) => {
  if (btn) btn.disabled = true;
  try { await ctl(path, body); if (okMsg) toast(okMsg, 'ok'); setTimeout(() => hooks.afterAct?.(), 600); }
  catch (e) { toast(SCREEN_ONLY[path] ? `${SCREEN_ONLY[path]} (${e.message})` : e.message, 'bad'); }
  if (btn) btn.disabled = !ctx.control;
};
const dur = s => { if (s == null || s <= 0) return '–'; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, '0')}` : `${m} min`; };
const evTime = t => { const d = new Date(t * 1000), now = new Date(); return d.toDateString() === now.toDateString() ? d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }); };

export { hooks, nice, $, BUSY, MESH, SCREEN_ONLY, SLOT, STATE, act, api, cfg, ctl, ctx, dur, durSec, esc, euro, evTime, fmtG, shortTime, size, spools, toast };

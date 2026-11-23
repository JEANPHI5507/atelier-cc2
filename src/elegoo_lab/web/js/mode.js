/* Display mode (R2.1): 'debutant' hides the advanced options (class .advanced), 'avance' shows everything.
   Kept in config.toml ([interface] mode) so every device opening the workshop sees the same mode.
   Plain script, no modules: the old tablet loads it too. */
(function () {
  'use strict';
  var mode = 'debutant';
  function apply(m) {
    mode = m;
    if (!document.body) return;
    document.body.classList.toggle('mode-debutant', m === 'debutant');
    var t = document.getElementById('mode-t');
    if (t) t.textContent = m === 'debutant' ? 'Débutant' : 'Avancé';
    var b = document.getElementById('mode');
    if (b) b.title = m === 'debutant'
      ? 'Passer en mode Avancé (tout afficher)'
      : 'Passer en mode Débutant (masquer les options avancées)';
  }
  window.UI_MODE = {
    toggle: function () {
      var m = mode === 'debutant' ? 'avance' : 'debutant';
      var r = new XMLHttpRequest();
      r.open('POST', '/lab/api/mode'); r.setRequestHeader('Content-Type', 'application/json');
      r.onloadend = function () { apply(m); };
      r.send(JSON.stringify({ mode: m }));
    }
  };
  function init() {
    var r = new XMLHttpRequest(); r.open('GET', '/lab/api/mode');
    r.onload = function () { try { apply(JSON.parse(r.responseText).mode || 'debutant'); } catch (e) { apply('debutant'); } };
    r.onerror = function () { apply('debutant'); };
    r.send();
  }
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init);
})();

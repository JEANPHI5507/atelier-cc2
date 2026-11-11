/* The interface in English: the pages are written in French, and every text shown (static, built by the scripts, or
   sent by the server) is looked up in i18n/en.json when the language is English. Exact texts first, then patterns
   where {} stands for a number or a name ("Couche {} / {}"). New text is translated as it appears (MutationObserver).
   Plain script, no modules: the old tablet loads it too. Language: localStorage cc2-lang, else the browser's. */
(function () {
  'use strict';
  var KEY = 'cc2-lang', saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var lang = saved || ((navigator.language || 'fr').toLowerCase().indexOf('fr') === 0 ? 'fr' : 'en');
  var exact = {}, patterns = [], generic = 0, ready = false, missing = {}, english = {}, debug = false;
  try { debug = localStorage.getItem('cc2-i18n-debug') === '1'; } catch (e) {}   // list every untranslated text, not only obvious French
  var FRENCH = /[éèêàùçôîâœ«»]|\b(le|la|les|des|une?|du|et|pas|sur|pour|avec|dans|est|ton|ta|tes|ou)\b/i;
  var ATTRS = ['title', 'placeholder', 'aria-label', 'alt', 'data-cap'];
  var SKIP = { SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1, TEXTAREA: 1 };

  document.documentElement.lang = lang;
  window.I18N = {
    lang: lang,
    set: function (l) {
      try { localStorage.setItem(KEY, l); } catch (e) {}
      // the server follows, for the phone notifications; reload either way
      var r = new XMLHttpRequest(); r.open('POST', '/lab/api/langue'); r.setRequestHeader('Content-Type', 'application/json');
      r.onloadend = function () { location.reload(); }; r.send(JSON.stringify({ lang: l }));
    },
    t: function (s) { return lang === 'en' ? tr(s) : s; },
    missing: function () { return Object.keys(missing); }
  };
  if (lang !== 'en') return;

  var style = document.createElement('style');
  style.textContent = 'html.i18n-wait body{visibility:hidden}';
  document.head.appendChild(style);
  document.documentElement.className += ' i18n-wait';

  function esc(s) { return s.replace(/[.*+?^$()|[\]\\]/g, '\\$&'); }
  // patterns are sorted most specific first; the last ones ("{} : {}", "{} · {}") only split a text into pieces
  function byPattern(s, from, to) {
    for (var i = from; i < to; i++) {
      var g = patterns[i].re.exec(s);
      // {} takes the next value, {3} the third one (English may drop a French plural mark);
      // each filled-in piece is translated too: "Consigne Buse" -> "Target Nozzle"
      if (g) { var k = 1; return patterns[i].en.replace(/\{(\d*)\}/g, function (_, n) { var v = n ? g[+n] : g[k++]; return v ? tr(v) : v; }); }
    }
  }
  function tr(raw) {
    if (!raw || !ready) return raw;
    var m = /^(\s*)([\s\S]*?)(\s*)$/.exec(raw), s = m[2].replace(/\s+/g, ' ');
    if (!s || !/[A-Za-zÀ-ÿ]/.test(s)) return raw;
    var hit = exact[s];
    if (hit === undefined) hit = byPattern(s, 0, generic);
    if (hit === undefined && /[.!?] [A-ZÀ-Ý]/.test(s)) {   // an alert chains sentences: translate them one by one
      var parts = s.split(/(?<=[.!?])\s+(?=[A-ZÀ-Ý])/), done = parts.map(function (x) { return tr(x); });
      if (done.join(' ') !== parts.join(' ')) hit = done.join(' ');
    }
    if (hit === undefined) hit = byPattern(s, generic, patterns.length);
    if (hit === undefined) { if (FRENCH.test(s) || (debug && !english[s])) missing[s] = 1; return raw; }
    return m[1] + hit + m[3];
  }
  function node(n) {
    if (n.nodeType === 3) {
      var p = n.parentNode;
      if (p && !SKIP[p.nodeName] && !(p.closest && p.closest('[translate="no"]:not(html)'))) {
        var v = tr(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v;
      }
      return;
    }
    if (n.nodeType !== 1 || SKIP[n.nodeName]) return;
    for (var a = 0; a < ATTRS.length; a++) {
      var at = n.getAttribute(ATTRS[a]);
      if (at) { var t = tr(at); if (t !== at) n.setAttribute(ATTRS[a], t); }
    }
    if (n.nodeName === 'INPUT' && (n.type === 'button' || n.type === 'submit') && n.value) n.value = tr(n.value);
    for (var c = n.firstChild; c; c = c.nextSibling) node(c);
  }
  function all() { node(document.body); document.title = tr(document.title); }

  // dialogs too
  var c0 = window.confirm, a0 = window.alert, p0 = window.prompt;
  window.confirm = function (s) { return c0.call(window, tr(String(s))); };
  window.alert = function (s) { return a0.call(window, tr(String(s))); };
  window.prompt = function (s, d) { return p0.call(window, tr(String(s)), d); };

  var src = (document.currentScript && document.currentScript.src) || '';
  var base = src ? src.replace(/js\/i18n\.js.*$/, '') : '/lab/';
  var x = new XMLHttpRequest();
  x.open('GET', base + 'i18n/en.json');
  x.onload = function () {
    try {
      var d = JSON.parse(x.responseText);
      exact = d.exact || {};
      for (var e in exact) english[exact[e]] = 1;
      (d.patterns || []).forEach(function (p) {
        // a {} may be empty: a French plural mark ("fichier{}") is "" in the singular
        patterns.push({ re: new RegExp('^' + esc(p[0]).replace(/\\\{\\\}|\{\}/g, '(.*?)') + '$'), en: p[1] });
      });
      generic = patterns.length;
      while (generic > 0 && (d.patterns[generic - 1][0].replace(/\{\}/g, '').length <= 3)) generic--;
    } catch (e) {}
    ready = true;
    function go() {
      all();
      document.documentElement.className = document.documentElement.className.replace(' i18n-wait', '');
      new MutationObserver(function (list) {
        for (var i = 0; i < list.length; i++) {
          var r = list[i];
          if (r.type === 'characterData') node(r.target);
          else if (r.type === 'attributes') node(r.target);
          else for (var j = 0; j < r.addedNodes.length; j++) node(r.addedNodes[j]);
        }
        if (document.title) { var t = tr(document.title); if (t !== document.title) document.title = t; }
      }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    }
    if (document.body) go(); else document.addEventListener('DOMContentLoaded', go);
  };
  x.onerror = function () { document.documentElement.className = document.documentElement.className.replace(' i18n-wait', ''); };
  x.send();
})();

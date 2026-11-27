import * as THREE from 'three';
import { OrbitControls } from '../vendor/addons/OrbitControls.js';
import { STLLoader } from '../vendor/addons/STLLoader.js';
import { GLTFLoader } from '../vendor/addons/GLTFLoader.js';
import { $, nice, BUSY, MESH, SLOT, api, cfg, ctx, dur, durSec, esc, euro, fmtG, shortTime, size, sizeTxt, spools, toast } from './core.js';

/* viewer: optional, the page works without WebGL */
let files = [], sel = null, analysis = null, mapping = {}, info = null, trays = {}, single = null;
// colours paired with the loaded spools: one summary line, the detail only on « Modifier »
let matched = null, colEdit = false;
// filament left on each loaded spool (g, from the stock) and the "almost empty" threshold
let stockLeft = {}, stockLow = 0;
// grams each colour should need, estimated by the server before any slicing ({} when not computable)
let needs = {};
let optUndo = null;   // the form before « Optimiser pour la CC2 », to put it back
// the CC2's plate: Elegoo's own model and markings (from OrcaSlicer's CC2 profile, vendor/cc2), on the textured PEI
// grain seen on the camera. OrcaSlicer lays the markings over 0..256 x -10..256 mm and centres the model on the bed.
const PLATE_AREA = { x0: -128, x1: 128, y0: -138, y1: 128 };      // the markings' area, in the scene (bed centre = 0)
function plateTexture(marks) {
  const k = 4, w = 256 * k, h = (PLATE_AREA.y1 - PLATE_AREA.y0) * k, c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d'), rnd = (i => () => ((i = Math.imul(i, 48271) % 2147483647) & 0xffff) / 0xffff)(7);
  g.fillStyle = '#2b2d31'; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 64000; i++) {   // the PEI grain: light and dark specks (same each time)
    const v = rnd() < .55 ? 70 + rnd() * 70 : 18 + rnd() * 20;
    g.fillStyle = `rgba(${v | 0},${v | 0},${(v + 4) | 0},${.35 + rnd() * .4})`;
    g.fillRect(rnd() * w, rnd() * h, 1 + rnd() * 1.6, 1 + rnd() * 1.6);
  }
  if (marks) g.drawImage(marks, 0, 0, w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
// a soft studio around the plate, for reflections: light from above and the front, dark floor (no file to load)
function studio() {
  const sc = new THREE.Scene(), geo = new THREE.SphereGeometry(100, 32, 16), col = [];
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) { const z = pos.getZ(i) / 100, v = z > 0 ? .35 + .65 * z : .08; col.push(v, v, v * 1.02); }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  sc.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
  [[0, -60, 70, 40], [70, 40, 50, 25], [-70, 20, 40, 20]].forEach(([x, y, z, w]) => {   // three soft boxes
    const l = new THREE.Mesh(new THREE.PlaneGeometry(w, w), new THREE.MeshBasicMaterial({ color: 0x8c8c8c, side: THREE.DoubleSide }));
    l.position.set(x, y, z); l.lookAt(0, 0, 0); sc.add(l);
  });
  const pm = new THREE.PMREMGenerator(renderer), t = pm.fromScene(sc, .04).texture; pm.dispose();
  return t;
}
function loadPlate() {
  const img = new Image();
  img.onload = () => { const old = plateMat.map; plateMat.map = plateTexture(img); plateMat.needsUpdate = true; old.dispose(); };
  img.src = 'vendor/cc2/plateau.svg';
  new STLLoader().load('vendor/cc2/plateau.stl', geo => {   // the steel sheet with its tabs, under the markings
    geo.translate(0, 2, -.02); geo.computeVertexNormals();   // centred on the bed like OrcaSlicer does (its box is -140.25..136.25 in y)
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x232428, roughness: .7, metalness: .2 })); m.receiveShadow = true; scene.add(m);
  }, undefined, () => {});
}
const stage = $('stage'); let renderer = null, scene, cam, controls, current = null, plateMat = null, grid = null, refit = false;
// render on demand: the loop keeps running (damping, wake-ups) but only draws when something changed
let needRender = true;
const renderOnce = () => { needRender = true; };
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));   // beyond 2 the retina/phone cost is huge for nothing visible
  stage.prepend(renderer.domElement);
  scene = new THREE.Scene();
  cam = new THREE.PerspectiveCamera(38, 1, 1, 5000); cam.up.set(0, 0, 1); cam.position.set(260, -300, 230);
  controls = new OrbitControls(cam, renderer.domElement); controls.target.set(0, 0, 30); controls.enableDamping = true;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  scene.environment = studio();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x30343c, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.9); sun.position.set(160, -200, 380); scene.add(sun);
  sun.castShadow = true; Object.assign(sun.shadow.camera, { left: -160, right: 160, top: 160, bottom: -160, near: 10, far: 900 });
  const sm = matchMedia('(max-width: 600px)').matches ? 1024 : 2048; sun.shadow.mapSize.set(sm, sm); sun.shadow.bias = -.0004; sun.shadow.normalBias = .4; sun.shadow.radius = 4;
  plateMat = new THREE.MeshStandardMaterial({ roughness: .85, map: plateTexture() });
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(256, PLATE_AREA.y1 - PLATE_AREA.y0), plateMat);
  plate.position.y = (PLATE_AREA.y0 + PLATE_AREA.y1) / 2; plate.receiveShadow = true; scene.add(plate); loadPlate();
  grid = new THREE.GridHelper(256, 16); grid.material.transparent = true; grid.material.opacity = .22; grid.rotation.x = Math.PI / 2; grid.position.z = .05; scene.add(grid);
  // the CC2's no-print corner (bed_exclude_area 246-256 x 0-20 mm, front right)
  const no = new THREE.Mesh(new THREE.PlaneGeometry(10, 20), new THREE.MeshBasicMaterial({ color: 0xff5a4f, transparent: true, opacity: .45 }));
  no.position.set(123, -118, .1); scene.add(no);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(256, 256, 256)), new THREE.LineBasicMaterial({ color: 0x8a96a8, transparent: true, opacity: .35 })); frame.position.z = 128; scene.add(frame);
  const resize = () => { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); renderOnce();
    if (refit && current && w && h) { refit = false; frame(current); }   // framed while hidden: fit it now
    if (stage.classList.contains('painting')) paintView(); };
  new ResizeObserver(resize).observe(stage); resize();
  controls.addEventListener('change', renderOnce);   // damping and orbits redraw only while they move
} catch { renderer = null; }
if (renderer) renderer.setAnimationLoop(() => {
  if (document.hidden || $('lab').hidden || $('make')?.open || $('asm')?.open) return;   // the main view is not the one on screen
  controls.update();
  if (mesure.on) mesureUpd();   // the distance label follows the model on screen
  if (needRender) { needRender = false; renderer.render(scene, cam); }
});

// freeing the GPU buffers of a removed object (models, paths, helpers): a disposed buffer is
// re-uploaded on demand, so reusing one elsewhere stays safe
function disposeObj(obj) {
  obj.traverse(o => {
    o.geometry?.dispose?.();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of mats) { for (const v of Object.values(m)) if (v?.isTexture) v.dispose(); m.dispose(); }
  });
}
// the shown model goes away: remove it and its buffers (the picked-spot marker dies with it)
function dropCurrent() {
  if (!current) return;
  if (cible.marker && cible.marker.parent === current) cible.marker = null;
  if (mesure.grp) { mesure.grp = null; mesure.b = null; mesure.on = false; $('vmeas').hidden = true; }   // died with the model
  scene.remove(current); disposeObj(current); current = null; renderOnce();
}
function show(obj) {
  current = obj; scene.add(obj);
  const box = new THREE.Box3().setFromObject(obj), c = box.getCenter(new THREE.Vector3());
  obj.position.sub(new THREE.Vector3(c.x, c.y, box.min.z)); $('hint').hidden = true; renderOnce();
}
function hint(big, small) { $('hint').hidden = false; $('hint').innerHTML = `<div><div class="big">${big}</div>${small}</div>`; }
let previewKey = '';
async function preview(f, map = '') {
  if (!renderer) return hint('Aperçu 3D indisponible', 'WebGL est désactivé dans ce navigateur. Tout le reste fonctionne.');
  if (f.ext === 'gcode') { dropCurrent(); return hint('Fichier tranché', 'Pas d\'aperçu des trajectoires. Il est prêt à être envoyé.'); }
  const pal = palString(), key = f.name + '|' + map + '|' + pal;
  if (key === previewKey) return;
  setView('model');
  previewKey = key;
  if (!current) hint('Chargement de l\'aperçu…', '');
  try {
    // every format goes through the server: one GLB, coloured per CANVAS slot
    const g = await new GLTFLoader().loadAsync(`/lab/api/models/${encodeURIComponent(f.name)}/preview.glb?map=${encodeURIComponent(map)}&pal=${encodeURIComponent(pal)}&v=${Math.round(f.mtime)}`);
    if (previewKey !== key) return;  // a newer request won
    g.scene.traverse(o => { if (o.isMesh) { const ix = o.geometry.index; if (ix && ix.count === o.geometry.attributes.position.count) o.geometry.setIndex(null);   // identity index: triangle i = face i
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals(); o.material = overhangAware(new THREE.MeshStandardMaterial({ vertexColors: !!o.geometry.attributes.color, color: o.geometry.attributes.color ? 0xffffff : 0xd7dbe2, roughness: .55 })); o.castShadow = true; } });
    g.scene.rotation.x = Math.PI / 2; g.scene.userData.base = Math.PI / 2;
    dropCurrent();
    show(g.scene); renderRot(); modelLook(); vtoolsShow(); piecesInit(f);
    if (framedFor !== f.name) { frame(g.scene); framedFor = f.name; }
  } catch (e) { previewKey = ''; hint('Aperçu impossible', esc(e.message)); }
}
// overhangs in red, computed on the GPU in plate axes: they follow every change of position
const OVER = { value: 0 }, FLOOR = { value: 0.4 };   // FLOOR: just above the plate, in the model's own units
function overhangAware(mat) {
  mat.onBeforeCompile = sh => {
    sh.uniforms.uOver = OVER; sh.uniforms.uFloor = FLOOR;
    sh.vertexShader = 'varying vec3 vWN; varying float vWZ;\n' + sh.vertexShader.replace('#include <project_vertex>',
      '#include <project_vertex>\n vWN = normalize(mat3(modelMatrix) * objectNormal); vWZ = (modelMatrix * vec4(transformed, 1.0)).z;');
    sh.fragmentShader = 'uniform float uOver; uniform float uFloor; varying vec3 vWN; varying float vWZ;\n' + sh.fragmentShader.replace('#include <color_fragment>',
      '#include <color_fragment>\n if (uOver > 0.5 && normalize(vWN).z < -0.766 && vWZ > uFloor) diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.95, 0.22, 0.18), 0.85);');
  };
  return mat;
}
let framedFor = '';
const VIEWS = { iso: [0.65, -0.8, 0.55], face: [0, -1, 0.12], top: [0, -0.001, 1], side: [1, 0, 0.12], low: [0.6, -0.8, 0.04] };
// camera distance along dir so the box fills the view both ways (projected, not its diagonal: a flat part seen
// from above fills the screen), at least 60 mm of plate in sight around a small part
function place(box, kind, margin = 1.12) {
  const a = stage.clientHeight ? stage.clientWidth / stage.clientHeight : cam.aspect;
  if (!(a > 0)) refit = true;
  const back = new THREE.Vector3(...VIEWS[kind]).normalize(), right = new THREE.Vector3(0, 0, 1).cross(back);
  if (right.lengthSq() < 1e-9) right.set(1, 0, 0);
  right.normalize(); const up = back.clone().cross(right), c = box.getCenter(new THREE.Vector3());
  let w = 30, h = 30, dz = 0;
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    const p = new THREE.Vector3(x, y, z).sub(c);
    w = Math.max(w, Math.abs(p.dot(right))); h = Math.max(h, Math.abs(p.dot(up))); dz = Math.max(dz, p.dot(back));
  }
  const tv = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2), d = Math.max(h / tv, w / (tv * (a > 0 ? a : 1))) * margin + dz;
  controls.target.copy(c); cam.position.copy(c).addScaledVector(back, d);
  cam.near = Math.max(.1, d / 200); cam.far = Math.max(5000, d * 20); cam.updateProjectionMatrix(); renderOnce();
  $('vtools').querySelectorAll('[data-cam]').forEach(b => b.classList.toggle('on', b.dataset.cam === kind));
}
function frame(obj) { place(new THREE.Box3().setFromObject(obj), 'iso'); }   // the 3/4 view, the whole model in sight
function camTo(kind) {
  if (kind === 'plate') {   // the whole plate, with the part on it
    const top = current ? new THREE.Box3().setFromObject(current).max.z : 0;
    return place(new THREE.Box3(new THREE.Vector3(-130, -140, 0), new THREE.Vector3(130, 136, Math.max(20, top))), 'iso', 1.02);
  }
  if (current) place(new THREE.Box3().setFromObject(current), kind);
}
// the part as it will be printed: the spool's colour when it prints in one, a glossy surface for Silk
function modelLook() {
  if (!current || previewKey === 'cut' || paths?.parts?.some(p => p.lines.parent === current)) return;
  const used = Object.values(trays || {}).filter(Boolean), silk = used.length > 0 && used.every(t => /silk/i.test(t.filament || t.name || ''));
  const hex = single && trays[1]?.hex;
  current.traverse(o => {
    if (!o.isMesh || !o.material?.isMeshStandardMaterial) return;
    const m = o.material;
    if (hex) { m.vertexColors = false; m.color.set(hex); }        // one spool: all of it in that spool's colour
    else if (!m.vertexColors) m.color.set(0xd7dbe2);
    m.roughness = silk ? .38 : .55; m.metalness = silk ? .3 : 0; m.envMapIntensity = silk ? .9 : .5; m.needsUpdate = true;
  });
  renderOnce();
}
const mapString = () => Object.entries(mapping).map(([c, s]) => `${c}:${s}`).join(',');
// the loaded spools' colours (slot 1 first) when the model is repainted with them, else ''
const palString = () => (analysis?.palette || []).map(h => h || '').join(',');

/* viewer toolbar: camera presets, overhangs, dimensions, recentre, full screen */
let dimsBox = null;
function vtoolsShow() {
  const on = !!renderer && !!current;
  $('vtools').hidden = !on;
  const model = on && !paths?.parts?.some(p => p.lines.parent === current);
  $('vtools').querySelectorAll('[data-vt="over"], [data-vt="dims"], [data-vt="paint"], [data-vt="marks"]').forEach(b => b.hidden = !model);
  const movable = model && mv.ranges.length >= 1 && sel?.name === mv.file;
  $('vtools').querySelector('[data-vt="move"]').hidden = !movable;
  $('vtools').querySelector('[data-vt="regroup"]').hidden = !movable || !(Object.keys(mv.moves).length || Object.keys(mv.scales).length);
  $('vtools').querySelector('[data-vt="add"]').hidden = !model || !sel || sel.ext === 'gcode';
  $('vtools').querySelector('[data-vt="paint"]').hidden = !model || !sel || sel.ext === 'gcode';   // the server colours every format: all can be touched up
  $('vtools').querySelector('[data-vt="cible"]').hidden = !model || !sel || sel.ext === 'gcode';
  $('vtools').querySelector('[data-vt="mesure"]').hidden = !model || !sel || sel.ext === 'gcode';
  if (cible.on && $('vtools').querySelector('[data-vt="cible"]').hidden) setCible(false);   // no target on a gcode view
  if (!model) { OVER.value = 0; setDims(false); $('vtools').querySelector('[data-vt="over"]').classList.remove('on'); }
}
function setDims(on) {
  dimsBox = dropBox(dimsBox);
  $('vdims').hidden = !on; $('vtools').querySelector('[data-vt="dims"]').classList.toggle('on', on);
  if (!on || !current) return;
  const box = new THREE.Box3().setFromObject(current), sz = box.getSize(new THREE.Vector3());
  const h = +$('height').value, k = h && sz.z ? h / sz.z : 1;     // the size it will be printed at
  dimsBox = new THREE.Box3Helper(box, 0xffd98a); scene.add(dimsBox); renderOnce();
  $('vdims').textContent = sizeTxt([sz.x * k, sz.y * k, sz.z * k]);
}
document.querySelectorAll('#vtools [data-cam]').forEach(b => b.onclick = () => camTo(b.dataset.cam));
$('vtools').querySelector('[data-vt="over"]').onclick = e => {
  OVER.value = OVER.value ? 0 : 1; e.currentTarget.classList.toggle('on', !!OVER.value); renderOnce();
  if (!OVER.value || !current) return;
  const box = new THREE.Box3().setFromObject(current);
  FLOOR.value = box.min.z + (box.max.z - box.min.z) * 0.01;      // the face lying on the plate is not an overhang
  camTo('low');                                                  // overhangs face down: look from low
  toast('En rouge : les zones penchées à plus de 50° qui auront besoin de supports (vue basse).');
};
$('vtools').querySelector('[data-vt="dims"]').onclick = () => setDims(!dimsBox);
$('vtools').querySelector('[data-vt="fit"]').onclick = () => camTo('iso');
$('vtools').querySelector('[data-vt="full"]').onclick = () => {
  if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen?.().catch(() => {});
};
/* move pieces: drag one object of a multi-object model across the plate; the server applies the same moves */
const mv = { file: '', ranges: [], moves: {}, scales: {}, orig: null, sel: -1, on: false, drag: null };
const pieceMesh = () => { let m = null; current?.traverse(o => { if (o.isMesh && !m) m = o; }); return m; };
async function piecesInit(f) {
  if (mv.file !== f.name) {
    Object.assign(mv, { file: f.name, ranges: [], moves: {}, scales: {}, orig: null, sel: -1 }); setMove(false); pieceSelect(-1);
    try { const r = await api(`/models/${encodeURIComponent(f.name)}/pieces`); if (mv.file === f.name) mv.ranges = r; } catch { /* one piece: nothing to move */ }
  }
  // the mesh as loaded: every change starts from it (a palette change reloads the same shape: keep the first copy,
  // the new mesh already took the moves)
  const m = pieceMesh(), a = m?.geometry.attributes.position.array;
  if (a && (!mv.orig || mv.orig.length !== a.length)) mv.orig = Float32Array.from(a);
  if (Object.keys(mv.moves).length || Object.keys(mv.scales).length) renderRot();   // palette change reloaded the mesh
  vtoolsShow();
}
// the pieces from the loaded mesh: moves (in the model's own axes, x y z up; the geometry is Y-up: x, z, -y), then
// the sizes, about each piece's bottom centre as it lies on the plate (the slicer does the same, after the turns)
function piecesBase() {
  const m = pieceMesh(); if (!m || !mv.orig || m.geometry.attributes.position.array.length !== mv.orig.length) return;
  const pos = m.geometry.attributes.position, a = pos.array; a.set(mv.orig);
  for (const [k, d] of Object.entries(mv.moves)) {
    const r = mv.ranges[k]; if (!r) continue;
    for (let i = r.first * 9; i < (r.first + r.count) * 9; i += 3) { a[i] += d[0]; a[i + 1] += d[2]; a[i + 2] -= d[1]; }
  }
  pos.needsUpdate = true; renderOnce();
}
function piecesScale() {
  const m = pieceMesh(); if (!m || !mv.orig) return;
  m.updateMatrixWorld(true);
  const pos = m.geometry.attributes.position, a = pos.array, inv = m.matrixWorld.clone().invert(), v = new THREE.Vector3();
  for (const [k, f] of Object.entries(mv.scales)) {
    const r = mv.ranges[k]; if (!r || f === 1) continue;
    const box = new THREE.Box3();
    for (let i = r.first * 3; i < (r.first + r.count) * 3; i++) box.expandByPoint(v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld));
    const c = new THREE.Vector3((box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, box.min.z).applyMatrix4(inv);
    for (let i = r.first * 9; i < (r.first + r.count) * 9; i += 3) {
      a[i] = c.x + (a[i] - c.x) * f; a[i + 1] = c.y + (a[i + 1] - c.y) * f; a[i + 2] = c.z + (a[i + 2] - c.z) * f;
    }
  }
  pos.needsUpdate = true; m.geometry.computeBoundingBox(); m.geometry.computeBoundingSphere(); renderOnce();
}
// the world box of one piece, as shown
function pieceBox(k) {
  const m = pieceMesh(), r = mv.ranges[k], box = new THREE.Box3(); if (!m || !r) return box;
  m.updateMatrixWorld(true);
  const pos = m.geometry.attributes.position, v = new THREE.Vector3();
  for (let i = r.first * 3; i < (r.first + r.count) * 3; i++) box.expandByPoint(v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld));
  return box;
}
// the chosen piece: a frame around it, its name and its size beside the 3D view
let selBox = null;
function dropBox(box) { if (box) { scene?.remove(box); box.geometry?.dispose?.(); box.material?.dispose?.(); } return null; }
function pieceSelect(k) {
  mv.sel = k;
  selBox = dropBox(selBox); renderOnce();
  const panel = $('pc-panel'); panel.hidden = k < 0 || !mv.ranges[k];
  if (panel.hidden) return;
  const box = pieceBox(k), size = box.getSize(new THREE.Vector3());
  selBox = new THREE.Box3Helper(box, 0xff9f0a); scene.add(selBox);
  const pct = Math.round((mv.scales[k] || 1) * 100);
  $('pc-name').textContent = nice(mv.ranges[k].name || `Pièce ${k + 1}`);
  $('pc-dims').textContent = sizeTxt([size.x, size.y, size.z], 1);
  $('pc-size').value = pct; $('pc-pct').value = pct;
  $('pc-del').hidden = mv.ranges.length < 2;
}
function pieceResize(pct) {
  const k = mv.sel; if (k < 0) return;
  const f = Math.max(10, Math.min(500, Math.round(+pct || 100))) / 100;
  if (f === 1) delete mv.scales[k]; else mv.scales[k] = f;
  renderRot(); pieceSelect(k); vtoolsShow(); sizeNote();
}
function setMove(on) {
  if (on && mesure.on) setMesure(false);   // a click then grabs a piece, it does not measure
  mv.on = on && mv.ranges.length >= 1; mv.drag = null; if (controls) controls.enabled = true;
  if (!mv.on) pieceSelect(-1);
  $('vtools').querySelector('[data-vt="move"]').classList.toggle('on', mv.on);
  stage.style.cursor = mv.on ? 'grab' : '';
  if (mv.on) { camTo('top'); toast('Touche une pièce pour la choisir (sa taille se règle à côté), glisse-la pour la déplacer.'); }
}
const PLATE_EDGE = 123;   // half the CC2's 256 mm plate (centred on the viewer's origin), less a 5 mm margin
const moved = () => sel?.name === mv.file && previewKey !== 'cut' && Object.values(mv.moves).some(d => d.some(Boolean));
const resized = () => sel?.name === mv.file && previewKey !== 'cut' && Object.keys(mv.scales).length > 0;
const shiftXY = () => { current.updateMatrixWorld(true); const c = new THREE.Box3().setFromObject(current).getCenter(new THREE.Vector3()); return [c.x, c.y]; };
if (renderer) {
  const dom = renderer.domElement, aim = e => { const r = dom.getBoundingClientRect(); ptr.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1); ray.setFromCamera(ptr, cam); };
  dom.addEventListener('pointerdown', e => {
    const m = mv.on && e.button === 0 && !stage.classList.contains('painting') ? pieceMesh() : null; if (!m) return;
    current.updateMatrixWorld(true); aim(e);
    const hit = ray.intersectObject(m, false)[0]; if (!hit) return;
    const k = mv.ranges.findIndex(r => hit.faceIndex >= r.first && hit.faceIndex < r.first + r.count); if (k < 0) return;
    pieceSelect(k);
    const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -hit.point.z), last = new THREE.Vector3();
    if (!ray.ray.intersectPlane(plane, last)) return;
    // the piece's footprint on the plate (world x, y), so a drag stops at the plate's edge instead of flying off it
    // (seen tilted, a few pixels near the horizon are tens of centimetres)
    const pos = m.geometry.attributes.position, r = mv.ranges[k], v = new THREE.Vector3(), box = new THREE.Box3();
    for (let i = r.first * 3; i < (r.first + r.count) * 3; i++) box.expandByPoint(v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld));
    mv.drag = { k, plane, last, box, off: new THREE.Vector3() };
    controls.enabled = false; dom.setPointerCapture(e.pointerId); stage.style.cursor = 'grabbing'; e.stopImmediatePropagation();
  }, true);
  // the pointer's samples arrive faster than the screen: one piece update per displayed frame
  const dragStep = e => {
    aim(e); const w = new THREE.Vector3(); if (!ray.ray.intersectPlane(mv.drag.plane, w)) return;
    const D = mv.drag, want = D.off.clone().add(w.clone().sub(D.last)), edge = PLATE_EDGE;
    D.last = w;
    want.x = Math.min(edge - D.box.max.x, Math.max(-edge - D.box.min.x, want.x));   // keep it on the plate
    want.y = Math.min(edge - D.box.max.y, Math.max(-edge - D.box.min.y, want.y)); want.z = 0;
    const dw = want.clone().sub(D.off); D.off = want;
    if (!dw.x && !dw.y) return;
    const m = pieceMesh(), inv = new THREE.Matrix3().setFromMatrix4(m.matrixWorld).invert(), l = dw.applyMatrix3(inv);
    const d = [l.x, -l.z, l.y], cur = mv.moves[mv.drag.k] || [0, 0, 0];
    mv.moves[mv.drag.k] = cur.map((v, i) => v + d[i]); piecesBase(); piecesScale(); pieceSelect(mv.drag.k);
  };
  dom.addEventListener('pointermove', e => {
    if (!mv.drag) return;
    mv.drag.ev = e;
    if (mv.drag.raf) return;
    mv.drag.raf = requestAnimationFrame(() => { const D = mv.drag; if (D) { D.raf = 0; if (D.ev) dragStep(D.ev); D.ev = null; } });
  });
  const end = () => {
    if (!mv.drag) return;
    if (mv.drag.raf) cancelAnimationFrame(mv.drag.raf);
    mv.drag = null; controls.enabled = true; stage.style.cursor = mv.on ? 'grab' : ''; vtoolsShow();
    const b = new THREE.Box3().setFromObject(current); if (Math.max(Math.abs(b.min.x), Math.abs(b.max.x), Math.abs(b.min.y), Math.abs(b.max.y)) > PLATE_EDGE + .5) toast('Une pièce sort du plateau : rapproche-la avant d\'imprimer.');
  };
  dom.addEventListener('pointerup', end); dom.addEventListener('pointercancel', end);
}
$('vtools').querySelector('[data-vt="move"]').onclick = () => setMove(!mv.on);
$('pc-size').oninput = () => { $('pc-pct').value = $('pc-size').value; pieceResize($('pc-size').value); };
$('pc-pct').onchange = () => pieceResize($('pc-pct').value);
document.querySelectorAll('[data-pc]').forEach(b => b.onclick = () => pieceResize(b.dataset.pc));
$('pc-close').onclick = () => pieceSelect(-1);
/* one piece leaves the plate: the server writes a new model with the others, keeping places and sizes */
$('pc-del').onclick = async () => {
  const k = mv.sel, base = mv.file; if (k < 0 || !base || base !== sel?.name || $('pc-del').disabled) return;
  if (!confirm(`Retirer « ${nice(mv.ranges[k]?.name || `pièce ${k + 1}`)} » du plateau ? Un nouveau modèle sera créé sans elle ; l'original reste dans la bibliothèque.`)) return;
  $('pc-del').disabled = true;
  try {
    const r = await api(`/models/${encodeURIComponent(base)}/retirer`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: k, moves: mv.moves, scales: mv.scales }) });
    await loadFiles();
    const f = files.find(x => x.name === r.name); if (f) await select(f);
    toast('Pièce retirée du plateau. Le modèle d\'origine reste dans la bibliothèque.', 'ok');
  } catch (e) { toast('Impossible de retirer la pièce : ' + e.message, 'bad'); $('pc-del').disabled = false; }
};
/* the chat's precise target: with Cibler on, a click on the model drops a marker that follows the piece
   (it is parented to it) and the clicked co-ordinates — the file's own axes as loaded — go with the message */
const cible = { on: false, pt: null, marker: null };
function cibleMark(local) {
  if (!cible.marker) {
    cible.marker = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0xff8a3c, transparent: true, opacity: 0.45, depthTest: false }));
    cible.marker.renderOrder = 20;
  }
  cible.marker.position.copy(local);
  if (cible.marker.parent !== current) { cible.marker.removeFromParent(); current.add(cible.marker); }
  cible.marker.scale.setScalar(+$('chat-zone-r').value || 10);
  renderOnce();
}
const CHAT_ASK = 'Ex. : perce un trou de 6 mm pour un aimant en haut';
const CHAT_HERE = 'Que faire à cet endroit ? (ex. : un trou de 6 mm ici, arrondir, renforcer)';
function setCible(on) {
  if (on && mesure.on) setMesure(false);   // one pick tool at a time
  cible.on = on && !!current;
  $('vtools').querySelector('[data-vt="cible"]').classList.toggle('on', cible.on);
  stage.style.cursor = cible.on ? 'crosshair' : stage.style.cursor;
  $('chat-in').placeholder = cible.on ? CHAT_HERE : CHAT_ASK;   // the input asks the right question
  if (!cible.on) {
    cible.pt = null; $('chat-zone').hidden = true;
    if (cible.marker) { cible.marker.removeFromParent(); cible.marker = null; renderOnce(); }   // dies with its model
  }
}
$('vtools').querySelector('[data-vt="cible"]').onclick = () => setCible(!cible.on);
$('chat-zone-x').onclick = () => setCible(false);
$('chat-zone-r').oninput = () => { if (cible.marker) { cible.marker.scale.setScalar(+$('chat-zone-r')?.value || 10); renderOnce(); } };
/* measuring by hand: two picked points on the model, the distance between them in the file's own mm.
   The dots and the line are parented to the model (like the Cibler marker), so they follow the piece. */
const mesure = { on: false, grp: null, a: new THREE.Vector3(), b: null };   // b is set once both points are picked
const MESURE_COL = 0x00cfd4;
function mesureClear() {
  const g = mesure.grp;
  if (g) { g.removeFromParent(); g.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); }); }
  mesure.grp = null; mesure.b = null; $('vmeas').hidden = true; renderOnce();
}
function setMesure(on) {
  $('vtools').querySelector('[data-vt="mesure"]').classList.toggle('on', on);
  if (on && paint) return;                       // while painting, a click paints: not both at once
  mesure.on = on && !!current;
  stage.style.cursor = mesure.on ? 'crosshair' : stage.style.cursor;
  if (!mesure.on) { mesureClear(); return; }
  if (cible.on) setCible(false);
  toast('Touche deux points du modèle : la distance s\'affiche entre les deux. Reclique pour mesurer ailleurs.');
}
$('vtools').querySelector('[data-vt="mesure"]').onclick = () => setMesure(!mesure.on);
function mesurePick(local) {
  if (mesure.grp && mesure.grp.parent !== current) mesureClear();   // another view took the stage
  if (mesure.grp && mesure.b) { mesureClear(); }              // a measure is done: this click starts the next one
  if (!mesure.grp) {                                          // first point: dots and line in a group on the model
    mesure.a = local.clone();
    mesure.grp = new THREE.Group();
    const s = new THREE.Box3().setFromObject(current).getSize(new THREE.Vector3()).length() * 0.008 || 2;
    const mat = { color: MESURE_COL, depthTest: false, transparent: true, opacity: .9 };
    const dot = v => { const d = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 8), new THREE.MeshBasicMaterial(mat));
                       d.position.copy(v); d.scale.setScalar(s); d.renderOrder = 19; return d; };
    mesure.dotB = dot(local); mesure.dotB.visible = false;
    mesure.line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([mesure.a, mesure.a]),
                                 new THREE.LineBasicMaterial({ ...mat, opacity: .85 }));
    mesure.line.renderOrder = 19;
    mesure.grp.add(dot(mesure.a), mesure.dotB, mesure.line);
    current.add(mesure.grp);                                  // follows the piece like the Cibler marker
    $('vmeas').textContent = '2e point ?'; $('vmeas').hidden = false;
  } else {                                                    // second point: the line is complete, show the distance
    mesure.b = local.clone(); mesure.dotB.visible = true;
    mesure.line.geometry.dispose();
    mesure.line.geometry = new THREE.BufferGeometry().setFromPoints([mesure.a, mesure.b]);
    const d = mesure.a.distanceTo(mesure.b);
    $('vmeas').textContent = `${d.toFixed(1).replace('.', ',')} mm`;
  }
  mesureUpd(); renderOnce();
}
// the chip sits over the middle of the line (first point alone: over the first dot)
function mesureUpd() {
  const el = $('vmeas');
  if (!mesure.on || !mesure.grp || !current) { el.hidden = true; return; }
  current.updateMatrixWorld();
  const p = (mesure.b ? mesure.a.clone().add(mesure.b) : mesure.a.clone().multiplyScalar(2)).multiplyScalar(.5)
    .applyMatrix4(current.matrixWorld).project(cam);
  el.style.left = `${((p.x + 1) / 2) * stage.clientWidth}px`;
  el.style.top = `${(1 - (p.y + 1) / 2) * stage.clientHeight}px`;
}
if (renderer) {   // a click that is not a drag picks a point, exactly like Cibler
  let mdown = null;
  const dom = renderer.domElement;
  dom.addEventListener('pointerdown', e => { mdown = mesure.on && e.button === 0 ? [e.clientX, e.clientY] : null; });
  dom.addEventListener('pointerup', e => {
    if (!mesure.on || !mdown || e.button !== 0 || !current) { mdown = null; return; }
    const dragged = Math.hypot(e.clientX - mdown[0], e.clientY - mdown[1]); mdown = null;
    if (dragged > 5) return;                                  // an orbit, not a pick
    const r = dom.getBoundingClientRect();
    ptr.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, cam);
    const hit = ray.intersectObject(current, true)[0]; if (!hit) return;
    mesurePick(current.worldToLocal(hit.point.clone()));
  });
}
if (renderer) {
  const dom = renderer.domElement;
  let down = null;
  const spot = e => { const r = dom.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  dom.addEventListener('pointerdown', e => { down = cible.on && e.button === 0 && current ? spot(e) : null; });
  dom.addEventListener('pointerup', e => {
    if (!cible.on || !down || !current) return;
    const at = spot(e), w = down[0] === undefined ? 99 : Math.hypot(at[0] - down[0], at[1] - down[1]); down = null;
    if (w > 5) return;                                    // an orbit drag, not a pick
    const r = dom.getBoundingClientRect();
    ptr.set(at[0] / r.width * 2 - 1, -(at[1] / r.height * 2) + 1);
    ray.setFromCamera(ptr, cam);
    const hit = ray.intersectObject(current, true)[0]; if (!hit) return;
    const local = current.worldToLocal(hit.point.clone());
    // the GLB viewer holds the model Y-up: back to the file's own axes (x, y, z)
    const pt = [+local.x.toFixed(1), +(-local.z).toFixed(1), +local.y.toFixed(1)];
    cible.pt = pt;
    cibleMark(local);
    $('chat-zone-txt').textContent = `Zone ciblée : (${pt.join(', ')}) mm — l'assistant la recevra avec le prochain message`;
    $('chat-zone').hidden = false;
  });
}
/* another library piece on this plate: the server writes a new model holding both, side by side */
function renderAddp() {
  const q = $('addp-q').value.toLowerCase();
  const list = files.filter(f => f.name !== sel?.name && !['gcode'].includes(f.ext) && f.kind !== 'technique' && (!q || f.name.toLowerCase().includes(q)))
    .sort((a, b) => b.mtime - a.mtime).slice(0, 200);
  $('addp-list').innerHTML = list.length ? list.map(f => `<div class="asm-row addp-row" role="button" tabindex="0" data-addp="${esc(f.name)}">
    <img class="fthumb" loading="lazy" alt="" src="/lab/api/models/${encodeURIComponent(f.name)}/thumb.png?v=${Math.round(f.mtime)}" onerror="this.style.visibility='hidden'">
    <span class="fname" title="${esc(f.name)}">${esc(pretty(f.name))}</span><span class="note" style="margin:0">${f.ext.toUpperCase()}</span></div>`).join('')
    : '<p class="note" style="padding:10px">Aucune pièce ne correspond.</p>';
  $('addp-list').querySelectorAll('[data-addp]').forEach(r => {
    r.onclick = () => addToPlate(r.dataset.addp);
    r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); addToPlate(r.dataset.addp); } };
  });
}
$('vtools').querySelector('[data-vt="add"]').onclick = () => {
  if (!sel) return;
  $('addp-base').textContent = pretty(sel.name); $('addp-q').value = ''; renderAddp(); $('addp').showModal();
};
let addpTimer = 0;
$('addp-q').oninput = () => { clearTimeout(addpTimer); addpTimer = setTimeout(renderAddp, 150); };
async function addToPlate(name) {
  const base = sel?.name; if (!base) return;
  $('addp').close(); toast('Mise en place des deux pièces sur un plateau…');
  try {
    const r = await api('/composer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names: [base, name] }) });
    await loadFiles();
    const f = files.find(x => x.name === r.name); if (f) await select(f);
    toast(`Plateau prêt : ${r.pieces} pièces. Avec « Déplacer », touche une pièce pour la placer ou changer sa taille.`, 'ok');
  } catch (e) { toast('Impossible de les mettre ensemble : ' + e.message, 'bad'); }
}
$('vtools').querySelector('[data-vt="regroup"]').onclick = () => {
  mv.moves = {}; mv.scales = {}; renderRot(); pieceSelect(mv.sel); vtoolsShow(); sizeNote();
};
/* colour touch-up: a brush repaints faces with one of the model's own colours; saved beside the model */
let paint = null;   // { mode, mesh, geo, pos, nor, col, orig, centres, hex, rgb, strokes, dirty, brush, down, busy }
const ray = renderer ? new THREE.Raycaster() : null, ptr = new THREE.Vector2();
// marks painted for the slicer (supports, seam), shown in these colours while painting; '' = eraser
const MARKS = [{ kind: 'support', hex: '#2ECC71', label: 'Support ici' }, { kind: 'sans_support', hex: '#E5484D', label: 'Jamais de support ici' },
  { kind: 'couture', hex: '#3B82F6', label: 'Couture ici (début de chaque couche)' }, { kind: '', hex: '', label: 'Gomme' }];
const vtFor = mode => $('vtools').querySelector(mode === 'marks' ? '[data-vt="marks"]' : '[data-vt="paint"]');
// the colours of the spools loaded in the CANVAS right now, one per slot: the brush paints with them too
async function canvasColours() {
  try {
    return (await api('/canvas/bobines')).filter(t => /^#[0-9A-Fa-f]{6}$/.test(t.hex || ''))
      .map(t => ({ slot: +t.slot || 1, hex: String(t.hex).toUpperCase(), name: t.name || '' }));
  } catch {   // printer away: the last spools read at match time
    return Object.values(trays || {}).filter(t => t?.hex)
      .map(t => ({ slot: +t.slot || 1, hex: String(t.hex).toUpperCase(), name: t.name || '' }));
  }
}
async function paintOn(mode = 'colour') {
  if (mesure.on) setMesure(false);   // left button paints, not measured
  const mesh = (() => { let m = null; current?.traverse(o => { if (o.isMesh && !m) m = o; }); return m; })();
  const geo = mesh?.geometry;
  if (!geo?.attributes.color || geo.index) return toast('Ce modèle ne peut pas être retouché au pinceau (aperçu indisponible).', 'bad');
  const pos = geo.attributes.position, n = pos.count / 3, centres = new Float32Array(n * 3);
  for (let f = 0; f < n; f++) for (let k = 0; k < 3; k++) centres[f * 3 + k] = (pos.getComponent(3 * f, k) + pos.getComponent(3 * f + 1, k) + pos.getComponent(3 * f + 2, k)) / 3;
  geo.computeBoundingSphere();
  const brush = new THREE.Mesh(new THREE.SphereGeometry(1, 18, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: .28, depthWrite: false }));
  brush.visible = false; scene.add(brush);
  const col = geo.attributes.color;
  /* one colour: the part is shown in its spool's flat colour, so face paint is invisible on screen;
     while painting, show the vertices instead, seeded with the flat colour the user already sees */
  let flat = null;
  if (mesh.material && !mesh.material.vertexColors) {
    flat = '#' + mesh.material.color.getHexString();
    const fc = [1, 3, 5].map(i => parseInt(flat.slice(i, i + 2), 16) / 255);
    for (let v = 0; v < pos.count; v++) col.setXYZ(v, fc[0], fc[1], fc[2]);
    mesh.material.vertexColors = true; mesh.material.color.set(0xffffff); mesh.material.needsUpdate = true;
  }
  paint = { mode, mesh, geo, pos, nor: geo.attributes.normal, col, orig: mode === 'marks' ? col.clone() : null, centres, hex: null, flat,
            strokes: [], dirty: new Map(), brush, down: false, busy: false, hit: null };
  controls.mouseButtons.LEFT = -1; controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;   // left paints, right turns
  controls.touches.ONE = -1; controls.touches.TWO = THREE.TOUCH.DOLLY_ROTATE;
  stage.classList.add('painting'); $('paintbar').hidden = false; vtFor(mode).classList.add('on');
  $('paintbar').setAttribute('aria-label', mode === 'marks' ? 'Supports et couture au pinceau' : 'Retouche des couleurs');
  $('pb-reset').title = mode === 'marks' ? 'Efface toutes les zones peintes (supports, couture)' : 'Remet les couleurs d\'origine du modèle';
  camTo('iso'); paintView();
  const swatches = mode === 'marks' ? MARKS.map(m => ({ key: m.kind, hex: m.hex, label: m.label }))
    : analysis.colours.map(c => ({ key: c.hex, hex: c.hex, label: `Peindre en ${c.hex}` }));
  const renderSw = () => {
    $('pb-sw').innerHTML = swatches.map(w => `<button data-key="${w.key}" class="${w.hex ? '' : 'erase'}" style="${w.hex ? `background:${w.hex}` : ''}" title="${esc(w.label)}" aria-label="${esc(w.label)}" role="radio" aria-checked="false">${w.hex ? '' : '<svg class="i"><use href="#i-x"/></svg>'}</button>`).join('');
    $('pb-sw').querySelectorAll('button').forEach(b => b.onclick = () => pickBrush(b.dataset.key));
  };
  renderSw(); pickBrush(swatches[0].key); paintButtons();
  if (mode === 'colour') {   // the CANVAS's own spool colours are brush choices too, added once read
    const have = new Set(swatches.map(s => String(s.hex).toUpperCase()));
    for (const t of await canvasColours())
      if (!have.has(t.hex)) { swatches.push({ key: t.hex, hex: t.hex, label: `Peindre en ${t.hex} · Bobine ${t.slot}${t.name ? ' ' + t.name : ''}` }); have.add(t.hex); }
    if (paint) { renderSw(); pickBrush(paint.hex); }   // keep the brush already picked
  }
  if (mode === 'marks') {   // show what is already painted
    try {
      const saved = await api(`/models/${encodeURIComponent(sel.name)}/marks`), P = paint;
      if (paint !== P) return;
      for (const m of MARKS.filter(x => x.kind)) {
        const [r, g, b] = [1, 3, 5].map(i => parseInt(m.hex.slice(i, i + 2), 16) / 255);
        for (const f of saved[m.kind] || []) for (let k = 0; k < 3; k++) col.setXYZ(3 * f + k, r, g, b);
      }
      col.needsUpdate = true; renderOnce();
    } catch { /* nothing painted yet */ }
  }
}
function pickBrush(key) {
  const mark = paint.mode === 'marks' ? MARKS.find(m => m.kind === key) : null, hex = mark ? mark.hex : key;
  paint.hex = key; paint.rgb = hex ? [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255) : null;   // null: the eraser
  paint.brush.material.color.set(hex || 0xffffff);   // the brush cursor shows the chosen colour on the model
  $('pb-sw').querySelectorAll('button').forEach(b => { const on = b.dataset.key === key; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
}
function paintOff(keep) {
  if (!paint) return;
  if (paint.flat) {   // back to the spool's flat colour (one-colour part)
    paint.mesh.material.vertexColors = false; paint.mesh.material.color.set(paint.flat); paint.mesh.material.needsUpdate = true;
  }
  scene.remove(paint.brush); renderOnce(); paint.brush.geometry.dispose(); paint.brush.material.dispose();
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE; controls.mouseButtons.RIGHT = THREE.MOUSE.PAN; controls.touches.ONE = THREE.TOUCH.ROTATE; controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  stage.classList.remove('painting'); $('paintbar').hidden = true; vtFor(paint.mode).classList.remove('on');
  paintView();
  const redraw = paint.dirty.size || paint.mode === 'marks'; paint = null;
  if (redraw && !keep && sel) { previewKey = ''; preview(sel, mapString()); }    // drop the unsaved strokes, or the marks' colours
}
// while painting, centre the picture in the free space above the brush bar (it covers the bottom of the view on a phone)
function paintView() {
  const bar = $('paintbar'), w = stage.clientWidth, h = stage.clientHeight;
  const cover = paint && !bar.hidden && w ? Math.max(0, stage.getBoundingClientRect().bottom - bar.getBoundingClientRect().top) : 0;
  if (cover > h * 0.15) cam.setViewOffset(w, h, 0, cover / 2, w, h); else cam.clearViewOffset();
  renderOnce();
}
function paintButtons() { $('pb-undo').disabled = !paint?.strokes.length; $('pb-save').disabled = !paint?.dirty.size; }
function paintHit(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, cam);
  return ray.intersectObject(paint.mesh, false)[0] || null;
}
function dab(hit, stroke) {
  const P = paint, inv = new THREE.Matrix4().copy(P.mesh.matrixWorld).invert(), local = hit.point.clone().applyMatrix4(inv);
  const R = P.geo.boundingSphere.radius * $('pb-size').value / 50, R2 = R * R, c = P.centres, n = c.length / 3;
  const hn = hit.face.normal, nor = P.nor, rgb = P.rgb, orig = P.orig;
  for (let f = 0; f < n; f++) {
    const dx = c[3 * f] - local.x, dy = c[3 * f + 1] - local.y, dz = c[3 * f + 2] - local.z;
    if (stroke.seen.has(f)) continue;
    if (f !== hit.faceIndex) {      // the face under the brush is always painted, even on a coarse mesh
      if (dx * dx + dy * dy + dz * dz > R2) continue;
      if (nor.getX(3 * f) * hn.x + nor.getY(3 * f) * hn.y + nor.getZ(3 * f) * hn.z < 0.25) continue;   // not through thin walls
    }
    stroke.seen.add(f); stroke.faces.push(f);
    stroke.old.push(P.col.getX(3 * f), P.col.getY(3 * f), P.col.getZ(3 * f), P.dirty.get(f) || null);
    for (let k = 0; k < 3; k++) {
      const v = 3 * f + k;
      if (rgb) P.col.setXYZ(v, rgb[0], rgb[1], rgb[2]); else P.col.setXYZ(v, orig.getX(v), orig.getY(v), orig.getZ(v));
    }
    P.dirty.set(f, P.hex);
  }
  P.col.needsUpdate = true; paintButtons(); renderOnce();
}
function paintMove(ev) {
  if (!paint || paint.busy) return;
  paint.busy = true;
  requestAnimationFrame(() => {
    if (!paint) return;
    paint.busy = false;
    const hit = paintHit(ev);
    paint.brush.visible = !!hit;
    renderOnce();
    if (!hit) return;
    const sc = new THREE.Vector3().setFromMatrixScale(paint.mesh.matrixWorld).x;
    paint.brush.position.copy(hit.point); paint.brush.scale.setScalar(paint.geo.boundingSphere.radius * $('pb-size').value / 50 * sc);
    if (paint.down) dab(hit, paint.strokes[paint.strokes.length - 1]);
  });
}
function paintUndo() {
  const s = paint?.strokes.pop(); if (!s) return;
  s.faces.forEach((f, i) => {
    const [r, g, b, h] = s.old.slice(4 * i, 4 * i + 4);
    for (let k = 0; k < 3; k++) paint.col.setXYZ(3 * f + k, r, g, b);
    if (h) paint.dirty.set(f, h); else paint.dirty.delete(f);
  });
  paint.col.needsUpdate = true; paintButtons(); renderOnce();
}
async function paintSave(clear = false) {
  if (paint?.mode === 'marks') return marksSave(clear);
  const body = clear ? { clear: true } : { paint: {} };
  if (!clear) paint.dirty.forEach((h, f) => (body.paint[h] ||= []).push(f));
  try {
    const r = await api(`/models/${encodeURIComponent(sel.name)}/retouch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast(clear ? 'Couleurs d\'origine rétablies' : `Retouche enregistrée (${r.retouched} faces)`, 'ok');
    paintOff(true); previewKey = ''; select(sel);
  } catch (e) { toast('Retouche impossible : ' + e.message, 'bad'); }
}
if (renderer) {
  const dom = renderer.domElement;
  dom.addEventListener('pointerdown', ev => {
    if (!paint || ev.button !== 0) return;
    paint.down = true; dom.setPointerCapture?.(ev.pointerId);
    paint.strokes.push({ faces: [], old: [], seen: new Set() });
    const hit = paintHit(ev); if (hit) dab(hit, paint.strokes[paint.strokes.length - 1]);
  });
  dom.addEventListener('pointermove', paintMove);
  const up = () => { if (paint) { paint.down = false; if (paint.strokes.length && !paint.strokes[paint.strokes.length - 1].faces.length) paint.strokes.pop(); paintButtons(); } };
  dom.addEventListener('pointerup', up); dom.addEventListener('pointercancel', up);
  dom.addEventListener('contextmenu', ev => { if (paint) ev.preventDefault(); });
  $('vtools').querySelector('[data-vt="paint"]').onclick = () => paint ? paintOff() : paintOn();
  $('vtools').querySelector('[data-vt="marks"]').onclick = () => paint ? paintOff() : paintOn('marks');
  $('pb-undo').onclick = paintUndo; $('pb-save').onclick = () => paintSave();
  $('pb-close').onclick = () => { if (!paint?.dirty.size || confirm('Abandonner la retouche non enregistrée ?')) paintOff(); };
  $('pb-reset').onclick = () => { if (confirm(paint?.mode === 'marks' ? 'Effacer toutes les zones peintes (supports, couture) de ce modèle ?' : 'Effacer toutes les retouches de ce modèle ?')) paintSave(true); };
}
if (renderer) setInterval(() => { if (!document.hidden) vtoolsShow(); }, 700);   // cheap: follows whatever the stage shows

async function marksSave(clear) {
  const body = clear ? { clear: true } : { add: {}, erase: [] };
  if (!clear) paint.dirty.forEach((k, f) => { if (k) (body.add[k] ||= []).push(f); else body.erase.push(f); });
  try {
    const r = await api(`/models/${encodeURIComponent(sel.name)}/marks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const any = r.support || r.sans_support || r.couture;   // one fixed sentence: the English page translates it whole
    toast(clear || !any ? 'Zones peintes effacées'
      : `Faces enregistrées : ${r.support || 0} à soutenir, ${r.sans_support || 0} sans support, ${r.couture || 0} pour la couture. Prises en compte au tranchage.`, 'ok');
    paintOff(true); previewKey = ''; select(sel);
  } catch (e) { toast('Enregistrement impossible : ' + e.message, 'bad'); }
}

/* slicing preview: printed paths, layer by layer */
let paths = null, pathsFor = '';
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0)).buffer;
function setView(v) {
  document.querySelectorAll('#viewtabs [data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === v));
  $('layerbar').hidden = v !== 'paths'; $('chips').hidden = v === 'paths';
}
async function showPaths(name) {
  if (!renderer) return hint('Aperçu 3D indisponible', 'WebGL est désactivé dans ce navigateur.');
  setView('paths'); $('viewtabs').hidden = !sel || sel.ext === 'gcode';  // tabs only make sense for a model
  hint('Lecture du G-code…', ''); previewKey = '';
  let d;
  try { d = await api(`/models/${encodeURIComponent(name)}/paths`); } catch (e) { return hint('Aperçu du tranchage impossible', esc(e.message)); }
  const { group, parts } = buildPaths(d), nl = d.layers.length;
  dropCurrent();
  current = group; scene.add(group); $('hint').hidden = true;
  paths = { parts, layers: d.layers }; pathsFor = name;
  stopPlay(); $('layer').max = nl; $('layer').value = nl; drawLayers(); vtoolsShow();
  const box = new THREE.Box3().setFromObject(group), size = box.getSize(new THREE.Vector3()).length(), c = box.getCenter(new THREE.Vector3());
  controls.target.copy(c); cam.position.set(c.x + size * 1.1, c.y - size * 1.3, c.z + size * .8);
}
// the printed paths as lines, one part per kind (model, supports, tower) with where each layer starts
function buildPaths(d) {
  const seg = new Int16Array(b64(d.segments)), lay = new Uint16Array(b64(d.layer)), kind = new Uint8Array(b64(d.kind)), tool = new Uint8Array(b64(d.tool));
  const tools = (d.colours.length ? d.colours : ['#d7dbe2']).map(h => new THREE.Color(h));
  const fixed = [null, new THREE.Color('#F0A040'), new THREE.Color('#8a97a8')], k = 1 / d.scale, nl = d.layers.length;
  const group = new THREE.Group(), parts = [];
  for (let g = 0; g < 3; g++) {
    let n = 0; for (let i = 0; i < d.count; i++) if (kind[i] === g) n++;
    const pos = new Float32Array(n * 6), col = new Float32Array(n * 6), start = new Uint32Array(nl + 1);
    let j = 0;
    for (let i = 0; i < d.count; i++) {
      if (kind[i] !== g) continue;
      const z = d.layers[lay[i]], c = fixed[g] || tools[tool[i] % tools.length], o = j * 6;
      pos[o] = seg[i * 4] * k - 128; pos[o + 1] = seg[i * 4 + 1] * k - 128; pos[o + 2] = z;
      pos[o + 3] = seg[i * 4 + 2] * k - 128; pos[o + 4] = seg[i * 4 + 3] * k - 128; pos[o + 5] = z;
      col[o] = col[o + 3] = c.r; col[o + 1] = col[o + 4] = c.g; col[o + 2] = col[o + 5] = c.b;
      start[lay[i] + 1] = ++j;
    }
    for (let l = 1; l <= nl; l++) if (start[l] < start[l - 1]) start[l] = start[l - 1];
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true }));
    group.add(lines); parts.push({ lines, start });
  }
  return { group, parts };
}
function drawLayers() {
  if (!paths) return;
  const l = +$('layer').value, nl = paths.layers.length, vis = [$('show-model').checked, $('show-support').checked, $('show-tower').checked];
  const single = $('show-single').checked;
  paths.parts.forEach((p, g) => {
    p.lines.visible = vis[g];
    const from = single ? p.start[l - 1] * 2 : 0;
    p.lines.geometry.setDrawRange(from, p.start[l] * 2 - from);
  });
  $('lv').textContent = `Couche ${l} / ${nl} · Z ${paths.layers[l - 1]?.toFixed(2)} mm`;
  renderOnce();
}
$('layer').oninput = drawLayers;
['show-model', 'show-support', 'show-tower'].forEach(id => $(id).onchange = drawLayers);
$('show-single').onchange = () => { drawLayers(); if ($('show-single').checked) camTo('top'); };
let playTimer = 0;
function stopPlay() { clearInterval(playTimer); playTimer = 0; $('lplay').innerHTML = '<svg class="i"><use href="#i-play"/></svg>'; }
$('lplay').onclick = () => {
  if (playTimer) return stopPlay();
  const r = $('layer'); if (+r.value >= +r.max) r.value = 1;
  const step = Math.max(1, Math.round(+r.max / 240));            // about 10 s for the whole print
  $('lplay').innerHTML = '<svg class="i"><use href="#i-pause"/></svg>';
  playTimer = setInterval(() => {
    if (document.hidden) return;   // a hidden tab must not burn through the layers
    r.value = Math.min(+r.max, +r.value + step); drawLayers();
    if (+r.value >= +r.max) stopPlay();
  }, 40);
};
$('layer').addEventListener('pointerdown', stopPlay);
document.querySelectorAll('#viewtabs [data-view]').forEach(b => b.onclick = () => {
  if (b.dataset.view === 'paths' && lastGcode) showPaths(lastGcode);
  if (b.dataset.view === 'model' && sel) { setView('model'); previewKey = ''; preview(sel, mapString()); }
});
let lastGcode = '';

/* library */
let libView = 'tout', libSort = 'date', libTech = false, libSelect = null, onPrinter = new Set();
try { libView = localStorage.getItem('cc2-lib-view') || 'tout'; libSort = localStorage.getItem('cc2-lib-sort') || 'date'; } catch {}
async function loadFiles() {
  files = await api('/models');
  fetch('/files').then(r => r.ok ? r.json() : null).then(d => {   // what is already on the printer
    const l = d && (d.file_list || d.files || (Array.isArray(d) ? d : null));
    if (l) { onPrinter = new Set(l.map(x => x.filename || x.name)); renderFiles(); }
  }).catch(() => {});
  renderFiles();
}
const shortT = t => t ? shortTime(t).replace(/(\d+) h (\d+)/, '$1 h $2') : '';
const day = m => new Date(m * 1000).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
// a name to read: no generation timestamp, no extension, spaces for underscores (the file name stays in the tooltip)
const pretty = nice;
function renderFiles() {
  const q = $('q').value.toLowerCase();
  const sorters = { date: (a, b) => b.mtime - a.mtime, nom: (a, b) => a.name.localeCompare(b.name, 'fr'), taille: (a, b) => b.size - a.size };
  const list = files.filter(f => (f.name + ' ' + (f.source || '')).toLowerCase().includes(q)).sort(sorters[libSort]);
  const tech = list.filter(f => f.kind === 'technique');
  $('lib-tech-n').textContent = tech.length ? `(${tech.length})` : '';
  document.querySelectorAll('#lib-view [data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === libView));
  $('lib-sort').value = libSort; $('lib-tech').checked = libTech;
  const models = list.filter(f => f.kind === 'modele'), ready = list.filter(f => f.kind === 'gcode');
  const thumb = f => `<img class="fthumb" loading="lazy" alt="" src="/lab/api/models/${encodeURIComponent(f.name)}/thumb.png?v=${Math.round(f.mtime)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ficon ${f.ext}',textContent:'${f.ext}'}))">`;
  const sub = f => f.kind === 'gcode'
    ? [shortT(f.temps), f.g ? fmtG(f.g) : '', f.eur ? euro(f.eur) : ''].filter(Boolean).join(' · ')
      + (f.couleurs?.length ? `<span class="fdots">${f.couleurs.map(c => `<i style="background:${c}"></i>`).join('')}</span>` : '')
      + (onPrinter.has(f.name) ? '<span class="fbadge cc2" title="Déjà envoyé sur l\'imprimante">sur la CC2</span>' : '')
    : `${size(f.size)} · ${day(f.mtime)}` + (f.prets ? `<span class="fbadge" title="G-code prêts pour ce modèle">${f.prets} prêt${f.prets > 1 ? 's' : ''}</span>` : '');
  const row = f => `<div class="file ${sel?.name === f.name ? 'sel' : ''}" data-n="${esc(f.name)}" tabindex="0">
    ${libSelect ? `<input type="checkbox" class="fcheck" ${libSelect.has(f.name) ? 'checked' : ''} aria-label="Sélectionner ${esc(f.name)}">` : ''}${thumb(f)}
    <div class="fmeta"><div class="fname" title="${esc(f.name)}">${esc(f.kind === 'gcode' && f.piece ? f.piece : pretty(f.name))}</div><div class="fsub">${f.kind === 'gcode' ? '' : `<span class="fext">${esc(f.ext.toUpperCase())}</span>`}${sub(f)}</div></div></div>`;
  let html = '';
  if (libView !== 'prets' && models.length) html += '<div class="group">Modèles</div>' + models.map(row).join('');
  if (libView !== 'modeles' && ready.length) {
    if (libView === 'prets') {   // grouped under the model they come from
      const groups = new Map();
      for (const f of ready) { const k = f.source || ''; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(f); }
      for (const [src, l] of groups) html += `<div class="group src" title="${esc(src)}">${src ? '↳ ' + esc(src) : 'Autres G-code'} <small>· ${l.length}</small></div>` + l.map(row).join('');
    } else html += '<div class="group">Prêts à imprimer</div>' + ready.map(row).join('');
  }
  if (libTech && tech.length) html += '<div class="group">Fichiers techniques <small>· conversions, pièces découpées</small></div>' + tech.map(row).join('');
  $('files').innerHTML = html || `<div class="empty">${q ? 'Aucun résultat.' : libView === 'prets' ? 'Aucun G-code : tranche un modèle.' : 'Aucun fichier. Dépose un modèle au-dessus.'}</div>`;
  $('files').querySelectorAll('.file').forEach(el => {
    el.onclick = ev => {
      if (libSelect) { const n = el.dataset.n; libSelect.has(n) ? libSelect.delete(n) : libSelect.add(n); renderFiles(); bulkBar(); return; }
      select(files.find(f => f.name === el.dataset.n));
    };
    el.onkeydown = e => { if (e.key === 'Enter') el.click(); };
  });
}
function bulkBar() { $('lib-bulk').hidden = !libSelect; if (libSelect) $('bulk-n').textContent = `${libSelect.size} sélectionné${libSelect.size > 1 ? 's' : ''}`; }
document.querySelectorAll('#lib-view [data-view]').forEach(b => b.onclick = () => { libView = b.dataset.view; try { localStorage.setItem('cc2-lib-view', libView); } catch {} renderFiles(); });
$('lib-sort').onchange = () => { libSort = $('lib-sort').value; try { localStorage.setItem('cc2-lib-sort', libSort); } catch {} renderFiles(); };
$('lib-more').onclick = ev => { ev.stopPropagation(); $('lib-menu').hidden = !$('lib-menu').hidden; };
document.addEventListener('click', ev => { if (!ev.target.closest('#lib-menu')) $('lib-menu').hidden = true; });
$('lib-tech').onchange = () => { libTech = $('lib-tech').checked; renderFiles(); };
$('lib-menu').querySelector('[data-act="select"]').onclick = () => { $('lib-menu').hidden = true; libSelect = new Set(); renderFiles(); bulkBar(); };
$('bulk-cancel').onclick = () => { libSelect = null; renderFiles(); bulkBar(); };
$('bulk-all').onclick = () => { $('files').querySelectorAll('.file').forEach(el => libSelect.add(el.dataset.n)); renderFiles(); bulkBar(); };
$('bulk-del').onclick = async () => {
  if (!libSelect.size || !confirm(`Supprimer ${libSelect.size} fichier${libSelect.size > 1 ? 's' : ''} de la bibliothèque ? C'est définitif.`)) return;
  const r = await api('/library/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names: [...libSelect] }) }).catch(e => (toast(e.message, 'bad'), null));
  if (r) toast(`${r.deleted.length} fichier${r.deleted.length > 1 ? 's' : ''} supprimé${r.deleted.length > 1 ? 's' : ''}`, 'ok');
  if (sel && libSelect.has(sel.name)) clearSelection();
  libSelect = null; bulkBar(); loadFiles();
};
$('lib-menu').querySelector('[data-act="clean"]').onclick = async () => {
  $('lib-menu').hidden = true;
  const list = await api('/library/cleanup').catch(() => []);
  $('clean-list').innerHTML = list.length ? list.map((c, i) => `<label class="clean-row"><input type="checkbox" data-clean="${i}" checked><span>${esc(c.name)}<small>${esc(c.raison)}</small></span><span class="note">${size(c.size)}</span></label>`).join('')
    : '<div class="empty">Rien à nettoyer : la bibliothèque est propre.</div>';
  const sum = () => { const n = [...$('clean-list').querySelectorAll('[data-clean]:checked')].map(el => list[+el.dataset.clean]);
    $('clean-sum').textContent = n.length ? `${n.length} fichier${n.length > 1 ? 's' : ''} · ${size(n.reduce((a, c) => a + c.size, 0))}` : ''; $('clean-go').disabled = !n.length; };
  $('clean-list').querySelectorAll('[data-clean]').forEach(el => el.onchange = sum); sum();
  $('clean-go').onclick = async () => {
    const names = [...$('clean-list').querySelectorAll('[data-clean]:checked')].map(el => list[+el.dataset.clean].name);
    const r = await api('/library/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names }) }).catch(e => (toast(e.message, 'bad'), null));
    if (r) toast(`Ménage fait : ${r.deleted.length} fichier${r.deleted.length > 1 ? 's' : ''} supprimé${r.deleted.length > 1 ? 's' : ''}`, 'ok');
    $('clean').close(); loadFiles();
  };
  $('clean').showModal();
};
document.querySelectorAll('[data-ren]').forEach(b => b.onclick = async () => {
  if (!sel) return;
  const stem = sel.name.replace(/\.[^.]+$/, ''), n = prompt('Nouveau nom :', stem);
  if (!n || n.trim() === stem) return;
  try {
    const r = await api('/models/' + encodeURIComponent(sel.name) + '/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: n.trim() }) });
    toast('Renommé en ' + r.name, 'ok'); await loadFiles(); select(files.find(f => f.name === r.name));
  } catch (e) { toast(e.message, 'bad'); }
});
// typing filters, not every keystroke rebuilds the whole library (thumbnails included)
let qTimer = 0;
$('q').oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(renderFiles, 150); };

/* a name added to a flat model, in a second colour */
$('add-text').onclick = () => { if (sel) { $('txt-v').value = ''; $('txt').showModal(); $('txt-v').focus(); } };
$('txt-go').onclick = async () => {
  const f = sel, v = $('txt-v').value.trim(), b = $('txt-go');
  if (!f || !v) return toast('Écris le texte à ajouter', 'bad');
  b.disabled = true; b.textContent = 'Ajout…';
  try {
    const r = await api('/models/' + encodeURIComponent(f.name) + '/texte', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texte: v, police: $('txt-font').value, angle: +$('txt-angle').value, taille: +$('txt-size').value || null }) });
    $('txt').close(); toast(`Texte ajouté (majuscules de ${r.capitales_mm} mm) : ${r.name}`, 'ok');
    await loadFiles(); select(files.find(x => x.name === r.name));
  } catch (e) { toast(e.message, 'bad'); }
  b.disabled = false; b.textContent = 'Ajouter';
};

/* a shape drilled through the model, added to it, or kept where both meet: placed by eye on the 3D view */
let shpGhost = null;
function shpValues() {
  const kind = $('shp-kind').value, op = $('shp-op').value, w = +$('shp-w').value || 5;
  return { forme: kind, operation: op, axe: kind === 'sphere' ? 'z' : $('shp-axis').value, couleur: +$('shp-col').value || 1,
           taille: [w, kind === 'cube' ? (+$('shp-d').value || w) : w, kind === 'sphere' ? w : (+$('shp-h').value || w)],
           position: [+$('shp-x').value || 0, +$('shp-y').value || 0, +$('shp-z').value || 0] };
}
function shpDraw() {
  const v = shpValues(), kind = v.forme;
  $('shp-w-l').textContent = kind === 'cube' ? 'Largeur (mm)' : 'Diamètre (mm)';
  $('shp-d-f').hidden = kind !== 'cube'; $('shp-h-f').hidden = kind === 'sphere'; $('shp-axis-f').hidden = kind === 'sphere';
  $('shp-h-f').querySelector('label').textContent = kind === 'cube' ? 'Hauteur (mm)' : 'Longueur (mm)';
  $('shp-col-f').hidden = v.operation !== 'ajouter';
  const mesh = pieceMesh(); if (!mesh || !renderer) return;
  if (shpGhost) { shpGhost.parent?.remove(shpGhost); shpGhost.geometry.dispose(); shpGhost.material.dispose(); }
  // the viewer's geometry is Y-up: the model's (x, y, z) is (x, z, -y) here; its length runs along Y like the model's Z
  const [w, d, h] = v.taille, geo = kind === 'cube' ? new THREE.BoxGeometry(w, h, d) : kind === 'sphere' ? new THREE.SphereGeometry(w / 2, 40, 24)
    : new THREE.CylinderGeometry(w / 2, w / 2, h, 48);
  shpGhost = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: v.operation === 'percer' ? 0xff5a4e : 0x4ea8ff, transparent: true, opacity: .45, depthWrite: false }));
  if (v.axe === 'x') shpGhost.rotation.z = Math.PI / 2; else if (v.axe === 'y') shpGhost.rotation.x = Math.PI / 2;
  mesh.geometry.computeBoundingBox();
  const c = mesh.geometry.boundingBox.getCenter(new THREE.Vector3()), [x, y, z] = v.position;
  shpGhost.position.set(c.x + x, c.y + z, c.z - y); shpGhost.renderOrder = 2;
  mesh.parent.add(shpGhost); renderOnce();
}
function shpClear() { if (shpGhost) { shpGhost.parent?.remove(shpGhost); shpGhost.geometry.dispose(); shpGhost.material.dispose(); shpGhost = null; renderOnce(); } }
$('add-shape').onclick = () => {
  if (!sel || sel.ext === 'gcode') return;
  const cols = analysis?.colours || [];
  $('shp-col').innerHTML = cols.map((c, i) => `<option value="${c.index}">Couleur ${i + 1} (${c.hex})</option>`).join('')
    + (cols.length < 4 ? `<option value="${Math.max(0, ...cols.map(c => c.index)) + 1}">Une nouvelle couleur (bobine suivante)</option>` : '');
  const box = pieceMesh()?.geometry; box?.computeBoundingBox();
  if (box) { const s = box.boundingBox.getSize(new THREE.Vector3()); $('shp-h').value = Math.ceil(s.y + 4); }   // through the whole height
  $('shp').showModal(); shpDraw();
};
$('shp').addEventListener('input', shpDraw); $('shp').addEventListener('change', shpDraw); $('shp').addEventListener('close', shpClear);
$('shp-go').onclick = async () => {
  const f = sel, b = $('shp-go'); if (!f) return;
  b.disabled = true; b.textContent = 'Calcul…';
  try {
    const r = await api('/models/' + encodeURIComponent(f.name) + '/forme', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(shpValues()) });
    $('shp').close(); toast(`Nouveau fichier : ${r.name} (${sizeTxt(r.size_mm, 1)})`, 'ok');
    await loadFiles(); select(files.find(x => x.name === r.name));
  } catch (e) { toast(e.message, 'bad'); }
  b.disabled = false; b.textContent = 'Créer le fichier';
};

async function upload(list) {
  const added = [];
  for (const file of list) {
    const fd = new FormData(); fd.append('file', file);
    try { const r = await api('/models', { method: 'POST', body: fd }); added.push(...(r.names || [r.name]));
      toast((r.names || []).length > 1 ? `${r.names.length} modèles ajoutés` : (r.name === file.name ? 'Ajouté : ' + r.name : `Ajouté sous le nom ${r.name} (le nom existait déjà)`), 'ok'); } catch (e) { toast(file.name + ' : ' + e.message, 'bad'); }
  }
  await loadFiles();
  if (added.length === 1) select(files.find(f => f.name === added[0]));
}
$('up').onchange = e => { upload([...e.target.files]); e.target.value = ''; };
$('link-open').onclick = () => { $('link-url').value = ''; $('link').showModal(); $('link-url').focus(); };
$('link-form').onsubmit = async e => {
  e.preventDefault();
  const go = $('link-go'); go.disabled = true; go.innerHTML = '<span class="spin"></span>Téléchargement…';
  try {
    const r = await api('/models/from-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: $('link-url').value }) });
    $('link').close(); toast(r.names.length > 1 ? `${r.names.length} modèles ajoutés` : 'Ajouté : ' + r.names[0], 'ok');
    await loadFiles(); if (r.names.length === 1) select(files.find(f => f.name === r.names[0]));
  } catch (err) { toast(err.message, 'bad'); }
  go.disabled = false; go.textContent = 'Importer';
};
const drop = $('drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove('over')));
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => { e.preventDefault(); if (e.dataTransfer.files.length) upload([...e.dataTransfer.files]); });

document.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
  if (!sel || !confirm(`Supprimer ${sel.name} de la bibliothèque ?`)) return;
  await api('/models/' + encodeURIComponent(sel.name), { method: 'DELETE' }).catch(e => toast(e.message, 'bad'));
  clearSelection();
  loadFiles();
});
function clearSelection() {
  sel = null; $('prep').hidden = $('ready').hidden = true; $('nosel').hidden = false; $('chips').innerHTML = '';
  chatFree();
  if (current) dropCurrent(); hint('Choisis un modèle dans la bibliothèque', 'Glisser pour tourner · molette pour zoomer');
  document.querySelectorAll('#mnav button[data-m="prep"]').forEach(b => b.disabled = true); $('mnext').hidden = true; mview('lib');   // « Aperçu » stays: the assistant lives there
}

/* selection */
const phone = matchMedia('(max-width: 860px)');
function mview(m) {
  $('lab').dataset.m = m;
  document.querySelectorAll('#mnav button').forEach(b => b.classList.toggle('on', b.dataset.m === m));
}
document.querySelectorAll('#mnav button').forEach(b => b.onclick = () => mview(b.dataset.m));
document.querySelectorAll('[data-lstep]').forEach(b => b.onclick = () => {
  const r = $('layer'); r.value = Math.min(+r.max, Math.max(+r.min, +r.value + +b.dataset.lstep)); r.dispatchEvent(new Event('input'));
});
$('mnext').onclick = () => { mview('prep'); $('lab').querySelector('.panel').scrollTop = 0; };
if (matchMedia('(pointer: coarse)').matches) $('hint').innerHTML = '<div><div class="big">Choisis un modèle dans la bibliothèque</div>Un doigt pour tourner · deux doigts pour zoomer</div>';
mview('lib');

async function select(f) {
  if (!f) return;
  paintOff(true); if (defects) { disposeObj(defects); defects = null; }
  document.querySelectorAll('#mnav button:not([data-m="lib"])').forEach(b => b.disabled = false);
  $('mnext').hidden = f.ext === 'gcode';
  if (phone.matches) mview(f.ext === 'gcode' ? 'prep' : 'view');
  sel = f; renderFiles(); setCible(false);   // a fresh model: the picked spot has no meaning any more
  $('nosel').hidden = true; $('result').innerHTML = ''; $('chips').innerHTML = '';
  lastGcode = ''; $('viewtabs').hidden = true; setView('model'); rotation = [0, 0, 0]; $('opt-res').innerHTML = ''; optUndo = null; $('mirror').checked = false; ['sx', 'sy', 'sz'].forEach(id => $(id).value = 100); renderRot();
  if (f.ext !== 'gcode') preview(f);
  if (f.ext === 'gcode') {
    lastGcode = f.name; showPaths(f.name);
    $('prep').hidden = true; $('ready').hidden = false; $('r-name').textContent = f.name;
    const USE = { decoratif: 'décoratif', fonctionnel: 'solide', detaille: 'détaillé', rapide: 'rapide', turbo: 'turbo', profil: 'profil Elegoo' };
    $('r-sub').innerHTML = [f.source ? 'depuis ' + esc(f.source) : 'tranché ailleurs', f.qualite, USE[f.usage], shortT(f.temps), f.g ? fmtG(f.g) : '', f.eur ? euro(f.eur) : '']
      .filter(Boolean).join(' · ') + (onPrinter.has(f.name) ? ' <span class="fbadge cc2">sur la CC2</span>' : '');
    $('r-body').innerHTML = sendBlock(f.name); bindSend(); return;
  }
  $('ready').hidden = true; $('prep').hidden = false;
  $('p-name').textContent = f.name; $('p-sub').textContent = 'Analyse du modèle…'; $('height').value = ''; $('h-now').textContent = '';
  $('c-note').textContent = 'Détection des couleurs…'; $('c-list').innerHTML = $('c-spools').innerHTML = '';
  needs = {}; stockLeft = {};
  $('chat-sec').hidden = false;
  $('chat-in').placeholder = $('chat-in').dataset.ph || $('chat-in').placeholder;
  if ($('chat-note').dataset.txt) $('chat-note').textContent = $('chat-note').dataset.txt;
  $('ia-note').hidden = true;
  if (chatSel !== f.name) { chatHist = []; $('chat-log').innerHTML = ''; chatConvNew(); $('chat-sug').hidden = false; }   // the conversation follows the model
  chatSel = f.name;
  const [inf, col] = await Promise.allSettled([api(`/models/${encodeURIComponent(f.name)}/info`), api(`/models/${encodeURIComponent(f.name)}/colors`)]);
  if (sel !== f) return;
  info = inf.status === 'fulfilled' ? inf.value : null;
  setUsage(info?.usage || savedUsage() || 'decoratif');
  showRetour(f, info?.retour);
  if (f.ext !== 'gcode') loadOrients(f);
  analysis = col.status === 'fulfilled' ? col.value : { colours: [{ index: 1, hex: '#C0C0C0', share: 100, slot: 1 }], source: 'inconnu' };
  mapping = Object.fromEntries(analysis.colours.map(c => [c.index, c.slot]));
  trays = {}; single = null; matched = null; colEdit = false; $('c-match').hidden = true;
  matchSpools(true);
  if (info?.size_mm) {
    const [x, y, z] = info.size_mm;
    $('p-sub').textContent = info.unitless ? 'Modèle IA sans unité réelle' : sizeTxt([x, y, z], 1).replace(/,0\b/g, '');
    $('h-now').textContent = info.unitless ? 'proposée : 60' : `actuelle : ${z}`;
    if (info.unitless) $('height').value = 60;
    sizeNote();
    $('chips').innerHTML = (info.unitless ? '<span class="chip">Taille d\'origine sans unité : 60 mm de haut proposés</span>' : `<span class="chip"><b>${sizeTxt([x, y, z], 1).replace(/,0\b/g, '')}</b></span>`)
      + (info.unitless ? '' : info.fits_bed ? '<span class="chip ok">Tient sur le plateau</span>' : '<span class="chip bad">Plus grand que le plateau (256 mm)</span>')
      + (info.watertight || !['glb', 'gltf', 'obj', 'ply', 'stl'].includes(f.ext) ? (info.watertight ? '' : '<span class="chip bad">Maillage non fermé</span>')
        : '<button class="chip bad" data-repair title="Créer une copie fermée, couleurs gardées">Maillage non fermé · <b>Réparer</b></button>');
    $('chips').querySelector('[data-repair]')?.addEventListener('click', e => repairModel(f, e.currentTarget));
  } else $('p-sub').textContent = f.ext.toUpperCase();
  renderColours();
}

function renderColours() {
  const cs = analysis.colours, multi = cs.length > 1;
  $('c-note').textContent = multi
    ? `${analysis.detected > cs.length ? `${analysis.detected} teintes regroupées en ${cs.length} couleurs` : `${cs.length} couleurs détectées`}. ${Object.keys(trays).length ? 'Chacune va sur la bobine chargée la plus proche, change-la d\'un clic si besoin' : 'Choisis la bobine CANVAS de chacune'}${cs.length > 4 ? ' (plus de 4 : certaines partagent une bobine)' : ''}.`
    : single ? 'Une seule couleur : la bobine du CANVAS est choisie, son filament est réglé.' : 'Une seule couleur. Choisis le filament.';
  const compact = !!matched && !colEdit, w = matched?.warnings || [];
  $('c-note').hidden = $('c-list').hidden = $('c-spools').hidden = compact;
  if (matched) {
    $('c-match').hidden = false;
    $('c-match').innerHTML = matched.line
      + (compact ? (w.length ? `<div class="warnline">⚠ ${w.length > 1 ? w.length + ' couleurs' : 'Une couleur'} sans bobine proche : la plus proche est utilisée.</div>` : '')
        : w.map(x => `<div class="warnline">⚠ ${esc(x)}</div>`).join(''))
      + `<button class="btn ghost c-edit" id="c-edit">${compact ? 'Modifier' : 'Réduire'}</button>`;
    $('c-edit').onclick = () => { colEdit = !colEdit; renderColours(); };
  }
  const bell = c => {   // the estimated need, next to the colour's share, red when the mapped spool holds less
    const g = needs[c.index], left = mapping[c.index] != null ? stockLeft[mapping[c.index]] : null;
    if (!g) return '';
    const low = left != null && left < g;
    return `<span class="pct" style="${low ? 'color:var(--bad);font-weight:600' : ''}" title="${low
      ? `besoin ~${g} g, il reste ~${Math.round(left)} g sur la bobine` : `besoin estimé : ~${g} g`}">~${g} g</span>`;
  };
  $('c-list').innerHTML = multi ? cs.map(c => `<div class="crow"><span class="sw" style="background:${c.hex}" title="${c.hex}"></span><span class="pct">${c.share} %</span>${bell(c)}
    <div class="slots" role="radiogroup" aria-label="Bobine pour ${c.hex}">${[1, 2, 3, 4].map(s => `<button class="slot ${mapping[c.index] === s ? 'on' : ''}" data-c="${c.index}" data-s="${s}" title="Bobine ${s}${trays[s] ? ' · ' + esc(trays[s].name) : ''}" role="radio" aria-checked="${mapping[c.index] === s}" ${trays[s] ? `style="background:${trays[s].hex}44;box-shadow:inset 0 -3px 0 ${trays[s].hex}"` : ''}>${s}</button>`).join('')}</div></div>`).join('') : '';
  $('c-list').querySelectorAll('.slot').forEach(b => b.onclick = () => { const c = +b.dataset.c; mapping[c] = +b.dataset.s;
    const h = (analysis.colours.find(x => x.index === c) || {}).hex;
    if (h) saveChoice(h, +b.dataset.s); renderColours(); });
  if (sel) preview(sel, mapString());
  const used = new Set(Object.values(mapping)), top = Math.max(...used);
  $('mode-box').hidden = top < 2;
  const opts = v => (cfg?.filaments || ['PLA']).map(x => `<option ${x === v ? 'selected' : ''}>${esc(x)}</option>`).join('');
  const left = s => { const g = stockLeft[s]; return g == null ? ''
    : `<div class="note" style="margin:3px 0 0${g < stockLow ? ';color:var(--bad)': ''}">il reste ~${Math.round(g)} g${g < stockLow ? ' · presque vide' : ''}</div>`; };
  // the swatch of each slot shows the model colour that prints from it
  const slotHex = s => trays[s]?.hex || cs.filter(c => mapping[c.index] === s).sort((a, b) => b.share - a.share)[0]?.hex || SLOT[s - 1];
  $('c-spools').innerHTML = (multi ? '<p class="note" style="margin-top:14px">Filament à charger dans chaque bobine</p>' : '')
    + Array.from({ length: top }, (_, i) => i + 1).map(s => `<div class="spool"><span class="tag" title="${esc(trays[s]?.name || '')}"><i style="background:${slotHex(s)}"></i>${single ? single.pos + 1 : s}</span>
      <div><select data-s="${s}" aria-label="Filament bobine ${s}">${opts(spools[s] || 'PLA')}</select>${trays[s] ? `<div class="note" style="margin:3px 0 0">chargée : ${esc(trays[s].name)}</div>` : ''}${trays[s] ? left(s) : ''}</div></div>`).join('')
    + ([...Array(top).keys()].some(i => !used.has(i + 1) && !trays[i + 1]) ? '<p class="note" style="margin-top:6px">Une bobine intermédiaire est inutilisée : elle doit quand même être chargée.</p>' : '');
  $('c-spools').querySelectorAll('select').forEach(s => { spools[s.dataset.s] = s.value; s.onchange = () => spools[s.dataset.s] = s.value; });
}

// the spool the user chose for a colour, remembered per model: applied again on every rematch
const choiceKey = () => sel ? 'cc2-cols:' + sel.name : '';
function savedChoices() { try { return JSON.parse(localStorage.getItem(choiceKey()) || '{}'); } catch { return {}; } }
function saveChoice(hex, slot) {
  if (!sel || !hex) return;
  try { const m = savedChoices(); m[hex] = { slot, tray: trays[slot]?.hex || null };
    localStorage.setItem(choiceKey(), JSON.stringify(m)); } catch { /* private browsing */ }
}
function keepChoices() {
  if (single || !analysis?.colours) return;
  const saved = savedChoices(), byHex = Object.fromEntries(Object.entries(trays).map(([s, t]) => [t.hex, +s]));
  for (const c of analysis.colours) {
    const ch = saved[c.hex]; if (!ch) continue;
    const s = (ch.tray && byHex[ch.tray]) || +ch.slot;   // the remembered spool if it is still loaded, else the remembered slot
    if (s >= 1 && s <= 4) mapping[c.index] = s;
  }
}

$('supports').onchange = () => { $('plate-row').hidden = $('supports').value === 'aucun'; };

/* print mode (multicolour only) */
const MODE_NOTE = {
  economie: 'Sans tour d\'essuyage, purge dosée selon les couleurs (bien plus forte vers le blanc) : le moins de filament sans mélange visible.',
  equilibre: 'Tour d\'essuyage et purge dosée : le plus net quand le modèle change souvent de couleur (gouttes et bavures essuyées sur la tour).',
  sans_purge: 'Aucune purge ni tour : le changement de couleur est juste le changement de bobine. Le plus économe et le plus rapide, mais un court mélange des deux couleurs apparaît après chaque changement. Essai à surveiller.',
  qualite: 'Tour d\'essuyage et purge maximale à chaque changement, quelles que soient les couleurs : le plus sûr, le plus de filament.',
};
let printMode = 'equilibre';   // quality first: the wipe tower; Économie is one click away
function renderMode() {
  document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('on', b.dataset.mode === printMode));
  $('mode-note').textContent = MODE_NOTE[printMode];
}
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { printMode = b.dataset.mode; renderMode(); });
renderMode();

/* too big for the bed? */
function rotatedSize([x, y, z]) {  // quarter turns about X, then Y, then Z swap the dimensions
  let d = [x, y, z];
  if (rotation[0] % 180) d = [d[0], d[2], d[1]];
  if (rotation[1] % 180) d = [d[2], d[1], d[0]];
  if (rotation[2] % 180) d = [d[1], d[0], d[2]];
  return d.map((v, i) => v * scale()[i]);
}
/* mirror and per-axis scale, along the plate's axes, after the turns (sent as rotate[3:6]) */
const scale = () => ['sx', 'sy', 'sz'].map(id => Math.max(1, +$(id).value || 100) / 100);
function xform() {
  const k = scale(); if ($('mirror').checked) k[0] = -k[0];
  return k.every(v => v === 1) ? rotation : [...rotation, ...k];
}
['mirror', 'sx', 'sy', 'sz'].forEach(id => $(id).addEventListener('change', () => { renderRot(); sizeNote(); }));
function sizeNote() {
  scheduleAdvice(); scheduleEstimate(); renderRot();
  if (!info?.size_mm) return;
  const sz = rotatedSize(info.size_mm), h = +$('height').value, z = sz[2] || 1, k = h ? h / z : 1, dims = sz.map(d => d * k), lim = 246;
  const n = dims.reduce((a, d) => a * Math.max(1, Math.ceil(d / lim)), 1);
  $('split-note').hidden = n < 2;
  $('split-note').innerHTML = n < 2 ? '' : `${sizeTxt(dims)} : plus grand que le plateau → <b>environ ${n} pièces</b>${$('split').checked ? ' · <a href="#" id="see-cut">voir la découpe</a>' : ' (découpe désactivée : le tranchage sera refusé)'}.`;
  const link = $('see-cut'); if (link) link.onclick = ev => { ev.preventDefault(); showCut(); };
}
const planTxt = p => `${p.axis} = ${p.mm} mm${p.angle ? ` (∠${p.angle > 0 ? '+' : ''}${p.angle}° → ${p.toward})` : ''}`;
async function showCut() {
  if (!sel) return;
  const q = `height=${+$('height').value || ''}&map=${encodeURIComponent(mapString())}&pal=${encodeURIComponent(palString())}`, f = sel;
  $('split-note').querySelector('#see-cut')?.replaceWith(Object.assign(document.createElement('span'), { textContent: 'calcul de la découpe…' }));
  try {
    const plan = await api(`/models/${encodeURIComponent(f.name)}/cut-plan?${q}`);
    if (sel !== f) return;
    $('split-note').innerHTML = `Coupes aux endroits les plus fins : ${plan.planes.map(planTxt).join(', ')} → <b>${plan.pieces.length} pièces</b>, ${plan.pins} chevilles. `
      + plan.pieces.map((p, i) => `Pièce ${i + 1} : ${sizeTxt(p.size_mm)}`).join(' · ') + ' · <a href="#" id="see-model">revoir le modèle</a>';
    $('see-model').onclick = ev => { ev.preventDefault(); previewKey = ''; preview(sel, mapString()); sizeNote(); };
    if (!renderer) return;
    const g = await new GLTFLoader().loadAsync(`/lab/api/models/${encodeURIComponent(f.name)}/cut-preview.glb?${q}`);
    g.scene.traverse(o => { if (o.isMesh) { o.geometry.computeVertexNormals(); o.material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .55 }); } });
    g.scene.rotation.x = Math.PI / 2; previewKey = 'cut';
    dropCurrent();
    show(g.scene); frame(g.scene);
  } catch (e) { $('split-note').textContent = 'Découpe impossible : ' + e.message; }
}
$('height').oninput = sizeNote; $('split').onchange = sizeNote;

/* large format: the plan is seen (coloured pieces, cut planes) before anything is sliced */
let gfKey = '';
function gfArgs() {
  const h = +$('gf-height').value;
  if (!h) throw new Error('indique la hauteur finale voulue');
  const zones = $('gf-zones').value.split(',').map(t => t.trim()).filter(Boolean).map(t => {
    const m = t.match(/^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)$/);
    if (!m) throw new Error(`zone illisible : « ${t} » (écris de-à en mm, ex. 150-190)`);
    return { axe: 'Z', de: +m[1].replace(',', '.'), a: +m[2].replace(',', '.') };
  });
  return { hauteur: h, interdites: zones, biais: $('gf-biais').checked, vision: $('gf-vision').checked };
}
const gfStale = () => { gfKey = ''; $('gf-slice').disabled = true; };
['gf-height', 'gf-zones', 'gf-biais', 'gf-vision'].forEach(id => $(id).addEventListener('input', gfStale));
$('gf-preview').onclick = async () => {
  const f = sel, out = $('gf-out');
  if (!f) return;
  try {
    const a = gfArgs(), q = `hauteur=${a.hauteur}&biais=${a.biais}&vision=${a.vision}&interdites=${encodeURIComponent(JSON.stringify(a.interdites))}`;
    out.textContent = a.vision ? 'l\'IA regarde le modèle et choisit les coupes… (environ une minute)' : 'calcul de la découpe…';
    const p = await api(`/models/${encodeURIComponent(f.name)}/grand-format?${q}`);
    if (sel !== f) return;
    out.innerHTML = `<b>${p.pieces.length} pièce${p.pieces.length > 1 ? 's' : ''}</b> pour ${sizeTxt(p.taille_mm)}, ${p.chevilles} cheville${p.chevilles > 1 ? 's' : ''}`
      + (p.plans.length ? ` · coupes : ${p.plans.map(x => `${x.axe} = ${x.mm} mm${x.angle ? ` (∠${x.angle > 0 ? '+' : ''}${x.angle}° → ${x.vers})` : ''}`).join(', ')}` : '')
      + `<ul>${p.pieces.map(x => `<li>${esc(x.nom)} : ${sizeTxt(x.taille_mm)}${x.pose ? ` · ${esc(x.pose)}` : ''}</li>`).join('')}</ul>`
      + (p.vision ? `<p class="note">${p.vision.utilisee ? 'Avis de l\'IA suivi' : 'Avis de l\'IA non suivi'} : ${esc(p.vision.commentaire || '')}</p>${p.vision.repli ? `<p class="w warn">${esc(p.vision.repli)}</p>` : ''}` : '')
      + p.alertes.map(x => `<p class="w ${x.bloquante ? 'bad' : 'warn'}">${esc(x.message)}</p>`).join('');
    gfKey = q; $('gf-slice').disabled = !p.ok;
    if (!renderer) return;
    const g = await new GLTFLoader().loadAsync(`/lab/api/models/${encodeURIComponent(f.name)}/grand-format.glb?${q}`);
    if (gfKey !== q) return;
    g.scene.traverse(o => { if (o.isMesh) { o.geometry.computeVertexNormals(); o.material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .55, transparent: true }); } });
    g.scene.rotation.x = Math.PI / 2; previewKey = 'gf';
    dropCurrent(); show(g.scene); frame(g.scene);
  } catch (e) { gfStale(); out.textContent = 'Aperçu impossible : ' + e.message; }
};
$('gf-slice').onclick = async () => {
  const f = sel, btn = $('gf-slice'), out = $('gf-out');
  if (!f || !gfKey) return;
  btn.disabled = true; out.textContent = 'tranchage de toutes les pièces… (peut durer plusieurs minutes)';
  try {
    const r = await api(`/models/${encodeURIComponent(f.name)}/grand-format/trancher`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...gfArgs(), usage: printUsage === 'profil' ? 'decoratif' : printUsage, supports: $('supports').value === 'aucun' ? false : $('supports').value }) });
    const b = r.bilan;
    out.innerHTML = `<b>Bilan</b> : ${b.pieces} pièce${b.pieces > 1 ? 's' : ''} · ${esc(b.duree)} · ${b.filament_g} g · ${b.cout_eur} € · ${b.chevilles} cheville${b.chevilles > 1 ? 's' : ''} à coller`
      + (r.alertes.length ? `<ul>${r.alertes.map(x => `<li>${esc(x.message)}</li>`).join('')}</ul>` : '');
    toast('Grand format tranché', 'ok'); loadFiles();
  } catch (e) { out.textContent = 'Tranchage impossible : ' + e.message; }
  finally { btn.disabled = !gfKey; }
};

/* print advisor */
let adviceTimer = 0, adviceSeq = 0;
function scheduleAdvice() { clearTimeout(adviceTimer); adviceTimer = setTimeout(loadAdvice, 600); }
async function loadAdvice() {
  const f = sel, box = $('advice');
  if (!f || f.ext === 'gcode') { box.hidden = true; return; }
  const brim = ['exterieure', 'oreilles'].includes($('adv-bordure')?.value);
  const q = new URLSearchParams({ rx: rotation[0], ry: rotation[1], rz: rotation[2], supports: $('supports').value !== 'aucun', brim, split: $('split').checked });
  if (+$('height').value) q.set('height', +$('height').value);
  const seq = ++adviceSeq;
  box.hidden = false; box.className = 'advice'; box.innerHTML = '<div class="ah"><span class="dot" style="background:var(--faint)"></span>Le conseiller vérifie le modèle…</div>';
  try {
    const a = await api(`/models/${encodeURIComponent(f.name)}/advice?${q}`);
    if (seq !== adviceSeq || sel !== f) return;
    const n = a.warnings.length;
    box.className = 'advice ' + a.verdict;
    box.innerHTML = `<div class="ah"><span class="dot"></span>${n ? `Conseiller : ${n} point${n > 1 ? 's' : ''} à regarder` : 'Conseiller : rien à signaler, prêt à trancher'}</div>`
      + (a.notes || []).map(t => `<div class="w note"><b>✓ ${esc(t.title)}</b><ul>${t.items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>${t.from && files.some(x => x.name === t.from) ? `<button class="btn ghost" data-orig="${esc(t.from)}">Voir l'original</button>` : ''}</div>`).join('')
      + a.warnings.map((w, i) => `<div class="w ${w.level}"><b>${esc(w.title)}</b><p>${esc(w.detail)}</p><div class="wbtns">${w.fix ? `<button class="btn" data-fix="${i}">${esc(w.fix_label || 'Corriger')}</button>` : ''}${(w.also || []).map((x, j) => `<button class="btn" data-also="${i}:${j}">${esc(x.label)}</button>`).join('')}</div></div>`).join('');
    box.querySelectorAll('[data-orig]').forEach(b => b.onclick = () => select(files.find(x => x.name === b.dataset.orig)));
    box.querySelectorAll('[data-also]').forEach(b => b.onclick = () => {
      const [i, j] = b.dataset.also.split(':').map(Number);
      if (a.warnings[i].also[j].action === 'defects') toggleDefects(b);
    });
    box.querySelectorAll('[data-fix]').forEach(b => b.onclick = async () => {
      const fix = a.warnings[+b.dataset.fix].fix;
      if (fix.repair) return repairModel(f, b);
      applyFix(fix); b.textContent = '✓ Appliqué'; b.classList.add('done');
    });
  } catch (e) { if (seq === adviceSeq) box.hidden = true; }
}
async function repairModel(f, btn) {
  const label = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Réparation… (jusqu\'à 1 min)';
  try {
    const r = await api(`/models/${encodeURIComponent(f.name)}/repair`, { method: 'POST' });
    toast(`Copie réparée créée : ${r.name}. L'original est gardé.`, 'ok');
    await loadFiles(); select(files.find(x => x.name === r.name));    // the advisor shows what was done
  } catch (e) {
    btn.disabled = false; btn.textContent = label;
    toast('Réparation impossible : ' + e.message, 'bad');
  }
}
/* where a mesh is open (red) or has edges shared by too many faces (orange), drawn on the model */
let defects = null;
async function toggleDefects(btn) {
  if (defects?.parent) { defects.removeFromParent(); defects = null; btn.textContent = 'Voir les défauts'; renderOnce(); return; }
  if (!current || !sel) return;
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Recherche…';
  try {
    const d = await api(`/models/${encodeURIComponent(sel.name)}/defects`), g = new THREE.Group();
    for (const [pts, color] of [[d.open, 0xff3b30], [d.nonmanifold, 0xffa000]]) {
      if (!pts.length) continue;
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      const line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true }));
      const dots = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: 6, sizeAttenuation: false, depthTest: false, transparent: true }));
      line.renderOrder = dots.renderOrder = 20; g.add(line, dots);
    }
    current.add(g); defects = g; btn.textContent = 'Masquer les défauts'; renderOnce();
    const parts = [d.holes ? `${d.holes} trou${d.holes > 1 ? 's' : ''} (${d.open_edges} bords ouverts, en rouge)` : '',
                   d.nonmanifold_edges ? `${d.nonmanifold_edges} arêtes partagées par trop de faces (en orange)` : ''].filter(Boolean);
    toast(parts.length ? parts.join(' · ') : 'Aucun défaut de surface trouvé : seule l\'orientation des faces posait problème.', parts.length ? '' : 'ok');
  } catch (e) { btn.textContent = 'Voir les défauts'; toast('Diagnostic impossible : ' + e.message, 'bad'); }
  btn.disabled = false;
}
function applyFix(fix) {
  if (fix.supports) { $('supports').value = fix.supports; $('supports').dispatchEvent(new Event('change')); }
  if (fix.orient) $('orient').checked = true;
  if (fix.split) { $('split').checked = true; }
  if (fix.height_mm) $('height').value = fix.height_mm;
  if (fix.advanced) {
    for (const [k, v] of Object.entries(fix.advanced)) { const el = $('adv-' + k); if (el) el.value = v; }
    advCount(); $('adv').open = true;
  }
  toast('Réglage appliqué. Le conseiller revérifie.', 'ok');
  sizeNote();
}
$('supports').addEventListener('change', scheduleAdvice);
document.addEventListener('change', e => { if (e.target.id === 'adv-bordure') scheduleAdvice(); });

/* is the plate empty? the camera compares it with a photo of the empty plate; a doubt blocks the start until checked */
async function plateCheck() {
  const box = $('ln-plate'), go = $('ln-go');
  box.hidden = false; box.className = 'ln-plate'; box.innerHTML = '<span class="spin"></span> Vérification du plateau à la caméra…';
  const r = await api('/plateau').catch(() => ({ etat: 'inconnu', raison: 'caméra indisponible' }));
  const empty = async btn => {
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Photo…';
    try { await api('/plateau/vide', { method: 'POST' }); box.className = 'ln-plate ok'; box.innerHTML = '✓ Plateau vide mémorisé : il sera vérifié avant chaque impression.'; go.disabled = !ctx.control; }
    catch (e) { toast(e.message, 'bad'); btn.disabled = false; btn.textContent = 'Le plateau est vide'; }
  };
  if (r.etat === 'vide') { box.className = 'ln-plate ok'; box.innerHTML = '✓ Plateau vide (vérifié à la caméra)'; return; }
  if (r.etat === 'occupe') {
    go.disabled = true; box.className = 'ln-plate bad';
    box.innerHTML = `<b>Il semble rester quelque chose sur le plateau.</b><img alt="Photo du plateau" src="${r.photo}">
      <span class="note" style="margin:0">Retire la pièce, puis vérifie à nouveau. Si le plateau est bien vide (ombre, reflet), dis-le : la photo de référence est mise à jour.</span>
      <div class="row-btns" style="margin:0"><button class="btn" id="pl-again">Vérifier à nouveau</button><button class="btn ghost" id="pl-empty">Le plateau est vide</button></div>`;
    $('pl-again').onclick = plateCheck; $('pl-empty').onclick = e => empty(e.currentTarget);
    return;
  }
  box.className = 'ln-plate';
  box.innerHTML = r.raison === 'pas encore de photo du plateau vide'
    ? `Pour vérifier le plateau à la caméra avant chaque impression : quand il est vide, mémorise-le.<button class="btn" id="pl-empty">Le plateau est vide : mémoriser</button>`
    : `Plateau non vérifié (${esc(r.raison || 'caméra')}) : regarde-le avant de lancer.`;
  if ($('pl-empty')) $('pl-empty').onclick = e => empty(e.currentTarget);
}

/* the review of this model's last print (Galerie → Bilan): its corrections are applied as soon as the
   model is selected, one click to take them back out */
function showRetour(f, r) {
  if (!r || !(r.issues?.length || r.note)) return;
  const when = new Date(r.date * 1000).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' });
  const auto = r.issues?.length && !!document.querySelectorAll('[data-adv]').length;   // advanced fields rendered
  let prev = null;
  if (r.issues?.length) {
    prev = optState();   // what the corrections change, to put it back
    if (auto) {
      const adv = { ...prev.adv }; for (const [k, v] of Object.entries(r.advanced || {})) if (k in adv) adv[k] = v;
      const prevMode = printMode;
      optApply({ ...prev, supports: r.supports || prev.supports, usage: r.usage || prev.usage, adv });
      if (r.mode) { printMode = r.mode; renderMode(); }
      prev.mode = prevMode;
    }
  }
  $('opt-res').innerHTML = `<div class="opt-card warn"><b>${auto
    ? `Corrections de ta dernière impression (${when}) appliquées`
    : `Retour de ta dernière impression (${when})`}</b>
    ${(r.titres || []).map(t => `<div class="opt-step left"><span>!</span><div><b>${esc(t)}</b></div></div>`).join('')}
    ${r.note ? `<p class="note" style="margin:0">« ${esc(r.note)} »</p>` : ''}
    ${r.issues?.length ? `<button class="btn${auto ? ' ghost' : ''}" id="retour-drop">${auto ? 'Enlever les corrections' : 'Appliquer les corrections'}</button>` : ''}</div>`;
  if ($('retour-drop')) $('retour-drop').onclick = auto ? () => {
    optApply(prev); if (prev.mode !== undefined) { printMode = prev.mode; renderMode(); }
    $('retour-drop').outerHTML = '<p class="note" style="margin:0">Corrections enlevées.</p>';
  } : () => {
    const adv = { ...prev.adv }; for (const [k, v] of Object.entries(r.advanced || {})) if (k in adv) adv[k] = v;
    optApply({ ...prev, supports: r.supports || prev.supports, usage: r.usage || prev.usage, adv });
    if (r.mode) { printMode = r.mode; renderMode(); }
    $('retour-drop').outerHTML = '<p class="note" style="margin:0">✓ Corrections appliquées.</p>';
  };
}

/* « Optimiser pour la CC2 » : the server chains repair, size, best face and the advisor's fixes; the plan fills the form */
function optState() {   // what the plan changes, to put it back
  return { rotation: [...rotation], height: $('height').value, supports: $('supports').value, split: $('split').checked, usage: printUsage,
           adv: Object.fromEntries([...document.querySelectorAll('[data-adv]')].map(el => [el.dataset.adv, el.value])) };
}
function optApply(st) {
  rotation = [...st.rotation]; $('height').value = st.height; $('supports').value = st.supports; $('split').checked = st.split;
  for (const [k, v] of Object.entries(st.adv)) { const el = $('adv-' + k); if (el) el.value = v; }
  setUsage(st.usage); advCount(); renderRot(); markOrient(); sizeNote();
}
$('opt-go').onclick = async () => {
  const f = sel, b = $('opt-go'); if (!f) return;
  b.disabled = true; b.innerHTML = '<span class="spin"></span>Analyse du modèle… (jusqu\'à 30 s)'; $('opt-res').innerHTML = '';
  try {
    const q = new URLSearchParams({ rz: rotation[2] }); if (baseHeight()) q.set('height', baseHeight().toFixed(2));
    const p = await api(`/models/${encodeURIComponent(f.name)}/optimize?${q}`, { method: 'POST' });
    if (p.file !== f.name) { await loadFiles(); await select(files.find(x => x.name === p.file)); }   // the repaired copy
    const before = optState();
    const adv = { ...before.adv }; for (const k of Object.keys(adv)) adv[k] = p.advanced[k] ?? adv[k];
    optApply({ rotation: p.rotate, height: p.height_mm ? Math.round(p.height_mm) : before.height, supports: p.supports,
               split: p.split || before.split, usage: p.usage, adv });
    optUndo = p.file === f.name ? before : null;   // a repaired copy is a new file: going back means reopening the original
    $('opt-res').innerHTML = `<div class="opt-card ${p.verdict}">
      <b>${p.steps.length ? `${p.steps.length} changement${p.steps.length > 1 ? 's' : ''} pour la CC2` : 'Déjà prêt pour la CC2 : rien à changer'}</b>
      ${p.steps.map(x => `<div class="opt-step"><span>✓</span><div><b>${esc(x.title)}</b><p>${esc(x.why)}</p></div></div>`).join('')}
      ${p.left.map(x => `<div class="opt-step left"><span>!</span><div><b>${esc(x.title)}</b><p>${esc(x.detail)}</p></div></div>`).join('')}
      ${optUndo && p.steps.length ? '<button class="btn ghost" id="opt-undo">Annuler l\'optimisation</button>' : ''}</div>`;
    if ($('opt-undo')) $('opt-undo').onclick = () => { optApply(optUndo); optUndo = null; $('opt-res').innerHTML = ''; toast('Réglages remis comme avant', 'ok'); };
  } catch (e) { toast('Optimisation impossible : ' + e.message, 'bad'); }
  b.disabled = false; b.innerHTML = '<svg class="i"><use href="#i-spark"/></svg>Optimiser pour la CC2';
};

/* spools actually loaded in the CANVAS */
async function matchSpools(auto = false) {
  if (!sel || sel.ext === 'gcode') return;
  const f = sel, b = $('use-spools'); b.disabled = true;
  try {
    const [r, st] = await Promise.all([api(`/models/${encodeURIComponent(f.name)}/match-spools?usage=${printUsage}`),
      api('/bobines').catch(() => null)]);
    if (sel !== f) return;
    stockLow = st?.low_g || 0;
    stockLeft = Object.fromEntries((st?.trays || []).map(t => [t.tray + 1, t.restant_g]));   // stock numbers the trays 0-3
    needs = r.needs || {};
    // one colour slices as T0 whatever the spool: slot 1 then stands for the spool chosen in the CANVAS
    single = r.single || null;
    trays = single ? { 1: r.trays.find(t => t.slot === single.pos + 1) } : Object.fromEntries(r.trays.map(t => [t.slot, t]));
    canvasSig = '';
    // repainted with the spools: the colours listed are the spools' own, one per spool used
    if (r.palette) analysis = { ...analysis, colours: r.colours, palette: r.palette };
    mapping = Object.fromEntries(Object.entries(r.mapping).map(([k, v]) => [k, +v]));
    if (auto) keepChoices();   // the user's earlier picks win over the automatic rematch
    r.filaments.forEach((fil, i) => { spools[i + 1] = fil; });
    const t1 = single && trays[1];
    matched = { line: (t1 ? `Imprimé avec la bobine chargée <b>${single.pos + 1}</b> · <span class="dot" style="background:${t1.hex};display:inline-block;width:9px;height:9px;border-radius:50%"></span> ${esc(t1.name)} (${esc(t1.filament)})`
        + (analysis?.source === 'sans couleur' ? ' : modèle sans couleur, la bobine déjà engagée est gardée.' : '')
      : (r.palette ? 'Repeint avec les couleurs des bobines chargées : ' : `${auto ? 'Associé automatiquement' : 'Associé'} aux bobines chargées : `)
      + r.details.map(d => `<span style="white-space:nowrap"><span class="dot" style="background:${d.hex};display:inline-block;width:9px;height:9px;border-radius:50%"></span> ${r.palette ? `${d.share} %` : '→'} bobine ${(d.tray_pos ?? d.slot - 1) + 1} ${esc(d.tray_name)}${d.de > 25 ? ' <span style="color:var(--warn)">(couleur éloignée)</span>' : ''}</span>`).join(' · '))
      , warnings: r.warnings };
    renderColours(); modelLook();
  } catch (e) {
    if (!auto) toast(e.message, 'bad');
    else { $('c-match').hidden = false; $('c-match').textContent = 'Bobines du CANVAS non lues (imprimante injoignable) : proposition automatique.'; }
    keepChoices(); renderColours();
  }
  b.disabled = false;
}
$('use-spools').onclick = () => matchSpools(false);

/* a spool swapped in the CANVAS while a model is open: match again */
let canvasSig = '';
async function watchCanvas() {
  if (document.hidden || !sel || sel.ext === 'gcode' || $('prep').hidden) return;
  try {
    const c = (await (await fetch('/canvas')).json()).canvas_info;
    if (!c) return;
    const sig = JSON.stringify((c.canvas_list || []).map(u => (u.tray_list || []).map(t =>
      [t.status, t.filament_color || t.color, t.filament_type || t.type, t.filament_code || t.code])));
    if (canvasSig && sig !== canvasSig) { toast('Bobines changées dans le CANVAS : association mise à jour', 'ok'); matchSpools(true); }
    canvasSig = sig;
  } catch { /* printer away: keep the current choice */ }
}
setInterval(watchCanvas, 15000);

/* the assistant: the CLI brain acting through the workshop's own tools (repair, size, turn, shape, slice…) */
let chatHist = [], chatSel = null, chatBusy = false, chatConv = '', chatPhoto = null;
/* a photo for the assistant (a flat object to copy, a sketch): uploaded at once, sent with the next message */
function chatPhotoShow() {
  const box = $('chat-att');
  box.hidden = !chatPhoto;
  box.innerHTML = chatPhoto ? `<img src="/lab/api/croquis/${encodeURIComponent(chatPhoto)}" alt=""><span>Photo jointe</span><button class="btn ghost" id="chat-att-x" type="button" aria-label="Retirer la photo">✕</button>` : '';
  if (chatPhoto) $('chat-att-x').onclick = () => { chatPhoto = null; chatPhotoShow(); };
}
$('chat-photo').onclick = () => $('chat-photo-in').click();
$('ia-open').onclick = () => {   // the assistant from the library, phone included (it lives in the view column)
  if (!sel) chatFree();
  $('chat-sec').classList.remove('folded'); $('chat-fold').textContent = '▾';
  if (phone.matches) mview('view');
  $('chat-sec').scrollIntoView({ block: 'nearest' }); $('chat-in').focus();
};
$('chat-photo-in').onchange = async () => {
  const f = $('chat-photo-in').files[0]; $('chat-photo-in').value = '';
  if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await api('/croquis', { method: 'POST', body: fd });
    chatPhoto = r.name; chatPhotoShow();
    if (!$('chat-in').value.trim()) $('chat-in').value = 'Fais-en une pièce : le plus grand côté mesure … mm, épaisseur 3 mm';
    $('chat-in').focus();
  } catch (e) { toast('Photo refusée : ' + e.message, 'bad'); }
};
function chatConvNew() { chatConv = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())); }
function chatAdd(role, html, small) {
  const d = document.createElement('div');
  d.className = 'chat-msg ' + role;
  d.innerHTML = html + (small ? `<small>${esc(small)}</small>` : '');
  $('chat-log').appendChild(d); $('chat-log').scrollTop = 1e9;
  return d;
}
/* no model open: the assistant can still make one (made-to-measure parts, Blender) */
function chatFree() {
  $('chat-sec').hidden = false; $('chat-sug').hidden = true;
  $('chat-sec').classList.remove('folded'); $('chat-fold').textContent = '▾';   // nothing else to see: open
  if (chatSel !== '') { chatHist = []; $('chat-log').innerHTML = ''; chatConvNew(); }
  chatSel = '';
  $('chat-in').placeholder = 'Décris la pièce à fabriquer : « une boîte de 100 × 60 mm avec couvercle »…';
  $('chat-note').dataset.txt ??= $('chat-note').textContent;
  $('chat-note').textContent = 'Aucun modèle choisi : décris une pièce à fabriquer (« un vase de 10 cm », « un crochet mural ») ou touche 📷 pour joindre la photo d\'un objet plat posé sur une feuille, puis donne sa taille réelle.';
}
async function chatSend() {
  const v = $('chat-in').value.trim();
  if (!v || chatBusy) return;
  const model = sel && sel.ext !== 'gcode' ? sel : null;
  chatBusy = true; $('chat-go').disabled = true; $('chat-in').value = '';
  $('chat-sug').hidden = true;   // one real turn: the ready-made ideas step aside
  const photo = chatPhoto; chatPhoto = null; chatPhotoShow();
  chatAdd('user', esc(v) + (photo ? `<br><img class="chat-img" src="/lab/api/croquis/${encodeURIComponent(photo)}" alt="photo jointe">` : '') + (cible.pt ? ` <small>— zone (${cible.pt.join(', ')})</small>` : ''));
  const wait = chatAdd('assistant', '<i style="color:var(--dim)">…</i>');
  const step = chatAdd('activity', '');
  const done = [];
  try {
    const rsp = await fetch('/lab/api' + (model ? `/models/${encodeURIComponent(model.name)}/assistant/stream` : '/assistant/stream'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: v, history: chatHist, conversation: chatConv, photo: photo || undefined,
                             zone: model && cible.pt ? { point: cible.pt, rayon: +$('chat-zone-r').value || 10 } : undefined })
    });
    if (!rsp.ok || !rsp.body) {
      let msg = `code ${rsp.status}`;
      try { msg = (await rsp.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    const rd = rsp.body.getReader(), dec = new TextDecoder();
    let buf = '', r = null;
    for (;;) {
      const { value, done: end } = await rd.read();
      if (value) buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();          // SSE: "data: {json}" per line
      for (const L of lines) {
        if (!L.startsWith('data: ')) continue;
        let ev; try { ev = JSON.parse(L.slice(6)); } catch { continue; }
        if (ev.type === 'outil') {
          done.push(ev.outil);
          step.innerHTML = `<b>${esc(ev.outil)}</b> — l'atelier travaille sur la pièce…`;
        } else if (ev.type === 'outil_ok') {
          step.innerHTML = `<b>${esc(ev.outil)}</b> — fait${ev.fichier ? ` : <code>${esc(ev.fichier)}</code>` : ''}`;
        } else if (ev.type === 'cli') {
          step.innerHTML = `via l'agent CLI : <code>${esc(ev.cible)}</code>`;
        } else if (ev.type === 'recharge') {          // the agent exported its own work (Blender…)
          step.innerHTML = `l'agent a exporté la pièce : <code>${esc(ev.fichier)}</code>`; chatSel = ev.fichier;
          await loadFiles();
          const f = files.find(x => x.name === ev.fichier);
          if (f && f.ext !== 'gcode') await select(f);
        } else if (ev.type === 'image') {           // the outline the workshop found, drawn on the photo
          chatAdd('activity', `contour trouvé (rouge, trous en bleu) :<br><img class="chat-img" src="/lab/api/croquis/${encodeURIComponent(ev.nom)}" alt="contour trouvé">`);
        } else if (ev.type === 'etape') {
          step.innerHTML = esc(ev.texte) + '…';
        } else if (ev.type === 'erreur') {
          throw new Error(ev.texte);
        } else if (ev.type === 'final') {
          r = ev;
        }
      }
      if (end) break;
    }
    if (!r) throw new Error('le moteur n\'a pas répondu');
    step.remove();
    wait.innerHTML = esc(r.reply || '…').replace(/\n/g, '<br>') + (r.outils?.length ? `<small>${r.outils.join(' · ')}</small>` : '');
    chatHist.push({ role: 'user', content: v }, { role: 'assistant', content: r.reply || '' });
    chatHist = chatHist.slice(-10);
    if (r.file && (!model || r.file !== model.name || r.maj)) {            // a new model, or the same one changed under the page
      chatSel = r.file;   // the conversation goes on with the file the assistant made
      await loadFiles();
      const f = files.find(x => x.name === r.file);
      if (f && !/\.gcode$/i.test(f.name)) select(f);
      else if (f) { select(f); toast(`L'assistant a tranché : ${nice(f.name)}`, 'ok'); }
    }
  } catch (e) {
    step.remove();
    const cut = e instanceof TypeError || /network|fetch|load failed/i.test(e.message);   // the connection, not the brain
    wait.innerHTML = cut
      ? `<span style="color:var(--bad)">Connexion coupée pendant le travail.</span><small>L'assistant a peut-être continué sur le serveur : la bibliothèque est rechargée, regarde les nouveaux fichiers.</small>`
      : `<span style="color:var(--bad)">${esc(e.message)}</span>`;
    if (cut) loadFiles().catch(() => {});
  }
  chatBusy = false; $('chat-go').disabled = false;
}
$('chat-in').dataset.ph = $('chat-in').placeholder;
if (!sel) chatFree();
$('chat-go').onclick = chatSend;
$('chat-in').onkeydown = e => { if (e.key === 'Enter') chatSend(); };
/* folded by default on a phone, so the piece stays visible */
$('chat-fold').onclick = () => { const f = $('chat-sec').classList.toggle('folded'); $('chat-fold').textContent = f ? '▴' : '▾'; };
$('chat-sug').onclick = e => {
  const w = e.target.closest('[data-wf]');
  if (w && !chatBusy) { workflowShow(); return; }
  const b = e.target.closest('[data-q]'); if (b && !chatBusy) { $('chat-in').value = b.dataset.q; chatSend(); }
};

/* R2.5: guided workflow — a step-by-step checklist in the chat; each step calls its own endpoint */
async function workflowShow() {
  if (!sel || chatBusy) return;
  const name = encodeURIComponent(sel.name);
  const w = await api(`/models/${name}/workflow`).catch(() => null);
  if (!w) { toast("Choisis un modèle d'abord", 'bad'); return; }
  const steps = [
    { id: 'fiche', label: 'Voir la fiche de la pièce',
      run: async () => { const i = await api(`/models/${name}/info`); return Array.isArray(i.size_mm) ? i.size_mm.join(' × ') + ' mm' : ''; } },
    { id: 'pose', label: 'Choisir la meilleure pose',
      run: async () => { const o = await api(`/models/${name}/orientations`); const b = (o || []).find(x => x.recommandee) || (o || [])[0]; return b ? b.label : ''; } },
    { id: 'bobines', label: 'Associer les bobines CANVAS',
      run: async () => { const m = await api(`/models/${name}/match-spools`); return Object.keys(m.mapping || {}).length + ' couleur(s)'; } },
    { id: 'tranche', label: 'Trancher pour la CC2',
      run: async () => { const r = await api(`/models/${name}/prepare-print`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); return r.gcode && r.gcode[0] ? nice(r.gcode[0]) : 'tranché'; } },
    { id: 'lance', label: "Lancer l'impression sur la CC2",
      run: async () => { if (!w.gcode) throw new Error("tranche d'abord"); await api('/print/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: w.gcode }) }); return "envoyé à l'imprimante"; } },
  ];
  const box = chatAdd('assistant', `<b>Workflow guidé : ${esc(nice(sel.name))}</b><div class="wf"></div>`);
  const wf = box.querySelector('.wf');
  for (const s of steps) {
    const b = document.createElement('button');
    b.className = 'btn wf-step'; b.textContent = s.label;
    if (s.id === 'tranche' && w.gcode) { b.classList.add('done'); b.textContent = '✔ ' + s.label + ` — ${esc(w.gcode)}`; }
    b.onclick = async () => {
      if (b.classList.contains('done')) return;
      b.disabled = true; b.textContent = s.label + '…';
      try { const out = await s.run(); b.classList.add('done'); b.textContent = '✔ ' + s.label + (out ? ` — ${esc(out)}` : ''); }
      catch (e) { b.disabled = false; b.textContent = s.label; toast(e.message, 'bad'); }
    };
    wf.appendChild(b);
  }
}
if (sel && matchMedia('(max-width: 600px)').matches) { $('chat-sec').classList.add('folded'); $('chat-fold').textContent = '▴'; }

/* plate, orientation, copies, advanced settings */
let rotation = [0, 0, 0];
function renderRot() {
  const pos = orients.find(o => o.rotate[0] === rotation[0] && o.rotate[1] === rotation[1]);
  const base = pos ? pos.label.toLowerCase() : ['X', 'Y'].map((a, i) => rotation[i] ? `${a} ${rotation[i]}°` : '').filter(Boolean).join(' · ') || 'telle quelle';
  $('rot-v').textContent = base + (rotation[2] ? ` · tournée de ${rotation[2]}° sur le plateau` : '');
  if (current && previewKey !== 'cut' && !paths?.parts?.some(p => p.lines.parent === current)) {
    if (sel?.name === mv.file) piecesBase();
    current.rotation.set(THREE.MathUtils.degToRad(rotation[0]), THREE.MathUtils.degToRad(rotation[1]), THREE.MathUtils.degToRad(rotation[2]), 'ZYX');
    if (current.userData.base) current.rotation.x += current.userData.base;
    // mirror and per-axis scale act along the plate's axes, after the turns (as sliced); turns are quarter turns,
    // so each axis of the model lies along one plate axis and takes that axis's factor (negative = mirrored)
    const k = scale(); if ($('mirror').checked) k[0] = -k[0];
    current.scale.set(...[0, 1, 2].map(i => {
      const v = new THREE.Vector3(i === 0 ? 1 : 0, i === 1 ? 1 : 0, i === 2 ? 1 : 0).applyQuaternion(current.quaternion);
      const j = [0, 1, 2].reduce((a, b) => Math.abs(v.getComponent(b)) > Math.abs(v.getComponent(a)) ? b : a, 0);
      return k[j];
    }));
    const h = +$('height').value;   // shown at the size it will print, on the plate at its real scale
    if (h) { current.updateMatrixWorld(true); const b = new THREE.Box3().setFromObject(current), z = b.max.z - b.min.z; if (z > 0) current.scale.multiplyScalar(h / z); }
    if (sel?.name === mv.file) { current.position.set(0, 0, 0); piecesScale(); }   // after the height, as the slicer does
    // centred on the plate, as the slicer places it: a file's own coordinates (often the slicer plate's, 0 to 256)
    // would show it in a corner, and turns about its origin would swing it away. The pivot is its centre when
    // loaded, kept in the model's own axes: a piece moved since then keeps its place next to the others
    current.position.set(0, 0, 0); current.updateMatrixWorld(true);
    const u = current.userData;
    u.pivot ||= current.worldToLocal(new THREE.Box3().setFromObject(current).getCenter(new THREE.Vector3()));
    const at = current.localToWorld(u.pivot.clone());
    current.position.set(-at.x, -at.y, 0);
    const box = new THREE.Box3().setFromObject(current); current.position.z -= box.min.z;
    const tall = box.max.z - box.min.z, was = current.userData.tall;   // much bigger or smaller: frame it again
    current.userData.tall = tall;
    if (was && (tall / was > 1.4 || was / tall > 1.4)) frame(current);
    renderOnce();
  }
}
document.querySelectorAll('[data-rot]').forEach(b => b.onclick = () => {
  if (b.dataset.rot === 'reset') rotation = [0, 0, 0]; else rotation[+b.dataset.rot] = (rotation[+b.dataset.rot] + 90) % 360;
  renderRot(); sizeNote(); markOrient();
});

/* how to lay the part: six thumbnails, the workshop's advice marked */
let orients = [], orientSeq = 0;
async function loadOrients(f) {
  const seq = ++orientSeq;
  orients = [];
  $('orients').innerHTML = '<p class="note wait" style="margin:0"><span class="spin"></span> Calcul des positions…</p>';
  const q = +$('height').value ? `?height=${+$('height').value}` : '';
  try {
    const list = await api(`/models/${encodeURIComponent(f.name)}/orientations${q}`);
    if (seq !== orientSeq || sel !== f) return;
    orients = list;
    $('orients').innerHTML = list.map((o, i) => `<button class="orient" data-orient="${i}" ${o.tient ? '' : 'disabled title="Ne tient pas sur le plateau ainsi"'}>
      ${o.recommandee ? '<span class="best">Conseillée</span>' : ''}<img alt="" src="${o.image}"><span>${esc(o.label)}</span></button>`).join('');
    $('orients').querySelectorAll('[data-orient]').forEach(b => b.onclick = () => {
      const o = orients[+b.dataset.orient];
      if (+$('height').value) $('height').value = Math.round(o.size_mm[2]);   // same object laid another way: its new height
      rotation = [o.rotate[0], o.rotate[1], rotation[2]];
      renderRot(); sizeNote(); markOrient();
    });
    markOrient();
  } catch (e) { if (seq === orientSeq) $('orients').innerHTML = `<p class="note wait" style="margin:0">${esc(e.message)}</p>`; }
}
// the height the model has as it comes (orientation 0): the field holds the height as it is now laid
function baseHeight() {
  const h = +$('height').value, cur = orients.find(o => o.rotate[0] === rotation[0] && o.rotate[1] === rotation[1]);
  return h && cur && orients[0] ? h * orients[0].size_mm[2] / cur.size_mm[2] : h;
}
function markOrient() {
  $('orients').querySelectorAll('[data-orient]').forEach(b => {
    const o = orients[+b.dataset.orient];
    b.classList.toggle('on', !!o && o.rotate[0] === rotation[0] && o.rotate[1] === rotation[1]);
  });
}
function renderAdvanced() {
  const a = cfg?.advanced; if (!a) return;
  $('plate').innerHTML = a.plates.map(p => `<option value="${p.value}" ${p.value === a.default_plate ? 'selected' : ''}>${esc(p.label)}</option>`).join('');
  $('adv-fields').innerHTML = '<div>'
    + a.choices.map(c => `<div class="field"><label for="adv-${c.name}">${esc(c.label)}</label><select id="adv-${c.name}" data-adv="${c.name}"><option value="">Profil (${esc(c.options.find(o => o.value === c.default)?.label || c.default)})</option>${c.options.map(o => `<option value="${o.value}">${esc(o.label)}</option>`).join('')}</select></div>`).join('')
    + a.numbers.map(n => `<div class="field"><label for="adv-${n.name}">${esc(n.label)}${n.unit ? ' (' + n.unit + ')' : ''}</label><input id="adv-${n.name}" data-adv="${n.name}" type="number" min="${n.min}" max="${n.max}" placeholder="${n.default}"></div>`).join('')
    + (a.numbers_fil || []).map(n => `<div class="field"><label for="adv-${n.name}">${esc(n.label)}</label><input id="adv-${n.name}" data-adv="${n.name}" type="number" min="${n.min}" max="${n.max}" step="${n.step}" placeholder="${n.default}"></div>`).join('')
    + a.temps.map(t => `<div class="field"><label for="adv-${t.name}">${esc(t.label)} (°C)</label><input id="adv-${t.name}" data-adv="${t.name}" type="number" min="${t.min}" max="${t.max}" placeholder="profil du filament (PLA : ${t.default_pla})"></div>`).join('')
    + '</div>';
  document.querySelectorAll('[data-adv]').forEach(el => el.oninput = el.onchange = advCount);
}
function advValues() { const o = {}; document.querySelectorAll('[data-adv]').forEach(el => { if (el.value !== '') o[el.dataset.adv] = el.tagName === 'SELECT' ? el.value : +el.value; }); return o; }
function advCount() { const n = Object.keys(advValues()).length; $('adv-n').textContent = n ? `· ${n} modifié${n > 1 ? 's' : ''}` : ''; }
$('adv-reset').onclick = () => { document.querySelectorAll('[data-adv]').forEach(el => el.value = ''); advCount(); };

/* slicing */
let infillTouched = false, printUsage = 'decoratif';
function renderUsages() {
  $('usage').innerHTML = (cfg.usages || []).map(u => `<button data-usage="${u.value}" title="${esc(u.hint)}">${esc(u.label)}</button>`).join('');
  $('usage').querySelectorAll('[data-usage]').forEach(b => b.onclick = () => setUsage(b.dataset.usage, true));
}
/* the usage last picked by hand is kept: opening a file used to put it back on « Décoratif » */
const savedUsage = () => { try { return localStorage.getItem('lab-usage'); } catch { return null; } };
function setUsage(u, byUser = false) {
  const def = (cfg?.usages || []).find(x => x.value === u); if (!def) return;
  printUsage = u;
  $('usage').querySelectorAll('[data-usage]').forEach(b => b.classList.toggle('on', b.dataset.usage === u));
  $('usage-hint').textContent = def.hint;
  if (def.quality && cfg.qualities.includes(def.quality)) $('quality').value = def.quality;
  else if (!def.quality) $('quality').value = cfg.default_quality;
  infillTouched = false; $('inf-v').textContent = u === 'profil' ? 'selon le profil' : 'selon l\'usage';
  if (byUser) { try { localStorage.setItem('lab-usage', u); } catch {} scheduleAdvice(); scheduleEstimate(); }
}
/* what the chosen usage costs, under the usage buttons: filament, time, price (one slice of just that choice) */
let estTimer = 0, estSeq = 0; const estCache = new Map();
function scheduleEstimate() {
  clearTimeout(estTimer); const def = (cfg?.usages || []).find(x => x.value === printUsage);
  if (def) $('usage-hint').textContent = def.hint;
  if (!sel || sel.ext === 'gcode' || !analysis) return;
  estTimer = setTimeout(loadEstimate, 500);
}
async function loadEstimate() {
  const f = sel, seq = ++estSeq, body = JSON.stringify(prepBody()), key = f.name + body, def = (cfg?.usages || []).find(x => x.value === printUsage);
  const show = html => { if (seq === estSeq && sel === f && def) $('usage-hint').innerHTML = esc(def.hint) + html; };
  if (estCache.has(key)) return show(estCache.get(key));
  show('<span class="est"><span class="spin"></span> calcul du filament et du temps…</span>');
  try {
    const r = await api(`/models/${encodeURIComponent(f.name)}/estimate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    const html = r.error ? '' : `<span class="est"><b>${fmtG(r.g / r.copies)}</b> · <b>${dur(durSec(r.time) / r.copies)}</b> · ${euro(r.eur / r.copies)}${r.copies > 1 ? ' par pièce' : ''}</span>`;
    if (estCache.size > 60) estCache.clear();
    estCache.set(key, html); show(html);
  } catch { show(''); }
}
$('infill').oninput = () => { infillTouched = true; $('inf-v').textContent = $('infill').value + ' %'; };
function prepBody() {
  const top = Math.max(...Object.values(mapping));
  return {
      mapping, filaments: Array.from({ length: top }, (_, i) => spools[i + 1] || 'PLA'), quality: $('quality').value,
      infill: infillTouched ? +$('infill').value : null, supports: $('supports').value, plate_only: $('plate-only').checked, height_mm: +$('height').value || null, mode: printMode, split: $('split').checked, plate: $('plate').value || undefined, advanced: advValues(),
      usage: printUsage, rotate: xform(), copies: Math.max(1, +$('copies').value || 1), orient: $('orient').checked,
      slot_colours: Object.keys(trays).length ? Object.fromEntries(Object.entries(trays).map(([k, t]) => [k, t.hex])) : null,
      palette: analysis?.palette || null,
      simplify_colours: $('simplify').value,
      ...(moved() ? { moves: mv.moves, shift: shiftXY() } : {}), ...(resized() ? { scales: mv.scales } : {}),
      pauses_mm: $('pauses').value.trim().split(/[;\s]+|,\s+/).map(v => +v.replace(',', '.')).filter(v => v > 0) };
}
/* AI picks and justifies the slicing settings before the cut; the panel fields show exactly what it chose */
function iaApply(r) {
  const faits = [];
  if (r.usage) setUsage(r.usage, true);
  if (r.qualite && cfg.qualities.includes(r.qualite)) { $('quality').value = r.qualite; faits.push('qualité ' + r.qualite); }
  if (typeof r.remplissage === 'number') { $('infill').value = r.remplissage; $('infill').oninput(); faits.push('remplissage ' + r.remplissage + ' %'); }
  if (r.supports) { $('supports').value = r.supports; $('supports').dispatchEvent(new Event('change')); faits.push('supports ' + r.supports); }
  if (r.reglages && Object.keys(r.reglages).length) {
    for (const [k, v] of Object.entries(r.reglages)) { const el = $('adv-' + k); if (el) el.value = v; }
    advCount(); $('adv').open = true;
    faits.push(Object.keys(r.reglages).length + ' réglage' + (Object.keys(r.reglages).length > 1 ? 's' : '') + ' fin' + (Object.keys(r.reglages).length > 1 ? 's' : ''));
  }
  if (Array.isArray(r.rotate) && (r.rotate[0] || r.rotate[1] || r.rotate[2])) faits.push('rotation ' + r.rotate.map(a => Math.round(a) + '°').join(' '));
  return faits;
}
function iaNote(r, faits) {
  const n = $('ia-note');
  n.hidden = false; n.className = 'advice';
  n.innerHTML = `<div class="ah"><span class="dot"></span>${faits.length ? "L'IA a réglé le tranchage : " + esc(faits.join(' · ')) : "L'IA n'a pas changé les réglages"}</div>`
    + (r.explication ? `<p class="note">${esc(r.explication)}</p>` : '');
}
$('go').onclick = async () => {
  const top = Math.max(...Object.values(mapping)), go = $('go'), f = sel;
  go.disabled = true; go.innerHTML = '<span class="spin"></span>Tranchage en cours…'; $('result').innerHTML = '';
  try {
    if ($('ia-tranche').checked) {
      go.innerHTML = '<span class="spin"></span>L\'IA lit la pièce et règle le tranchage…';
      const r = await api(`/models/${encodeURIComponent(f.name)}/slice-brain`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(prepBody()) });
      iaNote(r, iaApply(r));
      go.innerHTML = '<span class="spin"></span>Tranchage en cours…';
    }
    const r = await api(`/models/${encodeURIComponent(f.name)}/prepare-print`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(prepBody()) });
    if (r.split) { renderPieces(r); return; }
    const max = Math.max(...r.slots.map(s => s.metres), .01), g = r.gcode[0];
    $('result').innerHTML = `<div class="result"><div class="stats"><div class="stat"><div class="v">${esc(shortTime(r.time))}</div><div class="k">durée estimée</div></div>
      <div class="stat"><div class="v">${r.layers ?? '–'}</div><div class="k">couches</div></div><div class="stat"><div class="v">${r.usage ? fmtG(r.usage.g) : (r.total_m ?? r.filament_m ?? '–') + ' m'}</div><div class="k">${r.usage ? 'filament · ' + euro(r.usage.eur) : 'filament'}</div></div></div>
      ${r.slots.length > 1 ? `<p class="note" style="margin:0 0 8px">${r.colour_changes} changements de couleur · dont purge ${(r.purge_m || []).reduce((a, b) => a + b, 0).toFixed(1)} m · mode ${({ economie: 'Économie', equilibre: 'Équilibré', qualite: 'Qualité', sans_purge: 'Sans purge' })[r.mode] || ''}${r.ordre === 'suite' ? ' · pièces les unes après les autres' : ''}</p>` : ''}
      ${r.temps && (r.temps.bed || (r.temps.nozzle || []).length) ? `<p class="note" style="margin:0 0 8px">${(r.temps.nozzle || []).length ? `buse ${[...new Set(r.temps.nozzle)].join(' / ')} °C` : ''}${(r.temps.nozzle || []).length && r.temps.bed ? ' · ' : ''}${r.temps.bed ? `plateau ${r.temps.bed} °C (première couche)` : ''} — températures du profil Elegoo donc optimales</p>` : ''}
      ${r.slots.map(s => `<div class="use"><span class="tag"><i style="background:${s.colour}"></i>${s.slot}</span><span class="fn" ${s.buse ? `title="buse ${s.buse} °C"` : ''}>${esc(s.filament)}${s.buse ? ` · ${s.buse} °C` : ''}</span><span class="bar"><i style="width:${100 * s.metres / max}%;background:${s.colour}"></i></span><span style="width:52px;text-align:right">${s.metres} m</span></div>`).join('')}
      ${stockLines(r.usage)}
      ${r.colour_changes > 150 && printMode === 'economie' ? `<div class="warnline">⚠ ${r.colour_changes} changements de couleur : sans tour d'essuyage, des bavures et un marbrage sont probables. Le mode Équilibré (tour d'essuyage) les évite.</div>` : ''}
      ${(r.pauses || []).map(p => `<div class="warnline" style="color:var(--dim)">⏸ Pause après la couche ${p.layer - 1} (${p.run > 1 ? `pièce ${p.run} · ` : ''}pièce à ${p.z} mm), demandée à ${p.mm} mm</div>`).join('')}
      ${r.warnings.map(w => `<div class="warnline">⚠ ${esc(w)}</div>`).join('')}
      <p class="note" style="margin:10px 0 0">Fichier : ${esc(g)}</p>
      <button class="btn block" id="see-paths" style="margin-top:10px"><svg class="i"><use href="#i-layers"/></svg>Voir le tranchage couche par couche</button>${sendBlock(g)}</div>`;
    bindSend(); loadFiles(); lastGcode = g; $('viewtabs').hidden = false;
    $('see-paths').onclick = () => showPaths(g);
  } catch (e) { $('result').innerHTML = `<div class="result" style="border-color:var(--bad)"><b style="color:var(--bad)">Tranchage impossible</b><p class="note" style="margin:6px 0 0">${esc(e.message)}</p></div>`; }
  go.disabled = false; go.innerHTML = '<svg class="i"><use href="#i-layers"/></svg>Trancher';
};

/* cut into pieces: one row per piece */
function renderPieces(r) {
  const row = (label, p, extra = '') => `<div class="crow" style="border-top:1px solid var(--line);padding:10px 0">
    <div style="flex:1;min-width:0"><div style="font-weight:600">${label}</div><div class="note" style="margin:0">${extra}${esc(shortTime(p.time))} · ${p.total_m ?? p.filament_m} m</div></div>
    <div style="display:flex;gap:2px;flex:none">
    <button class="btn ghost" data-paths="${esc(p.gcode[0])}" title="Voir le tranchage"><svg class="i"><use href="#i-layers"/></svg></button>
    <button class="btn ghost" data-send="upload" data-file="${esc(p.gcode[0])}" title="Envoyer à l'imprimante" ${ctx.control ? '' : 'disabled'}><svg class="i"><use href="#i-send"/></svg></button>
    <a class="btn ghost" href="/lab/api/models/${encodeURIComponent(p.gcode[0])}" download title="Télécharger"><svg class="i"><use href="#i-download"/></svg></a></div></div>`;
  const time = r.pieces.reduce((a, p) => a + durSec(p.time), 0) + (r.pins ? durSec(r.pins.time) : 0);
  $('result').innerHTML = `<div class="result"><div class="stats"><div class="stat"><div class="v">${r.pieces.length}</div><div class="k">pièces</div></div>
    <div class="stat"><div class="v">${dur(time)}</div><div class="k">au total</div></div><div class="stat"><div class="v">${r.usage ? fmtG(r.usage.g) : r.total_m + ' m'}</div><div class="k">${r.usage ? 'filament · ' + euro(r.usage.eur) : 'filament'}</div></div></div>
    ${stockLines(r.usage)}
    <p class="note">Coupes : ${r.planes.map(planTxt).join(', ')}. Imprime les pièces une par une, puis assemble-les avec les chevilles et un peu de colle.</p>
    ${r.pieces.map((p, i) => row(`Pièce ${i + 1}`, p, `${sizeTxt(p.size_mm)} · `)).join('')}
    ${r.pins ? row(r.pins.small_pieces ? `Petites pièces (${r.pins.small_pieces}) + ${r.pins.count} chevilles` : `${r.pins.count} chevilles`, r.pins, r.pins.count ? `Ø ${r.pins.diameter_mm} × ${r.pins.length_mm} mm · ` : '') : ''}
    ${r.warnings.map(w => `<div class="warnline">⚠ ${esc(w)}</div>`).join('')}
    ${ctx.control ? '' : '<p class="note" style="margin:8px 0 0">Lecture seule : relance avec <code>cc2 --control dash</code> pour envoyer.</p>'}</div>`;
  $('result').querySelectorAll('[data-paths]').forEach(b => b.onclick = () => { lastGcode = b.dataset.paths; $('viewtabs').hidden = false; showPaths(b.dataset.paths); });
  bindSend(); loadFiles();
  const go = $('go'); go.disabled = false; go.innerHTML = '<svg class="i"><use href="#i-layers"/></svg>Trancher';
}

/* sending */
function sendBlock(name) {
  const off = !ctx.control;
  return `<div class="actions">
    <button class="btn primary" data-send="start" data-file="${esc(name)}" ${off ? 'disabled' : ''}><svg class="i"><use href="#i-play"/></svg>Imprimer maintenant</button>
    <div class="two"><button class="btn" data-send="upload" data-file="${esc(name)}" ${off ? 'disabled' : ''}><svg class="i"><use href="#i-send"/></svg>Envoyer</button>
    <a class="btn" href="/lab/api/models/${encodeURIComponent(name)}" download><svg class="i"><use href="#i-download"/></svg>Télécharger</a></div>
    <button class="btn ghost block" data-queue="${esc(name)}"><svg class="i"><use href="#i-plus"/></svg>Ajouter à la file d'attente</button>
    ${off ? '<p class="note" style="margin:0">Lecture seule : relance avec <code>cc2 --control dash</code> pour envoyer.</p>' : ''}</div>`;
}
function stockLines(u) {
  if (!u) return '';
  return (u.manques || []).map(t => `<div class="warnline">⚠ Bobine ${t.tray + 1} : il faut ${fmtG(t.g)}, il reste environ ${fmtG(t.restant_g)} sur la bobine. Change-la ou corrige son poids (onglet Imprimante).</div>`).join('');
}
/* start dialog: the CC2's own options and which CANVAS spool feeds each colour */
let launchCtx = null;
async function launchFile(name, { upload, button, onStarted }) {
  let plan;
  try { plan = await api('/print/plan/' + encodeURIComponent(name)); } catch (e) { toast(e.message, 'bad'); return; }
  launchCtx = { name, upload, button, plan, onStarted };
  // the model's name, not the G-code's (profile and plate suffixes)
  $('ln-t').textContent = name.replace(/\.gcode$/, '').replace(/(_canvas)?_\d+(\.\d+)?mm_.*?(_p(\d+))?$/, (m, c, p, q, n) => n ? ` · plateau ${n}` : '');
  $('ln-t').title = name;
  const trayOpt = (sel) => plan.trays.map(t => `<option value="${t.tray_id}" ${t.tray_id === sel ? 'selected' : ''}>Bobine ${t.pos + 1} · ${esc(t.name || t.type || "")}</option>`).join('');
  const sw = id => plan.trays.find(t => t.tray_id === id)?.colour || 'transparent';
  // sliced with a loaded spool's colour: that spool's own word (« Or »), else one from the hue
  const cname = hex => (plan.trays.find(t => t.colour?.toLowerCase() === hex?.toLowerCase())?.name || '')
    .replace(/^(PLA|PETG|ABS|ASA|TPU|PC|PA)\+?\s*((Silk|Matte|Mat|Basic|HS|Pro)\s+)*/i, '').trim() || colourName(hex);
  $('ln-map').innerHTML = !plan.tools.length ? '<p class="note">Fichier présent seulement sur l\'imprimante : elle utilisera son ordre de bobines habituel.</p>'
    : !plan.trays.length ? '<p class="note" style="color:var(--warn)">CANVAS illisible : l\'imprimante utilisera son ordre habituel.</p>'
    : plan.tools.map((t, i) => { const s0 = plan.slot_map[i]; return `<div class="ln-row"><span class="ln-sw" style="background:${t.colour}"></span>
        <span class="ln-l">${esc(cname(t.colour))}<small>${esc(t.type)}${t.m != null ? ' · ' + t.m + ' m' : ''}</small></span><span class="ln-arrow">→</span>
        <span class="ln-sw" data-sw="${i}" style="background:${sw(s0?.tray_id)}"></span><select data-map="${i}">${trayOpt(s0?.tray_id)}</select></div>
        ${s0?.far ? `<p class="note ln-far" data-far="${i}">⚠ Aucune bobine chargée n'a cette couleur : la plus proche est proposée.</p>` : ''}`; }).join('');
  const checkTypes = () => {
    const bad = plan.tools.map((t, i) => { const el = $('ln-map').querySelector(`[data-map="${i}"]`), tr = el && plan.trays.find(x => x.tray_id === +el.value);
      return tr && tr.type && t.type && tr.type.toUpperCase() !== t.type.toUpperCase() ? `${cname(t.colour)} tranchée en ${t.type}, mais la bobine ${tr.pos + 1} est du ${tr.type} : la CC2 peut refuser, et l'impression serait ratée. Re-tranche avec la bonne matière ou change de bobine.` : null; }).filter(Boolean);
    $('ln-warn').innerHTML = [...bad, ...(plan.warnings || [])].map(w => `<div class="warnline">⚠ ${esc(w)}</div>`).join('');
  };
  $('ln-map').querySelectorAll('[data-map]').forEach(el => el.onchange = () => { $('ln-map').querySelector(`[data-sw="${el.dataset.map}"]`).style.background = sw(+el.value); checkTypes(); });
  checkTypes();
  const st = plan.stock;
  $('ln-stock').innerHTML = st?.trays ? `<p class="note" style="margin:0">Filament : ${fmtG(st.g)} · ${euro(st.eur)}</p>` + stockLines(st) : '';
  const o = plan.options;
  $('ln-level').checked = o.bedlevel_force && !plan.tools.some(t => /TPU/i.test(t.type)); $('ln-check').checked = o.printer_check; $('ln-video').checked = o.delay_video;
  document.querySelectorAll('#ln-layout button').forEach(b => b.classList.toggle('on', b.dataset.layout === o.print_layout));
  $('ln-remember').checked = false; $('ln-go').disabled = !ctx.control;
  // a print already running: the CC2 would refuse, so offer the queue instead
  const now = await fetch('/status').then(r => r.json()).catch(() => null), busy = !!now && BUSY.has(now.print_status ?? 0);
  $('ln-busy').hidden = !busy; if (busy) $('ln-go').disabled = true;
  if (!busy && ctx.control) plateCheck();
  $('ln-queue').onclick = () => api('/queue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
    .then(q => { $('launch').close(); toast(`Ajouté à la file (${q.length}) : il se lancera depuis l'onglet Imprimante, plateau vidé`, 'ok'); })
    .catch(e => toast(e.message, 'bad'));
  $('ln-more').open = false; launchSummary();
  $('launch').showModal();
}
/* folded options, said in one line */
function launchSummary() {
  $('ln-sum').textContent = '· ' + [$('ln-check').checked ? 'vérifications' : '', $('ln-video').checked ? 'timelapse CC2' : '',
    'disposition ' + (document.querySelector('#ln-layout button.on')?.dataset.layout || 'A')].filter(Boolean).join(', ');
}
['ln-check', 'ln-video'].forEach(id => $(id).addEventListener('change', launchSummary));
document.querySelectorAll('#ln-layout button').forEach(b => b.onclick = () => { document.querySelectorAll('#ln-layout button').forEach(x => x.classList.toggle('on', x === b)); launchSummary(); });
/* a plain French name for a slicer colour (« Or », « Rouge ») instead of « Couleur 2 » */
function colourName(hex) {
  const m = /^#?([0-9a-f]{6})/i.exec(hex || ''); if (!m) return 'Couleur';
  const v = parseInt(m[1], 16), r = (v >> 16) / 255, g = (v >> 8 & 255) / 255, b = (v & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  const h = !d ? 0 : mx === r ? (60 * ((g - b) / d) + 360) % 360 : mx === g ? 60 * ((b - r) / d) + 120 : 60 * ((r - g) / d) + 240;
  if (l > .88 || (s < .15 && l > .75)) return 'Blanc';
  if (l < .12) return 'Noir';
  if (s < .15) return 'Gris';
  if (h < 15 || h >= 345) return l > .7 ? 'Rose' : 'Rouge';
  if (h < 40) return l < .35 ? 'Marron' : 'Orange';
  if (h < 65) return s < .75 && l < .6 ? 'Or' : 'Jaune';
  if (h < 165) return 'Vert';
  if (h < 200) return 'Turquoise';
  if (h < 255) return 'Bleu';
  if (h < 290) return 'Violet';
  return 'Rose';
}
$('ln-go').onclick = async () => {
  const { name, upload, button, plan } = launchCtx, go = $('ln-go');
  const slot_map = plan.tools.length && plan.trays.length ? plan.tools.map((t, i) => ({ t: t.t, tray_id: +$('ln-map').querySelector(`[data-map="${i}"]`).value })) : null;
  const body = { filename: name, slot_map, bedlevel_force: $('ln-level').checked, printer_check: $('ln-check').checked, delay_video: $('ln-video').checked,
    print_layout: document.querySelector('#ln-layout button.on')?.dataset.layout || 'A', remember: $('ln-remember').checked };
  go.disabled = true; go.innerHTML = '<span class="spin"></span>' + (upload ? 'Envoi…' : 'Lancement…');
  if (button) button.disabled = true;
  try {
    if (upload) {
      const blob = await (await fetch('/lab/api/models/' + encodeURIComponent(name))).blob(), fd = new FormData();
      fd.append('file', blob, name);
      const r = await fetch('/files/upload', { method: 'POST', body: fd }); const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || r.statusText);
      go.innerHTML = '<span class="spin"></span>Lancement…';
    }
    await api('/print/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    $('launch').close(); toast('Impression lancée : suis-la dans l\'onglet Imprimante', 'ok');
    launchCtx.onStarted?.();
  } catch (e) { toast('Lancement impossible : ' + e.message, 'bad'); }
  go.disabled = false; go.innerHTML = '<svg class="i"><use href="#i-play"/></svg>Lancer l\'impression';
  if (button) button.disabled = false;
};
function bindSend() {
  document.querySelectorAll('[data-queue]').forEach(b => b.onclick = () =>
    api('/queue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: b.dataset.queue }) })
      .then(q => toast(`Dans la file (${q.length}) : retrouve-la dans l'onglet Imprimante`, 'ok')).catch(e => toast(e.message, 'bad')));
  document.querySelectorAll('[data-send]').forEach(b => b.onclick = async () => {
    const start = b.dataset.send === 'start', name = b.dataset.file;
    if (start) return launchFile(name, { upload: true, button: b });
    b.disabled = true; const label = b.innerHTML; b.innerHTML = '<span class="spin"></span>Envoi…';
    try {
      const blob = await (await fetch('/lab/api/models/' + encodeURIComponent(name))).blob(), fd = new FormData();
      fd.append('file', blob, name); if (start) fd.append('start', 'true');
      const r = await fetch('/files/upload', { method: 'POST', body: fd }); const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || r.statusText);
      toast(start ? 'Impression lancée : ' + name : 'Envoyé à l\'imprimante : ' + name, 'ok');
    } catch (e) { toast('Envoi impossible : ' + e.message, 'bad'); }
    b.disabled = false; b.innerHTML = label;
  });
}

/* AI */
$('ai-open').onclick = async () => {
  $('ai').showModal();
  const c = await api('/comfy').catch(e => ({ online: false, error: e.message, workflows: [], url: '?' }));
  $('ai-status').innerHTML = c.online ? `<span style="color:var(--ok)">●</span> ComfyUI connecté (${esc(c.url)}) ${esc((c.devices || []).join(', '))}`
    : `<span style="color:var(--bad)">●</span> ComfyUI injoignable sur ${esc(c.url)}. Renseigne <code>[comfyui] url</code> dans config.toml avec l'adresse de la machine GPU.`;
  const order = w => (w === 'photo_vers_figurine_3d' ? 0 : w.startsWith('trellis_texte') ? 1 : w.startsWith('trellis') ? 2 : w.startsWith('photo') ? 3 : w.startsWith('hunyuan') ? 5 : 4);
  const wfs = [...c.workflows].sort((a, b) => order(a) - order(b));
  $('wf').innerHTML = wfs.length ? wfs.map(w => `<option value="${esc(w)}">${esc(WF_LABEL[w] || w)}</option>`).join('') : '<option value="">Aucun workflow dans workflows/</option>';
  $('gen').disabled = !c.online || !wfs.length; wfFields(); pollJobs();
};
const WF_LABEL = {
  photo_vers_figurine_3d: 'Photo → figurine 3D en couleurs (Qwen + TRELLIS.2, ≈ 9 min)',
  photo_vers_figurine: 'Photo → image de figurine seulement (≈ 40 s, pour essayer)',
  trellis_texte_vers_3d: 'Texte → 3D en couleurs (TRELLIS.2, ≈ 9 min)',
  trellis_image_vers_3d: 'Image → 3D en couleurs (TRELLIS.2, ≈ 8 min)',
  hunyuan_texte_vers_3d: 'Texte → 3D, forme seule (Hunyuan3D : licence non valable dans l\'UE)',
  hunyuan_image_vers_3d: 'Image → 3D, forme seule (Hunyuan3D : licence non valable dans l\'UE)',
};
function wfFields() {
  const w = $('wf').value || '', text = w.includes('texte'), photo = w.startsWith('photo');
  $('img').closest('.field').hidden = text; $('prompt').closest('.field').hidden = !text && !photo && !!w;
  $('prompt').closest('.field').querySelector('label').textContent = photo ? 'Consigne pour la figurine (optionnel, en anglais)' : 'Description de l\'objet (en anglais de préférence)';
  $('prompt').placeholder = photo ? 'vide = toutes les personnes en pied sur un socle commun' : 'ex. un petit perroquet rouge, jaune et bleu sur un socle rond';
}
$('wf').onchange = wfFields;
$('gen').onclick = async () => {
  const fd = new FormData(); fd.append('workflow', $('wf').value);
  if ($('prompt').value) fd.append('prompt', $('prompt').value); if ($('img').files[0]) fd.append('image', $('img').files[0]);
  if ($('wf').value.includes('texte') && !$('prompt').value.trim()) return toast('Décris l\'objet à générer', 'bad');
  if (!$('wf').value.includes('texte') && !$('img').files[0]) return toast('Choisis une image de départ', 'bad');
  try { await api('/generate', { method: 'POST', body: fd }); toast('Génération lancée sur la machine GPU. Le modèle arrivera dans la bibliothèque.', 'ok'); pollJobs(); } catch (e) { toast(e.message, 'bad'); }
};
let jobTimer;
async function pollJobs() {
  clearTimeout(jobTimer); const jobs = await api('/jobs').catch(() => []);
  $('jobs').innerHTML = jobs.map(j => `<div class="crow" style="flex-wrap:wrap"><span>${esc(WF_LABEL[j.workflow] || j.workflow)}</span><span style="margin-left:auto" class="note">${j.state === 'running' ? 'en cours…' : j.state === 'done' ? '✔ ' + esc(j.files.join(', ') || 'image prête') : '<span style="color:var(--bad)">' + esc(j.error) + '</span>'}</span>
    ${(j.images || []).map(im => `<img src="/lab/api/references/${encodeURIComponent(im)}" alt="Figurine intermédiaire" style="width:100%;border-radius:8px;margin-top:6px;border:1px solid var(--line)">`).join('')}</div>`).join('');
  if (jobs.some(j => j.state === 'running')) jobTimer = setTimeout(() => { if (!document.hidden) pollJobs(); }, 3000); else loadFiles();
}

/* made-to-measure parts: pick a kind, set the sizes, the 3D preview follows as you type */
let makeKinds = [], makeKey = '', makeView = null, makeTimer = 0, makeSeq = 0, makeSpools = [];
function makeValues() {
  const vals = {}; document.querySelectorAll('[data-mk]').forEach(el => { vals[el.dataset.mk] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? +el.value : el.value; });
  return vals;
}
function renderMake() {
  const k = makeKinds.find(x => x.key === makeKey) || makeKinds[0]; makeKey = k.key;
  $('make-kinds').innerHTML = makeKinds.map(x => `<button class="make-kind ${x.key === makeKey ? 'on' : ''}" data-kind="${x.key}" role="radio" aria-checked="${x.key === makeKey}">
    <b>${esc(x.title)}</b><span>${esc(x.description)}</span></button>`).join('');
  $('make-kinds').querySelectorAll('[data-kind]').forEach(b => b.onclick = () => { makeKey = b.dataset.kind; renderMake(); });
  $('make-fields').innerHTML = k.params.map(p => p.kind === 'choice'
    ? `<div class="field"><label for="mk-${p.name}">${esc(p.label)}</label><select id="mk-${p.name}" data-mk="${p.name}">${p.options.map(([v, l]) => `<option value="${esc(v)}" ${v === p.default ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>`
    : p.kind === 'image'
      ? `<div class="field full"><label for="mk-${p.name}">${esc(p.label)} <span>JPEG ou PNG, réduite avant l'envoi</span></label><input id="mk-${p.name}" type="file" accept="image/*"><input type="hidden" data-mk="${p.name}" id="mk-${p.name}-v"></div>`
    : p.kind === 'bool'
    ? `<div class="switch full"><label for="mk-${p.name}">${esc(p.label)}</label><input id="mk-${p.name}" data-mk="${p.name}" type="checkbox" ${p.default ? 'checked' : ''}></div>`
    : p.kind === 'text'
      ? `<div class="field full"><label for="mk-${p.name}">${esc(p.label)}</label><textarea id="mk-${p.name}" data-mk="${p.name}" rows="2">${esc(p.default)}</textarea></div>`
      : `<div class="field"><label for="mk-${p.name}">${esc(p.label)} <span>${p.lo}–${p.hi}${p.unit ? ' ' + p.unit : ''}</span></label><input id="mk-${p.name}" data-mk="${p.name}" type="number" min="${p.lo}" max="${p.hi}" step="${p.kind === 'int' ? 1 : 0.1}" value="${p.default}"></div>`).join('');
  $('make-fields').querySelectorAll('[data-mk]').forEach(el => el.oninput = el.onchange = () => { clearTimeout(makeTimer); makeTimer = setTimeout(makePreview, 250); });
  $('make-fields').querySelectorAll('input[type=file]').forEach(inp => inp.onchange = () => {   // the photo, shrunk to 700 px here
    const file = inp.files[0]; if (!file) return;
    const img = new Image(); img.onload = () => {
      const k = Math.min(1, 700 / Math.max(img.width, img.height)), c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      $(inp.id + '-v').value = c.toDataURL('image/jpeg', 0.9); URL.revokeObjectURL(img.src); makePreview();
    };
    img.src = URL.createObjectURL(file);
  });
  makePreview();
}
// a small 3D view inside a dialog (made-to-measure parts, assembly): renders only while its dialog is open
function miniViewer(hostId, dialogId) {   // dialogId: the dialog it lives in, or a function saying when it is seen
  if (!renderer) return null;
  const host = $(hostId), r = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  r.setPixelRatio(devicePixelRatio); host.append(r.domElement);
  const sc = new THREE.Scene(), c = new THREE.PerspectiveCamera(35, 1, 1, 5000); c.up.set(0, 0, 1);
  sc.add(new THREE.HemisphereLight(0xffffff, 0x445566, 2.2)); const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(1, -2, 3); sc.add(sun);
  const ctl = new OrbitControls(c, r.domElement); ctl.enableDamping = true;
  // the drawing buffer follows the box; the box's size comes from the layout, never from the canvas (it would push the dialog wider)
  const size = () => { const w = host.clientWidth, h = host.clientHeight; if (w && h) { r.setSize(w, h, false); c.aspect = w / h; c.updateProjectionMatrix(); } };
  new ResizeObserver(size).observe(host); size();
  const seen = typeof dialogId === 'function' ? dialogId : () => $(dialogId).open;
  let need = true;
  ctl.addEventListener('change', () => { need = true; });
  r.setAnimationLoop(() => {
    if (!seen()) { need = true; return; }   // reopen: a first picture right away
    ctl.update();
    if (need) { need = false; r.render(sc, c); }
  });
  const v = { sc, c, ctl, obj: null,
    render: () => { need = true; },   // callers redraw after moving the nozzle or the layer ranges
    set(obj, refit) {   // swap the shown object; refit the camera only when asked (keeps the user's angle otherwise)
      need = true;
      if (v.obj) { v.sc.remove(v.obj); disposeObj(v.obj); }
      v.obj = obj; if (!obj) return; v.sc.add(obj);
      if (!refit) return;
      const box = new THREE.Box3().setFromObject(obj), ctr = box.getCenter(new THREE.Vector3()), d = box.getSize(new THREE.Vector3()).length() * 1.6 || 100;
      ctl.target.copy(ctr); c.position.set(ctr.x + d * .6, ctr.y - d * .8, ctr.z + d * .6); c.near = d / 100; c.far = d * 50; c.updateProjectionMatrix();
    } };
  return v;
}
function makeViewer() { return makeView || (makeView = miniViewer('make-3d', 'make')); }
async function makePreview() {
  const seq = ++makeSeq, v = makeViewer();
  try {
    const res = await fetch(`/lab/api/parametric/${makeKey}/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...makeValues(), _couleurs: makeSpools }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const [x, y, z] = (res.headers.get('X-Size') || '').split(',').map(Number);
    if (seq !== makeSeq) return;
    $('make-size').className = 'make-size'; $('make-size').textContent = `Sur le plateau : ${sizeTxt([x, y, z])}`;
    $('make-go').disabled = false;
    if (!v) return;
    const g = await res.arrayBuffer().then(b => new Promise((ok, ko) => new GLTFLoader().parse(b, '', ok, ko)));
    if (seq !== makeSeq) return;
    g.scene.traverse(o => { if (o.isMesh) o.material = new THREE.MeshStandardMaterial({ vertexColors: !!o.geometry.attributes.color, color: o.geometry.attributes.color ? 0xffffff : 0xcccccc, roughness: .6, flatShading: true }); });
    v.set(g.scene, v.fitted !== makeKey); v.fitted = makeKey;   // the GLB is written Z-up, like the plate; frame once per kind
  } catch (e) {
    if (seq !== makeSeq) return;
    $('make-size').className = 'make-size bad'; $('make-size').textContent = e.message; $('make-go').disabled = true;
  }
}
$('make-open').onclick = async () => {
  if (!makeKinds.length) makeKinds = await api('/parametric');
  // the preview in the colours of the spools loaded now (slot order; an empty slot keeps the palette colour)
  api('/canvas/bobines').then(list => { makeSpools = [1, 2, 3, 4].map(s => list.find(t => t.slot === s)?.hex || ''); if ($('make').open) makePreview(); }).catch(() => {});
  $('make').showModal(); renderMake();
};
$('make-go').onclick = async () => {
  const b = $('make-go'); b.disabled = true; b.innerHTML = '<span class="spin"></span>Création…';
  try {
    const r = await api(`/parametric/${makeKey}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(makeValues()) });
    $('make').close(); toast('Pièce créée : ' + r.name, 'ok');
    $('t-lab').click(); await loadFiles(); select(files.find(f => f.name === r.name));
  } catch (e) { toast(e.message, 'bad'); }
  b.disabled = false; b.innerHTML = '<svg class="i"><use href="#i-plus"/></svg>Créer la pièce';
};

/* assemble parts: search the meshes, give each kept part a spool, see the result in colour before building it */
const asmSlots = {};
let asmTrays = {}, asmView = null, asmSeq = 0;   // spools in the CANVAS by slot: the swatches show the printer's real colours
const asmGeo = new Map();                           // file name -> loaded geometry (kept while the page lives)
const asmHex = s => asmTrays[s]?.hex || SLOT[s - 1];
function renderAsm() {
  const q = $('asm-q').value.toLowerCase();
  const meshes = files.filter(f => ['stl', 'obj'].includes(f.ext) && f.kind !== 'technique' && (!q || f.name.toLowerCase().includes(q)))
    .sort((a, b) => (!!asmSlots[b.name] - !!asmSlots[a.name]));   // chosen parts first
  $('asm-list').innerHTML = meshes.length ? meshes.map(f => `<div class="asm-row ${asmSlots[f.name] ? 'on' : ''}">
    <img class="fthumb" loading="lazy" alt="" src="/lab/api/models/${encodeURIComponent(f.name)}/thumb.png?v=${Math.round(f.mtime)}" onerror="this.style.visibility='hidden'">
    <span class="fname" title="${esc(f.name)}">${esc(pretty(f.name))}</span><div class="slots">
    <button class="slot ${!asmSlots[f.name] ? 'on' : ''}" data-f="${esc(f.name)}" data-s="0" title="Ignorer" aria-label="Ignorer">–</button>
    ${[1, 2, 3, 4].map(s => `<button class="slot ${asmSlots[f.name] === s ? 'on' : ''}" data-f="${esc(f.name)}" data-s="${s}" title="Bobine ${s}${asmTrays[s] ? ' · ' + esc(asmTrays[s].name) : asmTrays.read ? ' · vide' : ''}" aria-label="Bobine ${s}"><i style="background:${asmHex(s)}"></i></button>`).join('')}</div></div>`).join('')
    : `<div class="empty">${q ? 'Aucune pièce ne correspond.' : 'Aucune pièce STL ou OBJ dans la bibliothèque.'}</div>`;
  $('asm-spools').innerHTML = !asmTrays.read ? 'Bobines du CANVAS non lues : couleurs indicatives.'
    : [1, 2, 3, 4].map(s => `<span style="white-space:nowrap"><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${asmTrays[s]?.hex || 'transparent'};border:1px solid var(--line)"></i> ${s} ${asmTrays[s] ? esc(asmTrays[s].name) : 'vide'}</span>`).join(' · ');
  $('asm-list').querySelectorAll('.slot').forEach(b => b.onclick = () => { const s = +b.dataset.s; if (s) asmSlots[b.dataset.f] = s; else delete asmSlots[b.dataset.f]; renderAsm(); asmPreview(); });
  const n = Object.keys(asmSlots).length;
  if (!$('asm-name').dataset.typed) {   // the chosen parts' common name, until the user types one
    const names = Object.keys(asmSlots).map(pretty);
    let common = names[0] || '';
    for (const x of names) while (common && !x.startsWith(common)) common = common.slice(0, -1);
    $('asm-name').value = common.replace(/[\s_-]+$/, '') || 'assemblage';
  }
  $('asm-go').textContent = n ? `Assembler ${n} pièce${n > 1 ? 's' : ''}` : 'Assembler'; $('asm-go').disabled = !n;
}
async function asmPreview() {
  const seq = ++asmSeq, chosen = Object.entries(asmSlots);
  asmView = asmView || miniViewer('asm-3d', 'asm');
  if (!chosen.length) { asmView?.set(null); $('asm-size').textContent = 'Choisis une bobine pour au moins une pièce'; return; }
  $('asm-size').textContent = 'Chargement…';
  try {
    const group = new THREE.Group(), loader = new STLLoader();
    for (const [name, slot] of chosen) {
      if (!asmGeo.has(name)) {
        const f = files.find(x => x.name === name);
        if (f?.ext !== 'stl') continue;   // OBJ parts are assembled but not previewed
        asmGeo.set(name, loader.parse(await (await fetch('/lab/api/models/' + encodeURIComponent(name))).arrayBuffer()));
      }
      group.add(new THREE.Mesh(asmGeo.get(name), new THREE.MeshStandardMaterial({ color: asmHex(slot), roughness: .6 })));
    }
    if (seq !== asmSeq) return;
    const sz = new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3());
    $('asm-size').textContent = group.children.length ? `${sizeTxt([sz.x, sz.y, sz.z])} (unités du fichier)` : 'Aperçu disponible pour les STL';
    asmView?.set(group, true);
  } catch (e) { if (seq === asmSeq) $('asm-size').textContent = 'Aperçu impossible : ' + e.message; }
}
$('asm-q').oninput = renderAsm;
$('asm-name').oninput = () => { $('asm-name').dataset.typed = '1'; };
$('asm-open').onclick = async () => {
  asmTrays = {}; $('asm-q').value = ''; delete $('asm-name').dataset.typed; renderAsm(); $('asm').showModal(); asmPreview();
  try { asmTrays = { read: true, ...Object.fromEntries((await api('/canvas/bobines')).map(t => [t.slot, t])) }; } catch { /* printer away */ }
  renderAsm(); asmPreview();
};
$('asm-go').onclick = async () => {
  const parts = Object.entries(asmSlots).map(([name, slot]) => ({ name, slot }));
  if (!parts.length) return toast('Choisis une bobine pour au moins une pièce', 'bad');
  const top = Math.max(...parts.map(p => p.slot)), b = $('asm-go'); b.disabled = true; b.textContent = 'Assemblage…';
  try {
    const r = await api('/multicolor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: $('asm-name').value, parts,
      filaments: Array.from({ length: top }, (_, i) => asmTrays[i + 1]?.filament || 'PLA'),
      colours: asmTrays.read ? Array.from({ length: top }, (_, i) => asmTrays[i + 1]?.hex || '') : null }) });
    $('asm').close(); toast(asmTrays.read ? 'Assemblé et tranché avec les bobines du CANVAS : ' + r.project : 'Assemblé : ' + r.project + '. Règle les filaments puis tranche.', 'ok');
    await loadFiles(); select(files.find(f => f.name === r.project));
  } catch (e) { toast(e.message, 'bad'); }
  b.disabled = false; renderAsm();
};



export { buildPaths, miniViewer, MODE_NOTE, WF_LABEL, advCount, advValues, adviceSeq, adviceTimer, analysis, applyFix, asmSlots, b64, bindSend, cam, controls, current, drawLayers, drop, files, frame, framedFor, grid, hint, infillTouched, info, jobTimer, lastGcode, launchCtx, launchFile, loadAdvice, loadFiles, makeKey, makeKinds, mapString, mapping, matchSpools, mview, paths, pathsFor, phone, plateMat, pollJobs, prepBody, preview, previewKey, printMode, printUsage, renderAdvanced, renderAsm, renderColours, renderFiles, renderMake, renderMode, renderPieces, renderRot, renderUsages, rotatedSize, rotation, scene, scheduleAdvice, sel, select, sendBlock, setUsage, setView, show, showCut, showPaths, sizeNote, stage, stockLines, trays, upload, wfFields };

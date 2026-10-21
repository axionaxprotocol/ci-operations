const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const Fleet3D = require(path.join(__dirname, 'fleet3d.js'));
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

const MIN = 60000;
const NOW = Date.parse('2026-10-20T12:00:00Z');
const WINDOW = 60 * MIN;

function job(overrides) {
  return Object.assign({
    repo: 'o/a', name: 'build', workflow: 'CI', runner: 'w1',
    status: 'completed', conclusion: 'success',
    started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:55:00Z',
  }, overrides);
}

// --- layout -----------------------------------------------------------------

test('a job with a runner and a start time becomes a bar', () => {
  const layout = Fleet3D.buildLayout([job()], {now: NOW, windowMs: WINDOW});
  assert.equal(layout.boxes.length, 1);
  assert.equal(layout.boxes[0].repo, 'o/a');
  assert.equal(layout.boxes[0].runner, 'w1');
});

test('jobs without a runner or a start time are not shown', () => {
  const layout = Fleet3D.buildLayout([
    job({runner: undefined}),
    job({started: undefined}),
    job({started: null}),
  ], {now: NOW, windowMs: WINDOW});
  assert.equal(layout.boxes.length, 0);
});

test('a job outside the time window is not shown', () => {
  const layout = Fleet3D.buildLayout([
    job({started: '2026-10-20T09:00:00Z', completed: '2026-10-20T09:05:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  assert.equal(layout.boxes.length, 0);
});

test('a running job is drawn up to the current time', () => {
  const layout = Fleet3D.buildLayout([
    job({status: 'in_progress', conclusion: null, completed: null,
         started: '2026-10-20T11:58:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  assert.equal(layout.boxes.length, 1);
  assert.ok(layout.boxes[0].x1 > layout.boxes[0].x0, 'a running job must have length');
});

test('repositories are placed on separate depth planes', () => {
  const layout = Fleet3D.buildLayout([
    job({repo: 'o/a'}),
    job({repo: 'o/b'}),
  ], {now: NOW, windowMs: WINDOW});
  const z = layout.boxes.map(b => b.z);
  assert.notEqual(z[0], z[1], 'different repositories must not share a depth plane');
  assert.equal(layout.planes.length, 2);
  assert.deepEqual(layout.planes.map(p => p.repo).sort(), ['o/a', 'o/b']);
});

test('runners within a repository get their own row', () => {
  const layout = Fleet3D.buildLayout([
    job({runner: 'w1'}),
    job({runner: 'w2'}),
  ], {now: NOW, windowMs: WINDOW});
  const y = layout.boxes.map(b => b.y);
  assert.notEqual(y[0], y[1], 'different runners must not share a row');
  assert.equal(layout.rows.length, 2);
});

test('a longer job is a longer bar', () => {
  const short = Fleet3D.buildLayout([
    job({started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:51:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  const long = Fleet3D.buildLayout([
    job({started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:59:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  const shortLen = short.boxes[0].x1 - short.boxes[0].x0;
  const longLen = long.boxes[0].x1 - long.boxes[0].x0;
  assert.ok(longLen > shortLen * 5, 'duration must drive the bar length');
});

test('an instant job still has a visible bar', () => {
  const layout = Fleet3D.buildLayout([
    job({started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:50:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  assert.ok(layout.boxes[0].x1 > layout.boxes[0].x0, 'a zero-length job must still be visible');
});

test('bar colour follows the conclusion', () => {
  const layout = Fleet3D.buildLayout([
    job({conclusion: 'success', started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:51:00Z'}),
    job({conclusion: 'failure', started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:51:00Z'}),
    job({conclusion: 'cancelled', started: '2026-10-20T11:50:00Z', completed: '2026-10-20T11:51:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  const byConclusion = {};
  layout.boxes.forEach(b => { byConclusion[b.conclusion] = b.color.join(','); });
  assert.notEqual(byConclusion.success, byConclusion.failure);
  assert.notEqual(byConclusion.success, byConclusion.cancelled);
});

test('the layout is deterministic for the same input', () => {
  const jobs = [job({runner: 'w2'}), job({runner: 'w1'}), job({repo: 'o/b'})];
  const a = Fleet3D.buildLayout(jobs, {now: NOW, windowMs: WINDOW});
  const b = Fleet3D.buildLayout(jobs, {now: NOW, windowMs: WINDOW});
  assert.deepEqual(
    a.boxes.map(x => [x.repo, x.runner, x.x0, x.y, x.z]),
    b.boxes.map(x => [x.repo, x.runner, x.x0, x.y, x.z]));
});

test('the time axis carries readable ticks', () => {
  const layout = Fleet3D.buildLayout([job()], {now: NOW, windowMs: WINDOW});
  assert.ok(layout.ticks.length >= 2, 'the time axis needs ticks');
  assert.ok(layout.ticks.every(t => typeof t.label === 'string' && t.label.length > 0));
  assert.ok(layout.ticks.every(t => Number.isFinite(t.x)));
});

test('the layout reports bounds that contain every bar', () => {
  const layout = Fleet3D.buildLayout([
    job(), job({repo: 'o/b', runner: 'w9', started: '2026-10-20T11:30:00Z'}),
  ], {now: NOW, windowMs: WINDOW});
  layout.boxes.forEach(b => {
    assert.ok(b.x0 >= layout.bounds.minX - 1e-6);
    assert.ok(b.x1 <= layout.bounds.maxX + 1e-6);
    assert.ok(b.y >= layout.bounds.minY - 1e-6);
    assert.ok(b.y <= layout.bounds.maxY + 1e-6);
  });
});

test('an empty input still produces a usable layout', () => {
  const layout = Fleet3D.buildLayout([], {now: NOW, windowMs: WINDOW});
  assert.equal(layout.boxes.length, 0);
  assert.ok(layout.bounds);
  assert.ok(Array.isArray(layout.ticks));
});

test('a separator inside a name cannot make two jobs look alike', () => {
  // "a b" + "c" and "a" + "b c" must stay different rows.
  const layout = Fleet3D.buildLayout([
    job({repo: 'o/a b', runner: 'c'}),
    job({repo: 'o/a', runner: 'b c'}),
  ], {now: NOW, windowMs: WINDOW});
  const keys = layout.boxes.map(b => b.key);
  assert.equal(new Set(keys).size, 2, 'the two jobs must have different keys');
  const rows = new Set(layout.boxes.map(b => b.y + ':' + b.z));
  assert.equal(rows.size, 2, 'the two jobs must not share a row');
});

test('the engine file contains no stray control bytes', () => {
  const raw = fs.readFileSync(path.join(__dirname, 'fleet3d.js'));
  assert.equal(raw.includes(0), false, 'the source must stay plain text');
});

// --- matrix maths ----------------------------------------------------------

test('a point straight ahead of the camera projects to the centre of the screen', () => {
  const view = Fleet3D.mat4.lookAt(new Float32Array(16), [0, 0, 10], [0, 0, 0], [0, 1, 0]);
  const proj = Fleet3D.mat4.perspective(new Float32Array(16), Math.PI / 3, 1.5, 0.1, 100);
  const mvp = Fleet3D.mat4.multiply(new Float32Array(16), proj, view);
  const p = Fleet3D.mat4.project(mvp, [0, 0, 0]);
  assert.ok(Math.abs(p.x) < 1e-5, 'x must be centred, got ' + p.x);
  assert.ok(Math.abs(p.y) < 1e-5, 'y must be centred, got ' + p.y);
  assert.ok(p.z > -1 && p.z < 1, 'z must be inside the clip range, got ' + p.z);
});

test('a point to the right of the camera projects to the right of the screen', () => {
  const view = Fleet3D.mat4.lookAt(new Float32Array(16), [0, 0, 10], [0, 0, 0], [0, 1, 0]);
  const proj = Fleet3D.mat4.perspective(new Float32Array(16), Math.PI / 3, 1.5, 0.1, 100);
  const mvp = Fleet3D.mat4.multiply(new Float32Array(16), proj, view);
  const p = Fleet3D.mat4.project(mvp, [1, 0, 0]);
  assert.ok(p.x > 0, 'x must be positive, got ' + p.x);
});

test('a point behind the camera is reported as invisible', () => {
  const view = Fleet3D.mat4.lookAt(new Float32Array(16), [0, 0, 10], [0, 0, 0], [0, 1, 0]);
  const proj = Fleet3D.mat4.perspective(new Float32Array(16), Math.PI / 3, 1.5, 0.1, 100);
  const mvp = Fleet3D.mat4.multiply(new Float32Array(16), proj, view);
  const p = Fleet3D.mat4.project(mvp, [0, 0, 40]);
  assert.equal(p.visible, false);
});

test('inverting a matrix recovers the original', () => {
  const view = Fleet3D.mat4.lookAt(new Float32Array(16), [3, 4, 10], [1, 2, 3], [0, 1, 0]);
  const inv = Fleet3D.mat4.invert(new Float32Array(16), view);
  const round = Fleet3D.mat4.multiply(new Float32Array(16), inv, view);
  for (let i = 0; i < 16; i++) {
    const expected = i % 5 === 0 ? 1 : 0;
    assert.ok(Math.abs(round[i] - expected) < 1e-4, 'index ' + i + ' is ' + round[i]);
  }
});

test('multiplying by an identity matrix changes nothing', () => {
  const m = Fleet3D.mat4.perspective(new Float32Array(16), 1, 1, 0.1, 100);
  const id = Fleet3D.mat4.identity(new Float32Array(16));
  const out = Fleet3D.mat4.multiply(new Float32Array(16), m, id);
  for (let i = 0; i < 16; i++) assert.ok(Math.abs(out[i] - m[i]) < 1e-6);
});

// --- picking ----------------------------------------------------------------

test('a ray that passes through a bar hits it', () => {
  const hit = Fleet3D.rayBox([0, 0, 5], [0, 0, -1], {min: [-1, -1, -1], max: [1, 1, 1]});
  assert.ok(hit !== null && hit > 0, 'the ray must hit the box');
});

test('a ray that misses a bar reports no hit', () => {
  assert.equal(Fleet3D.rayBox([0, 5, 5], [0, 0, -1], {min: [-1, -1, -1], max: [1, 1, 1]}), null);
});

test('a ray pointing away from a bar reports no hit', () => {
  assert.equal(Fleet3D.rayBox([0, 0, 5], [0, 0, 1], {min: [-1, -1, -1], max: [1, 1, 1]}), null);
});

test('the nearest box along a ray is the one reported', () => {
  const near = Fleet3D.rayBox([0, 0, 5], [0, 0, -1], {min: [-1, -1, 3], max: [1, 1, 4]});
  const far = Fleet3D.rayBox([0, 0, 5], [0, 0, -1], {min: [-1, -1, -4], max: [1, 1, -3]});
  assert.ok(near < far, 'the closer box must have the smaller distance');
});

// --- camera -----------------------------------------------------------------

test('the camera starts in a sensible place and can be orbited', () => {
  const camera = Fleet3D.createCamera();
  assert.ok(camera.distance > 0);
  const before = camera.yaw;
  Fleet3D.orbit(camera, 0.5, 0);
  assert.notEqual(camera.yaw, before);
});

test('orbiting cannot flip the camera upside down', () => {
  const camera = Fleet3D.createCamera();
  Fleet3D.orbit(camera, 0, 100);
  assert.ok(camera.pitch <= Math.PI / 2 + 1e-6, 'pitch must stay below the horizon');
  Fleet3D.orbit(camera, 0, -100);
  assert.ok(camera.pitch >= -Math.PI / 2 - 1e-6, 'pitch must stay above the nadir');
});

test('zooming is clamped to a usable range', () => {
  const camera = Fleet3D.createCamera();
  Fleet3D.zoom(camera, -100000);
  assert.ok(camera.distance >= Fleet3D.MIN_DISTANCE);
  Fleet3D.zoom(camera, 100000);
  assert.ok(camera.distance <= Fleet3D.MAX_DISTANCE);
});

test('the camera can be reset to its default view', () => {
  const camera = Fleet3D.createCamera();
  Fleet3D.orbit(camera, 1, 1);
  Fleet3D.zoom(camera, 500);
  Fleet3D.resetCamera(camera);
  assert.equal(camera.yaw, Fleet3D.createCamera().yaw);
  assert.equal(camera.pitch, Fleet3D.createCamera().pitch);
  assert.equal(camera.distance, Fleet3D.createCamera().distance);
});

test('framing points the camera at the middle of the data', () => {
  const layout = Fleet3D.buildLayout([job()], {now: NOW, windowMs: WINDOW});
  const camera = Fleet3D.createCamera();
  Fleet3D.frameLayout(camera, layout);
  const b = layout.bounds;
  assert.ok(Math.abs(camera.target[0] - (b.minX + b.maxX) / 2) < 1e-6);
  assert.ok(Math.abs(camera.target[1] - (b.minY + b.maxY) / 2) < 1e-6);
  assert.ok(Math.abs(camera.target[2] - (b.minZ + b.maxZ) / 2) < 1e-6);
});

test('framing pulls the camera back far enough to see the whole volume', () => {
  const layout = Fleet3D.buildLayout([job()], {now: NOW, windowMs: WINDOW});
  const camera = Fleet3D.createCamera();
  Fleet3D.frameLayout(camera, layout);
  const span = layout.bounds.maxX - layout.bounds.minX;
  assert.ok(camera.distance > span, 'the camera must be far enough back to fit the time axis');
  assert.ok(camera.distance <= Fleet3D.MAX_DISTANCE);
});

test('framing a tiny scene does not put the camera inside it', () => {
  const layout = Fleet3D.buildLayout([], {now: NOW, windowMs: WINDOW});
  const camera = Fleet3D.createCamera();
  Fleet3D.frameLayout(camera, layout);
  assert.ok(camera.distance >= Fleet3D.MIN_DISTANCE);
});

test('framing makes the volume fill the frame instead of sitting in a corner', () => {
  const layout = Fleet3D.buildLayout([
    job(), job({repo: 'o/b', runner: 'w9'}), job({runner: 'w2'}),
  ], {now: NOW, windowMs: WINDOW});
  const camera = Fleet3D.createCamera();
  Fleet3D.frameLayout(camera, layout, 2.1);
  const mvp = Fleet3D.viewProjection(camera, 2.1);
  const b = layout.bounds;
  const corners = [];
  [b.minX, b.maxX].forEach(x => [b.minY, b.maxY].forEach(y =>
    [b.minZ, b.maxZ].forEach(z => corners.push([x, y, z]))));
  let extent = 0;
  corners.forEach(c => {
    const p = Fleet3D.mat4.project(mvp, c);
    if (p.visible) extent = Math.max(extent, Math.abs(p.x), Math.abs(p.y));
  });
  assert.ok(extent > 0.6, 'the volume must fill the frame, got ' + extent.toFixed(3));
  assert.ok(extent <= 0.95, 'the volume must not overflow the frame, got ' + extent.toFixed(3));
});

test('framing respects the aspect ratio it is given', () => {
  const layout = Fleet3D.buildLayout([job()], {now: NOW, windowMs: WINDOW});
  const wide = Fleet3D.createCamera();
  const tall = Fleet3D.createCamera();
  Fleet3D.frameLayout(wide, layout, 3);
  Fleet3D.frameLayout(tall, layout, 0.8);
  assert.notEqual(Math.round(wide.distance), Math.round(tall.distance));
});

// --- integration with the dashboard ----------------------------------------

test('the viewer gives up cleanly when the browser has no WebGL2', () => {
  const fakeCanvas = {getContext: () => null};
  assert.equal(Fleet3D.createViewer(fakeCanvas), null);
});

test('the viewer gives up cleanly when there is no canvas at all', () => {
  assert.equal(Fleet3D.createViewer(null), null);
  assert.equal(Fleet3D.createViewer(undefined), null);
});

test('the viewer gives up cleanly when the canvas cannot be created', () => {
  const fakeCanvas = {getContext: () => ({})};
  assert.equal(Fleet3D.createViewer(fakeCanvas), null);
});

test('the dashboard loads the 3D engine as a same-origin script', () => {
  assert.match(html, /<script src="fleet3d\.js"><\/script>/);
});

test('the 3D view is reachable from the navigation', () => {
  assert.match(html, /href="#volume"/);
  assert.match(html, /id="volume"/);
});

test('the 3D view has a canvas and an accessible description', () => {
  assert.match(html, /<canvas id="volume-canvas"/);
  assert.match(html, /aria-label="[^"]*3D[^"]*"/i);
});

test('the 3D view explains how to move the camera', () => {
  assert.match(html, /drag to orbit/i);
  assert.match(html, /scroll to zoom/i);
});

test('the 3D engine is only started when the browser really supports it', () => {
  assert.match(html, /Fleet3D/);
  assert.match(html, /createViewer/);
});

test('the content security policy allows the same-origin 3D script', () => {
  const source = fs.readFileSync(path.join(__dirname, 'ci_dashboard.py'), 'utf8');
  assert.match(source, /script-src 'self' 'unsafe-inline'/);
});

test('the 3D engine is bundled into the packaged application', () => {
  const source = fs.readFileSync(path.join(__dirname, 'build_desktop.py'), 'utf8');
  assert.match(source, /fleet3d\.js/);
});

test('the 3D engine does not reach the network', () => {
  const source = fs.readFileSync(path.join(__dirname, 'fleet3d.js'), 'utf8');
  assert.doesNotMatch(source, /https?:\/\/(?!www\.w3\.org)/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /XMLHttpRequest/);
});

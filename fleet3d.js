/**
 * Interactive 3D view of CI execution history.
 *
 * The scene is an "execution volume": time runs along the X axis, each
 * repository occupies its own depth plane, and each runner gets a row inside
 * that plane. A job is a cable arcing from its start to its end, coloured by
 * its conclusion, with a block marking where it started.
 *
 * The look is an isometric technical illustration: a warm parchment ground, an
 * orthographic camera, flat three-tone shading, a dark outline on every solid
 * edge, and faint circuit-trace artwork behind the data. The renderer is
 * hand-written WebGL2 with no third-party dependency, so the packaged
 * application stays self-contained and never reaches the network. Everything
 * except the drawing itself is pure maths and can be unit tested without a GPU.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Fleet3D = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const MINUTE = 60000;
  const MIN_DISTANCE = 12;
  const MAX_DISTANCE = 900;
  const ROW_HEIGHT = 3.4;
  const PLANE_DEPTH = 15;
  const BLOCK_SIZE = 2.2;
  const MIN_BAR_LENGTH = 1.0;
  const FRAME_FILL = 0.84;

  // Heights above the platform surface.
  const PLATFORM_TOP = 0;
  const PLATFORM_DEPTH_DOWN = 1.3;
  const GRID_Y = 0.05;
  const SHADOW_Y = 0.12;
  const BLOCK_Y = 0.22;

  // Palette taken from the reference illustration: a warm parchment ground, a
  // near-black outline, and the jumper-wire colours for the results.
  const PALETTE = {
    ground: [0.961, 0.922, 0.859],
    trace: [0.933, 0.898, 0.835],
    grid: [0.843, 0.765, 0.651],
    platform: [0.906, 0.851, 0.749],
    platformEdge: [0.769, 0.671, 0.529],
    shadow: [0.639, 0.549, 0.435],
    outline: [0.063, 0.063, 0.125],
  };

  const COLORS = {
    success: [0.235, 0.627, 0.392],
    failure: [0.784, 0.235, 0.235],
    timed_out: [0.784, 0.235, 0.235],
    action_required: [0.784, 0.235, 0.235],
    startup_failure: [0.784, 0.235, 0.235],
    cancelled: [0.627, 0.620, 0.596],
    skipped: [0.627, 0.620, 0.596],
    neutral: [0.627, 0.620, 0.596],
    running: [0.941, 0.706, 0.235],
  };
  const DEFAULT_COLOR = [0.941, 0.706, 0.235];

  function colorFor(conclusion, status) {
    if (status === 'in_progress' || status === 'queued' || status === 'waiting') return COLORS.running;
    if (!conclusion) return DEFAULT_COLOR;
    return COLORS[conclusion] || COLORS.neutral;
  }

  function parseTime(value) {
    if (!value) return NaN;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  /**
   * Keys are built with JSON.stringify so a separator inside a name can never
   * make two different jobs look like the same one.
   */
  function rowKeyFor(repo, runner) {
    return JSON.stringify([repo || '', runner || '']);
  }

  function boxKeyFor(repo, runner, runId, jobId) {
    return JSON.stringify([repo || '', runner || '', runId || '', jobId || '']);
  }

  /**
   * Turn the job list into a set of positioned bars plus the axis furniture
   * needed to label them. Pure: the same input always yields the same output.
   */
  function buildLayout(jobs, options) {
    const opts = options || {};
    const now = Number.isFinite(opts.now) ? opts.now : Date.now();
    const windowMs = Number.isFinite(opts.windowMs) && opts.windowMs > 0 ? opts.windowMs : 60 * MINUTE;
    const start = now - windowMs;

    const visible = (jobs || []).filter(function (job) {
      if (!job || !job.runner) return false;
      const began = parseTime(job.started);
      if (!Number.isFinite(began)) return false;
      const ended = parseTime(job.completed);
      const finishes = Number.isFinite(ended) ? ended : now;
      return began < now && finishes > start;
    });

    const repos = [];
    const seenRepo = {};
    const rows = [];
    const seenRow = {};
    visible.forEach(function (job) {
      const repo = job.repo || 'unknown repository';
      if (!seenRepo[repo]) {
        seenRepo[repo] = true;
        repos.push(repo);
      }
      const rowKey = rowKeyFor(repo, job.runner);
      if (!seenRow[rowKey]) {
        seenRow[rowKey] = true;
        rows.push({key: rowKey, repo: repo, runner: job.runner});
      }
    });
    repos.sort();
    rows.sort(function (a, b) {
      if (a.repo !== b.repo) return a.repo < b.repo ? -1 : 1;
      return a.runner < b.runner ? -1 : a.runner > b.runner ? 1 : 0;
    });

    const repoIndex = {};
    repos.forEach(function (repo, index) { repoIndex[repo] = index; });
    const rowIndex = {};
    rows.forEach(function (row, index) { rowIndex[row.key] = index; });

    // Rows are stacked inside a plane; the plane index separates repositories.
    const rowsBeforeIn = {};
    repos.forEach(function (repo) {
      let count = 0;
      rows.forEach(function (row) {
        if (row.repo !== repo) return;
        rowsBeforeIn[row.key] = count;
        count += 1;
      });
    });

    const boxes = visible.map(function (job) {
      const began = Math.max(parseTime(job.started), start);
      const endedRaw = parseTime(job.completed);
      const ended = Math.min(Number.isFinite(endedRaw) ? endedRaw : now, now);
      const x0 = (began - start) / windowMs;
      const x1 = (ended - began) / windowMs;
      const repo = job.repo || 'unknown repository';
      const rowKey = rowKeyFor(repo, job.runner);
      const plane = repoIndex[repo];
      const row = rowIndex[rowKey];
      const rowsBefore = rowsBeforeIn[rowKey] || 0;
      const position = x0 * 100;
      const span = Math.max(x1 * 100, MIN_BAR_LENGTH);
      return {
        job: job,
        repo: repo,
        runner: job.runner,
        name: job.name || 'job',
        workflow: job.workflow || '',
        conclusion: job.conclusion || '',
        status: job.status || '',
        x0: position,
        x1: position + span,
        y: rowsBefore * ROW_HEIGHT,
        z: plane * PLANE_DEPTH,
        color: colorFor(job.conclusion, job.status),
        key: boxKeyFor(repo, job.runner, job.run_id, job.job_id),
      };
    });

    const ticks = [];
    const tickStep = windowMs <= 30 * MINUTE ? 5 * MINUTE : 15 * MINUTE;
    for (let elapsed = 0; elapsed <= windowMs; elapsed += tickStep) {
      const at = start + elapsed;
      ticks.push({
        x: (elapsed / windowMs) * 100,
        label: '-' + Math.round((windowMs - elapsed) / MINUTE) + 'm',
        time: at,
      });
    }

    let maxX = 100;
    let maxY = 0;
    let maxZ = 0;
    boxes.forEach(function (box) {
      maxX = Math.max(maxX, box.x1);
      maxY = Math.max(maxY, box.y);
      maxZ = Math.max(maxZ, box.z);
    });
    if (!rows.length) maxY = 0;
    else maxY = (rows.length - 1) * ROW_HEIGHT;

    return {
      boxes: boxes,
      rows: rows.map(function (row) {
        return {
          key: row.key,
          repo: row.repo,
          runner: row.runner,
          y: rowIndex[row.key],
          z: repoIndex[row.repo] * PLANE_DEPTH,
        };
      }),
      planes: repos.map(function (repo, index) {
        return {repo: repo, z: index * PLANE_DEPTH};
      }),
      ticks: ticks,
      bounds: {
        minX: 0, maxX: maxX,
        minY: 0, maxY: maxY,
        minZ: 0, maxZ: maxZ,
      },
      window: {start: start, end: now, span: windowMs},
    };
  }

  // --- 4x4 matrix maths, column-major to match WebGL ------------------------

  const mat4 = {
    identity: function (out) {
      out[0] = 1; out[1] = 0; out[2] = 0; out[3] = 0;
      out[4] = 0; out[5] = 1; out[6] = 0; out[7] = 0;
      out[8] = 0; out[9] = 0; out[10] = 1; out[11] = 0;
      out[12] = 0; out[13] = 0; out[14] = 0; out[15] = 1;
      return out;
    },
    perspective: function (out, fovY, aspect, near, far) {
      const f = 1 / Math.tan(fovY / 2);
      out.fill(0);
      out[0] = f / aspect;
      out[5] = f;
      out[10] = (far + near) / (near - far);
      out[11] = -1;
      out[14] = 2 * far * near / (near - far);
      return out;
    },
    /** Orthographic projection: the isometric look has no perspective shrink. */
    orthographic: function (out, left, right, bottom, top, near, far) {
      out.fill(0);
      out[0] = 2 / (right - left);
      out[5] = 2 / (top - bottom);
      out[10] = -2 / (far - near);
      out[12] = -(right + left) / (right - left);
      out[13] = -(top + bottom) / (top - bottom);
      out[14] = -(far + near) / (far - near);
      out[15] = 1;
      return out;
    },
    lookAt: function (out, eye, center, up) {
      let zx = eye[0] - center[0];
      let zy = eye[1] - center[1];
      let zz = eye[2] - center[2];
      let length = Math.hypot(zx, zy, zz) || 1;
      zx /= length; zy /= length; zz /= length;
      let xx = up[1] * zz - up[2] * zy;
      let xy = up[2] * zx - up[0] * zz;
      let xz = up[0] * zy - up[1] * zx;
      length = Math.hypot(xx, xy, xz) || 1;
      xx /= length; xy /= length; xz /= length;
      const yx = zy * xz - zz * xy;
      const yy = zz * xx - zx * xz;
      const yz = zx * xy - zy * xx;
      out[0] = xx; out[1] = yx; out[2] = zx; out[3] = 0;
      out[4] = xy; out[5] = yy; out[6] = zy; out[7] = 0;
      out[8] = xz; out[9] = yz; out[10] = zz; out[11] = 0;
      out[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
      out[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
      out[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]);
      out[15] = 1;
      return out;
    },
    multiply: function (out, a, b) {
      const result = new Float32Array(16);
      for (let column = 0; column < 4; column++) {
        for (let row = 0; row < 4; row++) {
          let sum = 0;
          for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[column * 4 + k];
          result[column * 4 + row] = sum;
        }
      }
      out.set(result);
      return out;
    },
    invert: function (out, m) {
      const a00 = m[0], a01 = m[1], a02 = m[2], a03 = m[3];
      const a10 = m[4], a11 = m[5], a12 = m[6], a13 = m[7];
      const a20 = m[8], a21 = m[9], a22 = m[10], a23 = m[11];
      const a30 = m[12], a31 = m[13], a32 = m[14], a33 = m[15];
      const b00 = a00 * a11 - a01 * a10;
      const b01 = a00 * a12 - a02 * a10;
      const b02 = a00 * a13 - a03 * a10;
      const b03 = a01 * a12 - a02 * a11;
      const b04 = a01 * a13 - a03 * a11;
      const b05 = a02 * a13 - a03 * a12;
      const b06 = a20 * a31 - a21 * a30;
      const b07 = a20 * a32 - a22 * a30;
      const b08 = a20 * a33 - a23 * a30;
      const b09 = a21 * a32 - a22 * a31;
      const b10 = a21 * a33 - a23 * a31;
      const b11 = a22 * a33 - a23 * a32;
      let determinant = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
      if (!determinant) return null;
      determinant = 1 / determinant;
      out[0] = (a11 * b11 - a12 * b10 + a13 * b09) * determinant;
      out[1] = (a02 * b10 - a01 * b11 - a03 * b09) * determinant;
      out[2] = (a31 * b05 - a32 * b04 + a33 * b03) * determinant;
      out[3] = (a22 * b04 - a21 * b05 - a23 * b03) * determinant;
      out[4] = (a12 * b08 - a10 * b11 - a13 * b07) * determinant;
      out[5] = (a00 * b11 - a02 * b08 + a03 * b07) * determinant;
      out[6] = (a32 * b02 - a30 * b05 - a33 * b01) * determinant;
      out[7] = (a20 * b05 - a22 * b02 + a23 * b01) * determinant;
      out[8] = (a10 * b10 - a11 * b08 + a13 * b06) * determinant;
      out[9] = (a01 * b08 - a00 * b10 - a03 * b06) * determinant;
      out[10] = (a30 * b04 - a31 * b02 + a33 * b00) * determinant;
      out[11] = (a21 * b02 - a20 * b04 - a23 * b00) * determinant;
      out[12] = (a11 * b07 - a10 * b09 - a12 * b06) * determinant;
      out[13] = (a00 * b09 - a01 * b07 + a02 * b06) * determinant;
      out[14] = (a31 * b01 - a30 * b03 - a32 * b00) * determinant;
      out[15] = (a20 * b03 - a21 * b01 + a22 * b00) * determinant;
      return out;
    },
    /** Project a world point to normalised device coordinates. */
    project: function (m, point) {
      const x = point[0], y = point[1], z = point[2];
      const clipX = m[0] * x + m[4] * y + m[8] * z + m[12];
      const clipY = m[1] * x + m[5] * y + m[9] * z + m[13];
      const clipZ = m[2] * x + m[6] * y + m[10] * z + m[14];
      const clipW = m[3] * x + m[7] * y + m[11] * z + m[15];
      if (clipW <= 0) return {x: 0, y: 0, z: 0, visible: false, w: clipW};
      return {
        x: clipX / clipW,
        y: clipY / clipW,
        z: clipZ / clipW,
        w: clipW,
        visible: true,
      };
    },
  };

  /**
   * Slab test for a ray against an axis-aligned box.
   * Returns the distance along the ray, or null when there is no hit.
   */
  function rayBox(origin, direction, box) {
    let tmin = -Infinity;
    let tmax = Infinity;
    for (let axis = 0; axis < 3; axis++) {
      const o = origin[axis];
      const d = direction[axis];
      const lo = box.min[axis];
      const hi = box.max[axis];
      if (Math.abs(d) < 1e-9) {
        if (o < lo || o > hi) return null;
        continue;
      }
      let t1 = (lo - o) / d;
      let t2 = (hi - o) / d;
      if (t1 > t2) { const swap = t1; t1 = t2; t2 = swap; }
      if (t1 > tmin) tmin = t1;
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }
    if (tmax < 0) return null;
    return tmin >= 0 ? tmin : tmax;
  }

  // --- camera ----------------------------------------------------------------

  // A true isometric view: the camera looks down the (1, 1, 1) direction, so
  // the yaw is 45 degrees and the pitch is asin(1 / sqrt(3)).
  const ISO_YAW = -Math.PI / 4;
  const ISO_PITCH = Math.asin(1 / Math.sqrt(3));

  function createCamera() {
    return {
      yaw: ISO_YAW,
      pitch: ISO_PITCH,
      distance: 150,
      target: [50, 0, 0],
    };
  }

  function orbit(camera, deltaYaw, deltaPitch) {
    camera.yaw += deltaYaw;
    camera.pitch += deltaPitch;
    const limit = Math.PI / 2 - 0.05;
    if (camera.pitch > limit) camera.pitch = limit;
    if (camera.pitch < -limit) camera.pitch = -limit;
    return camera;
  }

  function zoom(camera, delta) {
    camera.distance *= Math.pow(0.995, delta);
    if (camera.distance < MIN_DISTANCE) camera.distance = MIN_DISTANCE;
    if (camera.distance > MAX_DISTANCE) camera.distance = MAX_DISTANCE;
    return camera;
  }

  function pan(camera, deltaX, deltaY) {
    const scale = camera.distance * 0.0016;
    const cos = Math.cos(camera.yaw);
    const sin = Math.sin(camera.yaw);
    camera.target[0] += (deltaX * cos - deltaY * sin) * scale;
    camera.target[1] += deltaY * scale * 0.6;
    camera.target[2] += (deltaX * sin + deltaY * cos) * scale;
    return camera;
  }

  function resetCamera(camera) {
    const fresh = createCamera();
    camera.yaw = fresh.yaw;
    camera.pitch = fresh.pitch;
    camera.distance = fresh.distance;
    camera.target = fresh.target.slice();
    return camera;
  }

  function cameraEye(camera) {
    const cosPitch = Math.cos(camera.pitch);
    return [
      camera.target[0] + camera.distance * cosPitch * Math.sin(camera.yaw),
      camera.target[1] + camera.distance * Math.sin(camera.pitch),
      camera.target[2] + camera.distance * cosPitch * Math.cos(camera.yaw),
    ];
  }

  /** The view direction, which is all an orthographic camera needs. */
  function cameraDirection(camera) {
    const cosPitch = Math.cos(camera.pitch);
    return [
      cosPitch * Math.sin(camera.yaw),
      Math.sin(camera.pitch),
      cosPitch * Math.cos(camera.yaw),
    ];
  }

  /**
   * The ray through a point on the screen.
   *
   * An orthographic camera looks in one direction for every pixel, so the ray
   * direction is constant. Its origin is the point on the eye plane that the
   * pointer lands on, which is the camera target pushed back along the view
   * direction and offset across the camera's own axes.
   */
  function cameraRay(camera, ndcX, ndcY, aspect) {
    const dir = cameraDirection(camera);
    // The camera's right axis, matching the lookAt construction.
    const worldUp = [0, 1, 0];
    let rx = worldUp[1] * dir[2] - worldUp[2] * dir[1];
    let ry = worldUp[2] * dir[0] - worldUp[0] * dir[2];
    let rz = worldUp[0] * dir[1] - worldUp[1] * dir[0];
    const rlen = Math.hypot(rx, ry, rz) || 1;
    rx /= rlen; ry /= rlen; rz /= rlen;
    // The camera's up axis.
    const ux = dir[1] * rz - dir[2] * ry;
    const uy = dir[2] * rx - dir[0] * rz;
    const uz = dir[0] * ry - dir[1] * rx;
    const halfHeight = camera.distance * 0.1;
    const halfWidth = halfHeight * (aspect > 0 ? aspect : 1);
    const origin = [
      camera.target[0] + rx * ndcX * halfWidth + ux * ndcY * halfHeight + dir[0] * camera.distance,
      camera.target[1] + ry * ndcX * halfWidth + uy * ndcY * halfHeight + dir[1] * camera.distance,
      camera.target[2] + rz * ndcX * halfWidth + uz * ndcY * halfHeight + dir[2] * camera.distance,
    ];
    return {origin: origin, direction: [-dir[0], -dir[1], -dir[2]]};
  }

  function viewProjection(camera, aspect) {
    const eye = cameraEye(camera);
    const view = mat4.lookAt(new Float32Array(16), eye, camera.target, [0, 1, 0]);
    const halfHeight = camera.distance * 0.1;
    const halfWidth = halfHeight * (aspect > 0 ? aspect : 1);
    const projection = mat4.orthographic(
      new Float32Array(16), -halfWidth, halfWidth, -halfHeight, halfHeight, -2000, 2000);
    return mat4.multiply(new Float32Array(16), projection, view);
  }

  /**
   * Point the camera at the middle of the data and pull back until the whole
   * volume fits the frame, so a scene with one job and a scene with a hundred
   * both fill the canvas.
   */
  function frameLayout(camera, layout, aspect) {
    const bounds = layout.bounds;
    camera.target = [
      (bounds.minX + bounds.maxX) / 2,
      (bounds.minY + bounds.maxY) / 2,
      (bounds.minZ + bounds.maxZ) / 2,
    ];

    const corners = [];
    [bounds.minX, bounds.maxX].forEach(function (x) {
      [bounds.minY, bounds.maxY].forEach(function (y) {
        [bounds.minZ, bounds.maxZ].forEach(function (z) { corners.push([x, y, z]); });
      });
    });

    const ratio = aspect > 0 ? aspect : 1;
    const spanX = Math.max(1, bounds.maxX - bounds.minX);
    const spanY = Math.max(1, bounds.maxY - bounds.minY);
    const spanZ = Math.max(1, bounds.maxZ - bounds.minZ);
    let distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE,
      Math.sqrt(spanX * spanX + spanY * spanY + spanZ * spanZ) / 2 * 2.1));

    // With an orthographic camera the projected size shrinks exactly with the
    // distance, so a few rounds of scaling land the volume inside the frame.
    for (let round = 0; round < 6; round++) {
      camera.distance = distance;
      const mvp = viewProjection(camera, ratio);
      let extent = 0;
      corners.forEach(function (corner) {
        const projected = mat4.project(mvp, corner);
        if (!projected.visible) return;
        extent = Math.max(extent, Math.abs(projected.x), Math.abs(projected.y));
      });
      if (!extent) break;
      const scale = extent / FRAME_FILL;
      if (Math.abs(scale - 1) < 0.01) break;
      distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, distance * scale));
    }
    camera.distance = distance;
    return camera;
  }

  // --- illustrated geometry ---------------------------------------------------

  /**
   * Three flat tones, one per face direction, so a solid reads as an
   * illustration rather than a smooth render.
   */
  function faceTone(normal) {
    if (normal[1] > 0.5) return 1.0;      // the top face catches the light
    if (normal[1] < -0.5) return 0.60;    // the underside stays dark
    if (normal[2] > 0.5) return 0.90;
    if (normal[2] < -0.5) return 0.72;
    return 0.80;
  }

  function toneColor(color, tone) {
    return [color[0] * tone, color[1] * tone, color[2] * tone];
  }

  function pushTriangles(out, a, b, c, color) {
    [a, b, c].forEach(function (point) {
      out.positions.push(point[0], point[1], point[2]);
      out.colors.push(color[0], color[1], color[2]);
    });
  }

  function pushLine(out, a, b, color) {
    [a, b].forEach(function (point) {
      out.positions.push(point[0], point[1], point[2]);
      out.colors.push(color[0], color[1], color[2]);
    });
  }

  function blockCorners(box) {
    const x0 = box.x0, x1 = box.x0 + BLOCK_SIZE;
    const y0 = box.y + BLOCK_Y, y1 = box.y + BLOCK_Y + BLOCK_SIZE * 0.8;
    const z0 = box.z, z1 = box.z + BLOCK_SIZE;
    return [
      [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ];
  }

  /** A block with three-tone flat shading. */
  function buildBlock(box) {
    const out = {positions: [], colors: []};
    const corners = blockCorners(box);
    const faces = [
      {ids: [4, 5, 6, 7], normal: [0, 1, 0]},
      {ids: [0, 1, 5, 4], normal: [0, 0, -1]},
      {ids: [3, 2, 6, 7], normal: [0, 0, 1]},
      {ids: [0, 3, 7, 4], normal: [-1, 0, 0]},
      {ids: [1, 2, 6, 5], normal: [1, 0, 0]},
      {ids: [0, 1, 2, 3], normal: [0, -1, 0]},
    ];
    faces.forEach(function (face) {
      const color = toneColor(box.color, faceTone(face.normal));
      pushTriangles(out, corners[face.ids[0]], corners[face.ids[1]], corners[face.ids[2]], color);
      pushTriangles(out, corners[face.ids[0]], corners[face.ids[2]], corners[face.ids[3]], color);
    });
    return out;
  }

  /**
   * The dark outline around a block: twelve line segments, pushed a little way
   * out from the solid so they win the depth test instead of fighting it.
   */
  function buildBlockEdges(box) {
    const out = {positions: [], colors: []};
    const corners = blockCorners(box);
    const centre = [0, 0, 0];
    corners.forEach(function (corner) {
      centre[0] += corner[0] / 8;
      centre[1] += corner[1] / 8;
      centre[2] += corner[2] / 8;
    });
    const pushed = corners.map(function (corner) {
      return [
        centre[0] + (corner[0] - centre[0]) * 1.04,
        centre[1] + (corner[1] - centre[1]) * 1.04,
        centre[2] + (corner[2] - centre[2]) * 1.04,
      ];
    });
    const edges = [
      [0, 1], [1, 2], [2, 3], [3, 0],
      [4, 5], [5, 6], [6, 7], [7, 4],
      [0, 4], [1, 5], [2, 6], [3, 7],
    ];
    edges.forEach(function (edge) {
      pushLine(out, pushed[edge[0]], pushed[edge[1]], PALETTE.outline);
    });
    return out;
  }

  /**
   * A cable from the job's start to its end, arcing above the row. It is a
   * hexagonal tube so it reads as a round wire under flat shading.
   */
  function buildCable(box, options) {
    const opts = options || {};
    const segments = opts.segments || 26;
    const sides = opts.sides || 6;
    const radius = opts.radius || 0.8;
    const rise = opts.rise === undefined ? Math.max(2.6, (box.x1 - box.x0) * 0.2) : opts.rise;
    const out = {positions: [], colors: []};
    const start = [box.x0, box.y + BLOCK_Y + BLOCK_SIZE * 0.4, box.z + BLOCK_SIZE / 2];
    const end = [box.x1, box.y + BLOCK_Y + BLOCK_SIZE * 0.4, box.z + BLOCK_SIZE / 2];
    const control = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + rise, start[2]];

    function pointAt(t) {
      const u = 1 - t;
      return [
        u * u * start[0] + 2 * u * t * control[0] + t * t * end[0],
        u * u * start[1] + 2 * u * t * control[1] + t * t * end[1],
        u * u * start[2] + 2 * u * t * control[2] + t * t * end[2],
      ];
    }

    const rings = [];
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const point = pointAt(t);
      const before = pointAt(Math.max(0, t - 0.01));
      const after = pointAt(Math.min(1, t + 0.01));
      let tx = after[0] - before[0];
      let ty = after[1] - before[1];
      let tz = after[2] - before[2];
      const length = Math.hypot(tx, ty, tz) || 1;
      tx /= length; ty /= length; tz /= length;
      // A reference direction that is never parallel to the tangent.
      const reference = Math.abs(ty) > 0.95 ? [1, 0, 0] : [0, 1, 0];
      let nx = reference[1] * tz - reference[2] * ty;
      let ny = reference[2] * tx - reference[0] * tz;
      let nz = reference[0] * ty - reference[1] * tx;
      const nlen = Math.hypot(nx, ny, nz) || 1;
      nx /= nlen; ny /= nlen; nz /= nlen;
      const bx = ty * nz - tz * ny;
      const by = tz * nx - tx * nz;
      const bz = tx * ny - ty * nx;
      const ring = [];
      for (let s = 0; s < sides; s++) {
        const angle = (s / sides) * Math.PI * 2;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        const dx = nx * cos + bx * sin;
        const dy = ny * cos + by * sin;
        const dz = nz * cos + bz * sin;
        ring.push({
          point: [point[0] + dx * radius, point[1] + dy * radius, point[2] + dz * radius],
          normal: [dx, dy, dz],
        });
      }
      rings.push(ring);
    }

    for (let i = 0; i < rings.length - 1; i++) {
      const a = rings[i];
      const b = rings[i + 1];
      for (let s = 0; s < sides; s++) {
        const next = (s + 1) % sides;
        const p0 = a[s], p1 = a[next], p2 = b[next], p3 = b[s];
        // Shade by how far the surface faces upward, in flat steps.
        const up = (p0.normal[1] + p2.normal[1]) / 2;
        const tone = 0.70 + 0.30 * (up * 0.5 + 0.5);
        const color = toneColor(box.color, tone);
        pushTriangles(out, p0.point, p1.point, p2.point, color);
        pushTriangles(out, p0.point, p2.point, p3.point, color);
      }
    }
    return out;
  }

  /** The flat slab a repository sits on. */
  function buildPlatform(plane, bounds) {
    const out = {positions: [], colors: []};
    const top = PLATFORM_TOP;
    const bottom = PLATFORM_TOP - PLATFORM_DEPTH_DOWN;
    const x0 = bounds.minX - 4;
    const x1 = bounds.maxX + 4;
    const z0 = plane.z - 1.5;
    const z1 = plane.z + PLANE_DEPTH * 0.74;
    const topColor = toneColor(PALETTE.platform, 1.0);
    const sideColor = toneColor(PALETTE.platformEdge, 1.0);
    const darkColor = toneColor(PALETTE.platformEdge, 0.72);
    const corners = [
      [x0, top, z0], [x1, top, z0], [x1, top, z1], [x0, top, z1],
      [x0, bottom, z0], [x1, bottom, z0], [x1, bottom, z1], [x0, bottom, z1],
    ];
    pushTriangles(out, corners[0], corners[1], corners[2], topColor);
    pushTriangles(out, corners[0], corners[2], corners[3], topColor);
    pushTriangles(out, corners[0], corners[5], corners[4], sideColor);
    pushTriangles(out, corners[0], corners[1], corners[5], sideColor);
    pushTriangles(out, corners[1], corners[2], corners[6], sideColor);
    pushTriangles(out, corners[1], corners[6], corners[5], sideColor);
    pushTriangles(out, corners[3], corners[7], corners[4], darkColor);
    return out;
  }

  /** A soft flat shadow cast by a block. */
  function buildShadow(box) {
    const out = {positions: [], colors: []};
    const y = box.y + SHADOW_Y;
    const x0 = box.x0 + 0.4;
    const x1 = box.x0 + BLOCK_SIZE + 1.7;
    const z0 = box.z + 0.5;
    const z1 = box.z + BLOCK_SIZE + 1.0;
    pushTriangles(out, [x0, y, z0], [x1, y, z0], [x1, y, z1], PALETTE.shadow);
    pushTriangles(out, [x0, y, z0], [x1, y, z1], [x0, y, z1], PALETTE.shadow);
    return out;
  }

  /** The isometric ground grid: one line per runner row and per time tick. */
  function buildGrid(layout) {
    const out = {positions: [], colors: []};
    const maxZ = layout.bounds.maxZ + PLANE_DEPTH;
    layout.planes.forEach(function (plane) {
      pushLine(out,
        [layout.bounds.minX, PLATFORM_TOP + GRID_Y, plane.z],
        [layout.bounds.maxX, PLATFORM_TOP + GRID_Y, plane.z], PALETTE.grid);
    });
    layout.ticks.forEach(function (tick) {
      pushLine(out,
        [tick.x, PLATFORM_TOP + GRID_Y, layout.bounds.minZ],
        [tick.x, PLATFORM_TOP + GRID_Y, maxZ], PALETTE.grid);
    });
    layout.rows.forEach(function (row) {
      pushLine(out,
        [layout.bounds.minX, PLATFORM_TOP + GRID_Y + 0.02, row.z + PLANE_DEPTH * 0.37],
        [layout.bounds.maxX, PLATFORM_TOP + GRID_Y + 0.02, row.z + PLANE_DEPTH * 0.37], PALETTE.grid);
    });
    return out;
  }

  /**
   * Faint circuit-trace artwork behind the data: right-angle paths with a pad
   * at each end, laid out on a fixed lattice so it never changes between
   * refreshes.
   */
  function buildTraces(layout) {
    const out = {positions: [], colors: []};
    // Just below the platform surface, so a platform always draws over the
    // artwork that passes beneath it.
    const y = PLATFORM_TOP - 0.05;
    const x0 = layout.bounds.minX - 26;
    const x1 = layout.bounds.maxX + 26;
    const z0 = layout.bounds.minZ - 30;
    const z1 = layout.bounds.maxZ + PLANE_DEPTH * 1.5;
    const stepX = 9;
    const stepZ = 7;
    let seed = 7;
    function random() {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    }
    for (let gx = x0; gx < x1; gx += stepX) {
      for (let gz = z0; gz < z1; gz += stepZ) {
        if (random() > 0.34) continue;
        const turns = 2 + Math.floor(random() * 2);
        let cx = gx + random() * 4;
        let cz = gz + random() * 3;
        const points = [[cx, y, cz]];
        let alongX = random() > 0.5;
        for (let t = 0; t < turns; t++) {
          const run = 3 + random() * 6;
          if (alongX) cx += run; else cz += run;
          points.push([cx, y, cz]);
          alongX = !alongX;
        }
        for (let i = 0; i < points.length - 1; i++) {
          pushLine(out, points[i], points[i + 1], PALETTE.trace);
        }
        // Pads: a short cross at each end of the trace.
        const first = points[0];
        const last = points[points.length - 1];
        pushLine(out, [first[0] - 0.9, first[1], first[2]], [first[0] + 0.9, first[1], first[2]], PALETTE.trace);
        pushLine(out, [first[0], first[1], first[2] - 0.9], [first[0], first[1], first[2] + 0.9], PALETTE.trace);
        pushLine(out, [last[0] - 0.9, last[1], last[2]], [last[0] + 0.9, last[1], last[2]], PALETTE.trace);
        pushLine(out, [last[0], last[1], last[2] - 0.9], [last[0], last[1], last[2] + 0.9], PALETTE.trace);
      }
    }
    return out;
  }

  // --- WebGL rendering -------------------------------------------------------

  const VERTEX_SHADER = [
    '#version 300 es',
    'in vec3 aPosition;',
    'in vec3 aColor;',
    'uniform mat4 uMVP;',
    'out vec3 vColor;',
    'void main() {',
    '  vColor = aColor;',
    '  gl_Position = uMVP * vec4(aPosition, 1.0);',
    '}',
  ].join('\n');

  const FRAGMENT_SHADER = [
    '#version 300 es',
    'precision mediump float;',
    'in vec3 vColor;',
    'out vec4 fragColor;',
    'void main() { fragColor = vec4(vColor, 1.0); }',
  ].join('\n');

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error('shader compile failed: ' + log);
    }
    return shader;
  }

  function link(gl, vertexSource, fragmentSource) {
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertexSource));
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragmentSource));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error('program link failed: ' + gl.getProgramInfoLog(program));
    }
    return program;
  }

  function merge(target, source) {
    target.positions = target.positions.concat(source.positions);
    target.colors = target.colors.concat(source.colors);
    return target;
  }

  /**
   * Build the viewer. Returns null when the browser has no WebGL2 support, so
   * the dashboard can fall back to the flat views instead of failing.
   */
  function createViewer(canvas, options) {
    const opts = options || {};
    if (!canvas || typeof canvas.getContext !== 'function') return null;
    const gl = canvas.getContext('webgl2', {antialias: true, alpha: false});
    if (!gl) return null;

    let program;
    let triBuffer;
    let triColorBuffer;
    let lineBuffer;
    let lineColorBuffer;
    let positionLocation;
    let colorLocation;
    let mvpLocation;
    try {
      program = link(gl, VERTEX_SHADER, FRAGMENT_SHADER);
      triBuffer = gl.createBuffer();
      triColorBuffer = gl.createBuffer();
      lineBuffer = gl.createBuffer();
      lineColorBuffer = gl.createBuffer();
      positionLocation = gl.getAttribLocation(program, 'aPosition');
      colorLocation = gl.getAttribLocation(program, 'aColor');
      mvpLocation = gl.getUniformLocation(program, 'uMVP');
    } catch (error) {
      // A partial or broken WebGL implementation must not break the dashboard.
      return null;
    }

    const camera = createCamera();
    let layout = buildLayout([], {now: Date.now()});
    let triangles = {positions: [], colors: []};
    let lines = {positions: [], colors: []};
    let backgroundLineCount = 0;
    let hovered = null;
    let selected = null;
    let disposed = false;
    const listeners = {hover: [], select: []};

    function notify(name, payload) {
      listeners[name].forEach(function (handler) {
        try { handler(payload); } catch (error) { /* a listener must not break the render */ }
      });
    }

    function upload(target, buffer, colors, values) {
      target.count = values.positions.length / 3;
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values.positions), gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, colors);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values.colors), gl.DYNAMIC_DRAW);
    }

    function buildScene() {
      const solid = {positions: [], colors: []};
      const outlines = {positions: [], colors: []};
      const traceLines = buildTraces(layout);
      const gridLines = buildGrid(layout);

      layout.planes.forEach(function (plane) {
        merge(solid, buildPlatform(plane, layout.bounds));
      });
      layout.boxes.forEach(function (box) {
        merge(solid, buildShadow(box));
        merge(solid, buildCable(box));
        merge(solid, buildBlock(box));
        merge(outlines, buildBlockEdges(box));
      });

      // One line buffer holds the background artwork first and the block
      // outlines last, so both can be drawn from it with an offset.
      const allLines = {
        positions: traceLines.positions.concat(gridLines.positions, outlines.positions),
        colors: traceLines.colors.concat(gridLines.colors, outlines.colors),
      };
      upload(solid, triBuffer, triColorBuffer, solid);
      upload(allLines, lineBuffer, lineColorBuffer, allLines);
      triangles = solid;
      lines = allLines;
      backgroundLineCount = (traceLines.positions.length + gridLines.positions.length) / 3;
    }

    function currentAspect() {
      const width = canvas.clientWidth || canvas.width || 1;
      const height = canvas.clientHeight || canvas.height || 1;
      return height > 0 ? width / height : 1;
    }

    function resize() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.floor((canvas.clientWidth || canvas.width || 1) * ratio));
      const height = Math.max(1, Math.floor((canvas.clientHeight || canvas.height || 1) * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function bindAttributes(buffer, colors) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.enableVertexAttribArray(positionLocation);
      gl.vertexAttribPointer(positionLocation, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, colors);
      gl.enableVertexAttribArray(colorLocation);
      gl.vertexAttribPointer(colorLocation, 3, gl.FLOAT, false, 0, 0);
    }

    function draw() {
      if (disposed) return;
      resize();
      gl.clearColor(PALETTE.ground[0], PALETTE.ground[1], PALETTE.ground[2], 1);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.disable(gl.BLEND);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

      const mvp = viewProjection(camera, currentAspect());
      gl.useProgram(program);
      gl.uniformMatrix4fv(mvpLocation, false, mvp);

      // The faint circuit artwork and the ground grid sit behind everything and
      // write no depth, so the platforms draw cleanly over them.
      gl.depthMask(false);
      bindAttributes(lineBuffer, lineColorBuffer);
      gl.drawArrays(gl.LINES, 0, backgroundLineCount);
      gl.depthMask(true);

      // The solids: shadows, platforms, cables and blocks.
      bindAttributes(triBuffer, triColorBuffer);
      gl.drawArrays(gl.TRIANGLES, 0, triangles.count);

      // The outlines last, so they sit on top of the blocks they belong to.
      bindAttributes(lineBuffer, lineColorBuffer);
      gl.drawArrays(gl.LINES, backgroundLineCount, lines.count - backgroundLineCount);
    }

    function boxBounds(box) {
      return {
        min: [box.x0, box.y + BLOCK_Y, box.z],
        max: [box.x0 + BLOCK_SIZE, box.y + BLOCK_Y + BLOCK_SIZE * 0.8, box.z + BLOCK_SIZE],
      };
    }

    /**
     * Project a world point to CSS pixels inside the canvas, so the dashboard
     * can pin axis labels to the scene without a second render pass.
     */
    function projectToScreen(point) {
      const rect = canvas.getBoundingClientRect();
      const width = rect.width || canvas.clientWidth || 1;
      const height = rect.height || canvas.clientHeight || 1;
      const aspect = height > 0 ? width / height : 1;
      const mvp = viewProjection(camera, aspect);
      const projected = mat4.project(mvp, point);
      if (!projected.visible) return null;
      return {
        x: (projected.x * 0.5 + 0.5) * width,
        y: (0.5 - projected.y * 0.5) * height,
        z: projected.z,
        visible: projected.x >= -1 && projected.x <= 1 && projected.y >= -1 && projected.y <= 1,
      };
    }

    function pickAt(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      const ndcX = ((clientX - rect.left) / rect.width) * 2 - 1;
      const ndcY = 1 - ((clientY - rect.top) / rect.height) * 2;
      const aspect = rect.height > 0 ? rect.width / rect.height : 1;
      const ray = cameraRay(camera, ndcX, ndcY, aspect);
      const origin = ray.origin;
      const direction = ray.direction;
      let best = null;
      let bestDistance = Infinity;
      layout.boxes.forEach(function (box) {
        const hit = rayBox(origin, direction, boxBounds(box));
        if (hit !== null && hit < bestDistance) {
          bestDistance = hit;
          best = box;
        }
      });
      return best;
    }

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let moved = 0;

    function onPointerDown(event) {
      dragging = true;
      moved = 0;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture && canvas.setPointerCapture(event.pointerId);
    }

    function onPointerMove(event) {
      if (dragging) {
        const deltaX = event.clientX - lastX;
        const deltaY = event.clientY - lastY;
        lastX = event.clientX;
        lastY = event.clientY;
        moved += Math.abs(deltaX) + Math.abs(deltaY);
        if (event.shiftKey) pan(camera, deltaX, deltaY);
        else orbit(camera, deltaX * 0.006, -deltaY * 0.006);
        draw();
        return;
      }
      const hit = pickAt(event.clientX, event.clientY);
      const key = hit ? hit.key : null;
      if (key !== (hovered ? hovered.key : null)) {
        hovered = hit;
        canvas.style.cursor = hit ? 'pointer' : 'grab';
        notify('hover', hit);
        draw();
      }
    }

    function onPointerUp(event) {
      if (!dragging) return;
      dragging = false;
      canvas.releasePointerCapture && canvas.releasePointerCapture(event.pointerId);
      if (moved < 4) {
        const hit = pickAt(event.clientX, event.clientY);
        selected = hit;
        notify('select', hit);
      }
    }

    function onWheel(event) {
      event.preventDefault();
      zoom(camera, event.deltaY);
      draw();
    }

    function onKeyDown(event) {
      const step = 0.12;
      if (event.key === 'ArrowLeft') orbit(camera, step, 0);
      else if (event.key === 'ArrowRight') orbit(camera, -step, 0);
      else if (event.key === 'ArrowUp') orbit(camera, 0, step);
      else if (event.key === 'ArrowDown') orbit(camera, 0, -step);
      else if (event.key === '+' || event.key === '=') zoom(camera, -120);
      else if (event.key === '-') zoom(camera, 120);
      else if (event.key === 'Home' || event.key === '0') resetCamera(camera);
      else return;
      event.preventDefault();
      draw();
    }

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('wheel', onWheel, {passive: false});
    canvas.addEventListener('keydown', onKeyDown);
    canvas.addEventListener('mouseleave', function () {
      if (hovered) { hovered = null; notify('hover', null); draw(); }
    });

    buildScene();
    draw();

    return {
      camera: camera,
      getLayout: function () { return layout; },
      setJobs: function (jobs, setOptions) {
        layout = buildLayout(jobs, setOptions);
        hovered = null;
        selected = null;
        frameLayout(camera, layout, currentAspect());
        buildScene();
        draw();
        notify('hover', null);
        notify('select', null);
      },
      setWindow: function (windowMs) {
        layout = buildLayout(layout.boxes.map(function (box) { return box.job; }), {
          now: Date.now(), windowMs: windowMs,
        });
        buildScene();
        draw();
      },
      reset: function () { resetCamera(camera); frameLayout(camera, layout, currentAspect()); draw(); },
      rotate: function (delta) { orbit(camera, delta, 0); draw(); },
      zoomBy: function (delta) { zoom(camera, delta); draw(); },
      draw: draw,
      pickAt: pickAt,
      projectToScreen: projectToScreen,
      on: function (name, handler) {
        if (listeners[name]) listeners[name].push(handler);
        return this;
      },
      dispose: function () {
        disposed = true;
        canvas.removeEventListener('pointerdown', onPointerDown);
        canvas.removeEventListener('pointermove', onPointerMove);
        canvas.removeEventListener('pointerup', onPointerUp);
        canvas.removeEventListener('pointercancel', onPointerUp);
        canvas.removeEventListener('wheel', onWheel);
        canvas.removeEventListener('keydown', onKeyDown);
        gl.deleteBuffer(triBuffer);
        gl.deleteBuffer(triColorBuffer);
        gl.deleteBuffer(lineBuffer);
        gl.deleteBuffer(lineColorBuffer);
        gl.deleteProgram(program);
      },
    };
  }

  return {
    buildLayout: buildLayout,
    mat4: mat4,
    rayBox: rayBox,
    createCamera: createCamera,
    orbit: orbit,
    zoom: zoom,
    pan: pan,
    resetCamera: resetCamera,
    frameLayout: frameLayout,
    cameraEye: cameraEye,
    cameraDirection: cameraDirection,
    cameraRay: cameraRay,
    viewProjection: viewProjection,
    createViewer: createViewer,
    buildBlock: buildBlock,
    buildBlockEdges: buildBlockEdges,
    buildCable: buildCable,
    buildPlatform: buildPlatform,
    buildGrid: buildGrid,
    buildTraces: buildTraces,
    faceTone: faceTone,
    MIN_DISTANCE: MIN_DISTANCE,
    MAX_DISTANCE: MAX_DISTANCE,
    ISO_YAW: ISO_YAW,
    ISO_PITCH: ISO_PITCH,
    PALETTE: PALETTE,
    COLORS: COLORS,
  };
});

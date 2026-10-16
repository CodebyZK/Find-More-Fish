// Morph forecast depth fields before colouring them. One canvas per lake stays
// at full opacity; moving contours never crossfade two translucent map layers.
import { L } from "./vendor.js";
import { paletteRgb, PALETTE_STOPS } from "./great-lakes-palette.js";

const MAX_DIMENSION = 320;
const FLOW_STEP = 8;
const MIXED = [104, 116, 132];

const CanvasOverlay = L.ImageOverlay.extend({
  _initImage() {
    this._image = this._url;
    L.DomUtil.addClass(this._image, "leaflet-image-layer");
    if (this._zoomAnimated) L.DomUtil.addClass(this._image, "leaflet-zoom-animated");
    L.DomUtil.addClass(this._image, this.options.className);
  }
});

function sample(data, width, height, x, y, channel = 0) {
  x = Math.max(0, Math.min(width - 1, x));
  y = Math.max(0, Math.min(height - 1, y));
  const left = Math.floor(x), top = Math.floor(y);
  const right = Math.min(left + 1, width - 1), bottom = Math.min(top + 1, height - 1);
  const dx = x - left, dy = y - top;
  const at = (px, py) => data[(py * width + px) * 4 + channel];
  return (at(left, top) * (1 - dx) + at(right, top) * dx) * (1 - dy)
    + (at(left, bottom) * (1 - dx) + at(right, bottom) * dx) * dy;
}

// Local optical flow estimates how depth contours moved between forecasts.
// This is visual interpolation, not a measured water-current vector field.
export function depthFlow(from, to, width, height) {
  const columns = Math.ceil(width / FLOW_STEP), rows = Math.ceil(height / FLOW_STEP);
  const vectors = new Float32Array(columns * rows * 2);
  const at = (data, x, y) => data[(y * width + x) * 4];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      let xx = 0, xy = 0, yy = 0, xt = 0, yt = 0;
      const cx = column * FLOW_STEP, cy = row * FLOW_STEP;
      for (let y = Math.max(1, cy - 4); y <= Math.min(height - 2, cy + 4); y += 1) {
        for (let x = Math.max(1, cx - 4); x <= Math.min(width - 2, cx + 4); x += 1) {
          // Missing depth / mixed water must not pull valid contours ashore.
          if (![from, to].every((data) => [[x, y], [x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]].every(([px, py]) => data[(py * width + px) * 4 + 3] > 240))) continue;
          const gx = (at(from, x + 1, y) - at(from, x - 1, y) + at(to, x + 1, y) - at(to, x - 1, y)) / 4;
          const gy = (at(from, x, y + 1) - at(from, x, y - 1) + at(to, x, y + 1) - at(to, x, y - 1)) / 4;
          const dt = at(to, x, y) - at(from, x, y);
          xx += gx * gx; xy += gx * gy; yy += gy * gy;
          xt += gx * dt; yt += gy * dt;
        }
      }
      // Regularization also gives a stable normal velocity for a straight front.
      xx += 4; yy += 4;
      const determinant = xx * yy - xy * xy;
      const offset = (row * columns + column) * 2;
      vectors[offset] = Math.max(-6, Math.min(6, (xy * yt - yy * xt) / determinant));
      vectors[offset + 1] = Math.max(-6, Math.min(6, (xy * xt - xx * yt) / determinant));
    }
  }
  return { vectors, columns, rows };
}

function velocity(flow, x, y, channel) {
  const gx = Math.min(flow.columns - 1, x / FLOW_STEP), gy = Math.min(flow.rows - 1, y / FLOW_STEP);
  const left = Math.floor(gx), top = Math.floor(gy);
  const right = Math.min(left + 1, flow.columns - 1), bottom = Math.min(top + 1, flow.rows - 1);
  const dx = gx - left, dy = gy - top;
  const at = (px, py) => flow.vectors[(py * flow.columns + px) * 2 + channel];
  return (at(left, top) * (1 - dx) + at(right, top) * dx) * (1 - dy)
    + (at(left, bottom) * (1 - dx) + at(right, bottom) * dx) * dy;
}

export function morphDepth(from, to, output, width, height, progress, flow, colors) {
  progress = Math.max(0, Math.min(1, progress));
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const vx = flow ? velocity(flow, x, y, 0) : 0, vy = flow ? velocity(flow, x, y, 1) : 0;
      const ax = x - vx * progress, ay = y - vy * progress;
      const bx = x + vx * (1 - progress), by = y + vy * (1 - progress);
      const a = sample(from.values, width, height, ax, ay, 3) / 255;
      const b = sample(to.values, width, height, bx, by, 3) / 255;
      const weight = a * (1 - progress) + b * progress;
      const level = weight ? (sample(from.values, width, height, ax, ay) * a * (1 - progress)
        + sample(to.values, width, height, bx, by) * b * progress) / weight : 0;
      const color = colors[Math.max(0, Math.min(255, Math.round(level)))];
      // Keep the geographic water mask fixed while the depth field moves.
      const water = from.water[offset + 3] * (1 - progress) + to.water[offset + 3] * progress;
      const coverage = from.mixed || to.mixed ? (water ? Math.min(1, weight * 255 / water) : 0) : 1;
      for (let channel = 0; channel < 3; channel += 1) {
        output[offset + channel] = color[channel] * coverage + MIXED[channel] * (1 - coverage);
      }
      output[offset + 3] = water;
    }
  }
}

async function readImage(url, width, height) {
  const image = new Image();
  image.src = url;
  await image.decode();
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, MAX_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight));
  canvas.width = width || Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = height || Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return context.getImageData(0, 0, canvas.width, canvas.height);
}

export async function createThermoclineFlow(payloads, options) {
  // Legacy colour-only responses retain instant forecast switching.
  if (!payloads.some((payload) => payload.rasters?.length)) return null;
  if (payloads.some((payload) => (payload.rasters || []).some((raster) => !raster.valueUrl || !raster.valueRange))) return null;
  const keys = [...new Set(payloads.flatMap((payload) => (payload.rasters || []).map((raster) => JSON.stringify(raster.bounds))))];
  const lakes = await Promise.all(keys.map(async (key) => {
    const rasters = payloads.map((payload) => payload.rasters?.find((raster) => JSON.stringify(raster.bounds) === key));
    const first = rasters.find(Boolean);
    const reference = await readImage(first.valueUrl);
    const { width, height } = reference;
    const frames = await Promise.all(rasters.map(async (raster) => {
      if (!raster) return { values: new Uint8ClampedArray(width * height * 4), water: new Uint8ClampedArray(width * height * 4) };
      const values = await readImage(raster.valueUrl, width, height);
      // Value and mixed images partition the water mask. Combine their alpha
      // without needing a second coloured frame image.
      const water = new Uint8ClampedArray(values.data);
      if (raster.mixedUrl) {
        const mixed = await readImage(raster.mixedUrl, width, height);
        for (let offset = 3; offset < water.length; offset += 4) {
          water[offset] = Math.min(255, water[offset] + mixed.data[offset]);
        }
      }
      return { values: values.data, water, mixed: Boolean(raster.mixedUrl) };
    }));
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext("2d");
    const output = context.createImageData(width, height);
    const overlay = new CanvasOverlay(canvas, first.bounds, { ...options, opacity: 1 });
    return { frames, width, height, context, output, overlay, range: first.valueRange, flows: new Map() };
  }));
  // Estimate motion before playback. Leaving this lazy makes the first frame of
  // every new pair pay for optical-flow analysis and can look like a keyframe hold.
  for (const lake of lakes) {
    if (lake.frames.length < 2) continue;
    for (let from = 0; from < lake.frames.length; from += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      const to = (from + 1) % lake.frames.length;
      lake.flows.set(`${from}:${to}`, depthFlow(lake.frames[from].values, lake.frames[to].values, lake.width, lake.height));
    }
  }
  let frame = null, colors = [];
  function setRange(low, high) {
    colors = lakes.map(({ range }) => Array.from({ length: 256 }, (_, level) => paletteRgb(
      (range[0] + level / 255 * (range[1] - range[0]) - low) / Math.max(high - low, 1e-9), PALETTE_STOPS.thermocline)));
  }
  setRange(...lakes[0].range);
  function draw(from, to = from, progress = 0) {
    lakes.forEach((lake, index) => {
      const key = `${from}:${to}`;
      morphDepth(lake.frames[from], lake.frames[to], lake.output.data, lake.width, lake.height, progress, lake.flows.get(key), colors[index]);
      lake.context.putImageData(lake.output, 0, 0);
    });
  }
  return {
    addTo(group) { lakes.forEach(({ overlay }) => overlay.addTo(group)); },
    setRange,
    show(index) { cancelAnimationFrame(frame); frame = null; draw(index); },
    transition(from, to, duration) {
      cancelAnimationFrame(frame);
      const started = performance.now();
      let lastDraw = -Infinity;
      const update = (now) => {
        if (document.hidden) { frame = null; return; }
        const progress = Math.max(0, Math.min(1, (now - started) / duration));
        // Cap CPU work while keeping motion smooth; always paint exact endpoints.
        if (now - lastDraw >= 1000 / 30 || progress === 1) {
          draw(from, to, progress);
          lastDraw = now;
        }
        frame = progress < 1 ? requestAnimationFrame(update) : null;
      };
      frame = requestAnimationFrame(update);
    },
    remove() { cancelAnimationFrame(frame); lakes.forEach(({ overlay }) => overlay.remove()); }
  };
}

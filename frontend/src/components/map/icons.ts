import type { Map as MlMap } from "maplibre-gl";

/** Marker glyphs drawn on a canvas and registered as SDF images (tinted by the layers). */
type Draw = (ctx: CanvasRenderingContext2D, s: number) => void;

const GLYPHS: Record<string, Draw> = {
  // water station: drop
  drop: (c, s) => {
    c.beginPath();
    c.moveTo(s / 2, s * 0.1);
    c.bezierCurveTo(s * 0.5, s * 0.1, s * 0.18, s * 0.5, s * 0.18, s * 0.64);
    c.arc(s / 2, s * 0.64, s * 0.32, Math.PI, 0, true);
    c.bezierCurveTo(s * 0.82, s * 0.5, s * 0.5, s * 0.1, s / 2, s * 0.1);
    c.fill();
  },
  // warning: triangle with "!"
  triangle: (c, s) => {
    c.beginPath();
    c.moveTo(s / 2, s * 0.08);
    c.lineTo(s * 0.94, s * 0.9);
    c.lineTo(s * 0.06, s * 0.9);
    c.closePath();
    c.fill();
  },
  // weather station: cloud
  cloud: (c, s) => {
    c.beginPath();
    c.arc(s * 0.36, s * 0.58, s * 0.2, 0, Math.PI * 2);
    c.arc(s * 0.56, s * 0.44, s * 0.24, 0, Math.PI * 2);
    c.arc(s * 0.72, s * 0.6, s * 0.18, 0, Math.PI * 2);
    c.rect(s * 0.36, s * 0.58, s * 0.36, s * 0.2);
    c.fill();
  },
  // dam: wall + water
  dam: (c, s) => {
    c.beginPath();
    c.moveTo(s * 0.42, s * 0.12);
    c.lineTo(s * 0.62, s * 0.12);
    c.lineTo(s * 0.82, s * 0.88);
    c.lineTo(s * 0.42, s * 0.88);
    c.closePath();
    c.fill();
    c.fillRect(s * 0.1, s * 0.4, s * 0.28, s * 0.48);
  },
};

export function registerIcons(map: MlMap) {
  const size = 48;
  for (const [name, draw] of Object.entries(GLYPHS)) {
    if (map.hasImage(name)) continue;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) continue;
    ctx.fillStyle = "#000";
    draw(ctx, size);
    const img = ctx.getImageData(0, 0, size, size);
    map.addImage(name, { width: size, height: size, data: new Uint8Array(img.data.buffer) }, { sdf: true, pixelRatio: 2 });
  }
}

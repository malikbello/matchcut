// Quality tiers, as games ship them: High is the default, and the Studio steps down
// on its own when the frame rate stays low, then falls back to the 2D data pitch if
// WebGL is missing. Each tier only changes cost, never what the viewer is told.
export const TIERS = {
  high: { pixelRatio: 2, shadows: 2048, crowd: 19000, bloom: true, gtao: true, antialias: true },
  medium: { pixelRatio: 1.5, shadows: 1024, crowd: 9000, bloom: true, gtao: false, antialias: true },
  low: { pixelRatio: 1, shadows: 0, crowd: 3500, bloom: false, gtao: false, antialias: false },
};
export const ORDER = ["high", "medium", "low"];

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2"));
  } catch {
    return false;
  }
}

// Watches frame times; after a sustained stretch below the floor it asks for the next tier down.
export class FrameGovernor {
  constructor({ floorFps = 30, window = 3000 } = {}) {
    this.floor = 1000 / floorFps;
    this.window = window;
    this.slowSince = null;
  }
  sample(now, frameMs) {
    if (frameMs <= this.floor) {
      this.slowSince = null;
      return false;
    }
    this.slowSince ??= now;
    if (now - this.slowSince > this.window) {
      this.slowSince = null;
      return true;
    }
    return false;
  }
}

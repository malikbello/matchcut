// The crowd: a layered stadium mix on the Web Audio API, driven by the match.
//
//   bed     two steady crowd loops played together (no audible loop point)
//   chant   a stadium song that swells as an attack becomes dangerous
//   roar    a real goal reaction, one of several, on every goal
// Excitement (0 calm to 1 eruption) raises the bed and chant and opens a low-pass
// filter from muffled to bright: a crowd leaning forward sounds brighter, not only louder.
// The whole crowd ducks under the commentary so the voice always reads.
const STEMS = ["bed_a", "bed_b", "chant", "roar_1", "roar_2", "roar_3", "roar_4", "roar_5"];

export class Crowd {
  constructor(base = "assets/audio/crowd") {
    this.base = base;
    this.ctx = null;
    this.buffers = new Map();
    this.excitement = 0;
    this.enabled = true;
    this.ducked = false;
    this.lastRoar = -1;
  }

  // call from a user gesture (browsers only allow audio after one)
  async start() {
    if (this.ctx) {
      await this.ctx.resume();
      return;
    }
    const ctx = new AudioContext();
    this.ctx = ctx;
    this.master = ctx.createGain();
    this.master.gain.value = this.enabled ? 0.9 : 0;
    this.master.connect(ctx.destination);
    this.tone = ctx.createBiquadFilter();
    this.tone.type = "lowpass";
    this.tone.frequency.value = 2200;
    this.tone.Q.value = 0.5;
    this.tone.connect(this.master);
    await Promise.all(
      STEMS.map(async (name) => {
        const res = await fetch(`${this.base}/${name}.mp3`);
        if (!res.ok) return;
        this.buffers.set(name, await ctx.decodeAudioData(await res.arrayBuffer()));
      }),
    );
    this.bedGain = ctx.createGain();
    this.bedGain.gain.value = 0.5;
    this.bedGain.connect(this.tone);
    for (const [name, offset] of [["bed_a", 0], ["bed_b", 7.3]]) {
      const buf = this.buffers.get(name);
      if (!buf) continue;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.loop = true;
      src.connect(this.bedGain);
      src.start(0, offset % buf.duration);
    }
    this.chantGain = ctx.createGain();
    this.chantGain.gain.value = 0;
    this.chantGain.connect(this.tone);
    const chant = this.buffers.get("chant");
    if (chant) {
      const src = ctx.createBufferSource();
      src.buffer = chant;
      src.loop = true;
      src.connect(this.chantGain);
      src.start();
    }
    await ctx.resume();
  }

  // e: 0..1, called every frame
  update(e) {
    if (!this.chantGain) return; // still loading
    this.excitement += (e - this.excitement) * 0.08;
    const x = this.excitement;
    const t = this.ctx.currentTime;
    const smooth = (x0, x1, v) => Math.min(1, Math.max(0, (v - x0) / (x1 - x0))) ** 2 * (3 - 2 * Math.min(1, Math.max(0, (v - x0) / (x1 - x0))));
    this.bedGain.gain.setTargetAtTime(0.45 + 0.35 * x, t, 0.35);
    this.chantGain.gain.setTargetAtTime(0.85 * smooth(0.3, 0.85, x), t, 0.5);
    this.tone.frequency.setTargetAtTime(1600 + 11000 * x ** 1.6, t, 0.3);
    this.master.gain.setTargetAtTime(this.enabled ? (this.ducked ? 0.45 : 0.9) : 0, t, 0.15);
  }

  goal() {
    if (!this.ctx) return;
    const roars = STEMS.filter((s) => s.startsWith("roar") && this.buffers.has(s));
    if (!roars.length) return;
    let pick = Math.floor(Math.random() * roars.length);
    if (pick === this.lastRoar) pick = (pick + 1) % roars.length;
    this.lastRoar = pick;
    const src = this.ctx.createBufferSource();
    src.buffer = this.buffers.get(roars[pick]);
    const g = this.ctx.createGain();
    g.gain.value = 1.0;
    src.connect(g);
    g.connect(this.master); // the roar bypasses the filter: full brightness
    src.start();
    this.excitement = 1;
  }

  duck(on) {
    this.ducked = on;
  }

  setEnabled(on) {
    this.enabled = on;
  }
}

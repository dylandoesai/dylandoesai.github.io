// Web Audio FFT -> band energies for the face shader.
//
// We split the spectrum into bass/mid/high, smooth each, and expose an
// overall amplitude. The TTS audio element is the input source; we keep
// it routed to the speakers via a passthrough node.

export class AudioAnalyzer {
  constructor(audioEl) {
    this.audioEl = audioEl;
    this.ctx = null;
    this.analyser = null;
    this.dataArr = null;
    this.bands = { bass: 0, mid: 0, high: 0, amp: 0 };
    this._smoothed = { bass: 0, mid: 0, high: 0, amp: 0 };
    this._initLazy = () => this._init();
    audioEl.addEventListener('play', this._initLazy, { once: true });
  }

  _init() {
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = this.ctx.createMediaElementSource(this.audioEl);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.5;
    src.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
    this.dataArr = new Uint8Array(this.analyser.frequencyBinCount);
  }

  sample() {
    if (!this.analyser) return this.bands;
    this.analyser.getByteFrequencyData(this.dataArr);
    const arr = this.dataArr;
    const sr = (this.ctx && this.ctx.sampleRate) || 48000;
    const binHz = sr / 2 / arr.length;
    let bass = 0, mid = 0, high = 0, total = 0, totalN = 0;
    let bassN = 0, midN = 0, highN = 0;
    for (let i = 1; i < arr.length; i++) {
      const f = i * binHz;
      const v = arr[i] / 255;
      total += v; totalN++;
      if (f < 250) { bass += v; bassN++; }
      else if (f < 2000) { mid += v; midN++; }
      else if (f < 8000) { high += v; highN++; }
    }
    bass = bassN ? bass / bassN : 0;
    mid = midN ? mid / midN : 0;
    high = highN ? high / highN : 0;
    const amp = totalN ? total / totalN : 0;

    const a = 0.25;
    this._smoothed.bass = this._smoothed.bass * (1 - a) + bass * a;
    this._smoothed.mid = this._smoothed.mid * (1 - a) + mid * a;
    this._smoothed.high = this._smoothed.high * (1 - a) + high * a;
    this._smoothed.amp = this._smoothed.amp * (1 - a) + amp * a;
    this.bands = { ...this._smoothed };
    return this.bands;
  }
}

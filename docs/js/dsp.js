// Elaborazione del segnale: tutto cio' che serve a capire CHI sta parlando,
// scritto a mano perche' deve girare nel browser di un telefono senza scaricare
// nulla e senza chiedere niente a nessun server.
//
// La catena e' quella classica del riconoscimento del parlante:
//   preenfasi -> finestratura -> FFT -> banco di filtri Mel -> log -> DCT = MFCC
// piu' la frequenza fondamentale (l'altezza della voce), che e' fortemente
// caratteristica della persona ed e' robusta al rumore.

export const SR = 16000;
const FRAME_LEN = 400;   // 25 ms
const FRAME_HOP = 160;   // 10 ms
const N_FFT = 512;
const N_MEL = 26;
const N_MFCC = 13;
const F_MIN = 80;
const F_MAX = 7600;

// ---------------------------------------------------------------- finestre
const hamming = (() => {
  const w = new Float32Array(FRAME_LEN);
  for (let i = 0; i < FRAME_LEN; i++) {
    w[i] = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (FRAME_LEN - 1));
  }
  return w;
})();

// -------------------------------------------------------------------- FFT
// Radix-2 iterativa in-place. N_FFT e' una potenza di due, quindi basta questa.
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wRe = Math.cos(ang), wIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curRe = 1, curIm = 0;
      for (let k = 0; k < len / 2; k++) {
        const uRe = re[i + k], uIm = im[i + k];
        const vRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm;
        const vIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe;
        re[i + k] = uRe + vRe;       im[i + k] = uIm + vIm;
        re[i + k + len / 2] = uRe - vRe; im[i + k + len / 2] = uIm - vIm;
        const nextRe = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
      }
    }
  }
}

// --------------------------------------------------------- banco Mel
const hzToMel = (hz) => 2595 * Math.log10(1 + hz / 700);
const melToHz = (mel) => 700 * (10 ** (mel / 2595) - 1);

// La scala Mel comprime le alte frequenze come fa l'orecchio: due suoni a 300 e
// 400 Hz si distinguono, a 8000 e 8100 no. Il banco di filtri riproduce questo.
const melBank = (() => {
  const bins = N_FFT / 2 + 1;
  const points = new Float64Array(N_MEL + 2);
  const melLo = hzToMel(F_MIN), melHi = hzToMel(F_MAX);
  for (let i = 0; i < points.length; i++) {
    const hz = melToHz(melLo + ((melHi - melLo) * i) / (N_MEL + 1));
    points[i] = Math.floor(((N_FFT + 1) * hz) / SR);
  }
  const bank = [];
  for (let m = 1; m <= N_MEL; m++) {
    const filt = new Float32Array(bins);
    const [lo, mid, hi] = [points[m - 1], points[m], points[m + 1]];
    for (let k = lo; k < mid; k++) if (mid > lo) filt[k] = (k - lo) / (mid - lo);
    for (let k = mid; k < hi; k++) if (hi > mid) filt[k] = (hi - k) / (hi - mid);
    bank.push(filt);
  }
  return bank;
})();

// Matrice DCT-II precalcolata: decorrela i coefficienti Mel.
const dctMatrix = (() => {
  const m = [];
  for (let i = 0; i < N_MFCC; i++) {
    const row = new Float32Array(N_MEL);
    for (let j = 0; j < N_MEL; j++) {
      row[j] = Math.cos((Math.PI * i * (j + 0.5)) / N_MEL);
    }
    m.push(row);
  }
  return m;
})();

// ------------------------------------------------------------- misure base
export function rms(frame) {
  if (!frame.length) return 0;
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

export function dbfs(frame) {
  return 20 * Math.log10(Math.max(rms(frame), 1e-10));
}

/**
 * Frequenza fondamentale con autocorrelazione.
 *
 * E' meno precisa dei metodi moderni, ma qui non serve precisione musicale:
 * serve sapere se questa voce e' piu' acuta o piu' grave della mia, e per
 * quello basta. Restituisce 0 quando il frame non e' sonoro (consonanti,
 * respiro, rumore).
 */
export function pitch(frame, sampleRate = SR) {
  const minLag = Math.floor(sampleRate / 400);   // 400 Hz
  const maxLag = Math.floor(sampleRate / 60);    // 60 Hz
  if (frame.length < maxLag + 1) return 0;

  let mean = 0;
  for (let i = 0; i < frame.length; i++) mean += frame[i];
  mean /= frame.length;

  let energy = 0;
  for (let i = 0; i < frame.length; i++) energy += (frame[i] - mean) ** 2;
  if (energy < 1e-8) return 0;

  let bestLag = 0, bestScore = 0;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let sum = 0;
    for (let i = 0; i + lag < frame.length; i++) {
      sum += (frame[i] - mean) * (frame[i + lag] - mean);
    }
    const score = sum / energy;
    if (score > bestScore) { bestScore = score; bestLag = lag; }
  }
  // Sotto 0.3 di correlazione il periodo trovato e' rumore, non voce.
  return bestScore > 0.3 && bestLag > 0 ? sampleRate / bestLag : 0;
}

// -------------------------------------------------------------- MFCC
/** MFCC di un singolo frame gia' finestrato. */
function mfccFrame(frame) {
  const re = new Float64Array(N_FFT);
  const im = new Float64Array(N_FFT);
  // Preenfasi: alza le alte frequenze, dove stanno le informazioni sul timbro.
  re[0] = frame[0];
  for (let i = 1; i < frame.length; i++) re[i] = frame[i] - 0.97 * frame[i - 1];
  for (let i = 0; i < frame.length; i++) re[i] *= hamming[i];

  fft(re, im);

  const bins = N_FFT / 2 + 1;
  const power = new Float64Array(bins);
  for (let k = 0; k < bins; k++) power[k] = (re[k] * re[k] + im[k] * im[k]) / N_FFT;

  const melEnergies = new Float64Array(N_MEL);
  for (let m = 0; m < N_MEL; m++) {
    let sum = 0;
    const filt = melBank[m];
    for (let k = 0; k < bins; k++) sum += power[k] * filt[k];
    melEnergies[m] = Math.log(Math.max(sum, 1e-10));
  }

  const out = new Float32Array(N_MFCC);
  for (let i = 0; i < N_MFCC; i++) {
    let sum = 0;
    const row = dctMatrix[i];
    for (let j = 0; j < N_MEL; j++) sum += melEnergies[j] * row[j];
    out[i] = sum;
  }
  return out;
}

/**
 * Estrae la sequenza di MFCC e di pitch dai frame sonori di un segmento.
 *
 * Si tengono solo i frame con energia sufficiente: i silenzi in mezzo alle
 * parole descrivono la stanza, non la persona, e includerli avvicinerebbe fra
 * loro tutte le voci registrate nello stesso posto.
 */
export function analyze(audio, sampleRate = SR) {
  const frames = [];
  const pitches = [];
  const level = dbfs(audio);
  const soglia = Math.max(level - 25, -55);   // 25 dB sotto il picco del segmento

  for (let start = 0; start + FRAME_LEN <= audio.length; start += FRAME_HOP) {
    const frame = audio.subarray(start, start + FRAME_LEN);
    if (dbfs(frame) < soglia) continue;
    frames.push(mfccFrame(frame));
    const f0 = pitch(frame, sampleRate);
    if (f0 > 0) pitches.push(f0);
  }
  return { frames, pitches };
}

/**
 * Impronta vocale di un segmento: un vettore di lunghezza fissa, GREZZO.
 *
 * Contiene media e deviazione standard degli MFCC (il timbro e quanto varia) e
 * le statistiche del pitch in scala logaritmica (l'altezza della voce).
 *
 * Volutamente non normalizzato e non pesato: dare pesi a mano alle varie parti
 * sarebbe indovinare. Ci pensa il verificatore, che standardizza ogni
 * dimensione sulla variabilita' misurata durante l'arruolamento - cosi' una
 * dimensione che nella mia voce e' stabile pesa molto, e una che oscilla da
 * sola pesa poco. E' il peso giusto, ed e' misurato invece che scelto.
 */
export function embed(audio, sampleRate = SR) {
  const { frames, pitches } = analyze(audio, sampleRate);
  if (frames.length < 8) return null;   // meno di ~100 ms di voce: non basta

  const n = frames.length;
  const mean = new Float64Array(N_MFCC);
  for (const f of frames) for (let i = 0; i < N_MFCC; i++) mean[i] += f[i] / n;

  const std = new Float64Array(N_MFCC);
  for (const f of frames) {
    for (let i = 0; i < N_MFCC; i++) std[i] += (f[i] - mean[i]) ** 2 / n;
  }
  for (let i = 0; i < N_MFCC; i++) std[i] = Math.sqrt(std[i]);

  // Il coefficiente 0 e' l'energia complessiva: dipende da quanto sei vicino al
  // microfono, non da chi sei. Si scarta.
  const vec = [];
  for (let i = 1; i < N_MFCC; i++) vec.push(mean[i]);
  for (let i = 1; i < N_MFCC; i++) vec.push(std[i]);

  if (pitches.length >= 3) {
    const logs = pitches.map(Math.log);
    const pMean = logs.reduce((a, b) => a + b, 0) / logs.length;
    const pStd = Math.sqrt(logs.reduce((a, b) => a + (b - pMean) ** 2, 0) / logs.length);
    vec.push(pMean, pStd);
  } else {
    // Nessun frame sonoro: metto il valore medio di una voce adulta, cosi' la
    // dimensione non spara un valore assurdo che falserebbe la distanza.
    vec.push(Math.log(140), 0.2);
  }

  return Float32Array.from(vec);
}

export const EMBED_DIM = (N_MFCC - 1) * 2 + 2;

// ------------------------------------------------------------- vettori
export function normalize(vec) {
  let norm = 0;
  for (let i = 0; i < vec.length; i++) norm += vec[i] * vec[i];
  norm = Math.sqrt(norm);
  if (norm < 1e-10) return vec;
  const out = new Float32Array(vec.length);
  for (let i = 0; i < vec.length; i++) out[i] = vec[i] / norm;
  return out;
}

export function cosine(a, b) {
  if (!a || !b || a.length !== b.length) return 0;
  let dot = 0;
  for (let i = 0; i < a.length; i++) dot += a[i] * b[i];
  return dot;
}

/**
 * Stima adattiva del rumore di fondo.
 *
 * Sale piano e scende in fretta: il brusio costante della stanza viene
 * imparato, un colpo di tosse improvviso no.
 */
export class NoiseFloor {
  constructor(initialDb = -60, up = 0.02, down = 0.25) {
    this.valueDb = initialDb;
    this.up = up;
    this.down = down;
  }
  update(frame) {
    const level = dbfs(frame);
    const alpha = level > this.valueDb ? this.up : this.down;
    this.valueDb += alpha * (level - this.valueDb);
    return this.valueDb;
  }
  isNearField(frame, marginDb) {
    return dbfs(frame) >= this.valueDb + marginDb;
  }
}

export function resample(audio, from, to) {
  if (from === to || !audio.length) return audio;
  const outLen = Math.round((audio.length * to) / from);
  const out = new Float32Array(outLen);
  const ratio = (audio.length - 1) / Math.max(outLen - 1, 1);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const idx = Math.floor(pos);
    const frac = pos - idx;
    out[i] = idx + 1 < audio.length
      ? audio[idx] * (1 - frac) + audio[idx + 1] * frac
      : audio[idx];
  }
  return out;
}

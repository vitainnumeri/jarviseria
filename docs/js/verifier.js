// Il portiere: decide se chi sta parlando e' il proprietario del telefono.
//
// Stessa architettura della versione da computer, con un motore piu' debole:
// li' c'e' una rete neurale addestrata su migliaia di voci, qui ci sono le
// caratteristiche acustiche calcolate a mano. La differenza e' reale e va
// detta - ma la logica di decisione, che e' quella che regge in una stanza
// affollata, e' la stessa:
//
//   1. campo vicino  chi e' lontano dal microfono viene scartato per fisica
//   2. somiglianza   distanza dalla mia voce, standardizzata
//   3. margine       devo somigliare a me piu' che a chiunque altro presente
//   4. maggioranza   un turno vale se lo superano abbastanza finestre
//
// Il punto 3 e' quello che fa la differenza fra "funziona a casa da solo" e
// "funziona in mezzo alla gente".

import { EMBED_DIM, NoiseFloor, dbfs, embed } from './dsp.js';

export const DECISION = { OWNER: 'owner', STRANGER: 'stranger', UNCERTAIN: 'uncertain' };

export const DEFAULTS = {
  acceptThreshold: 0.42,
  continueThreshold: 0.32,
  rejectMargin: 0.08,
  windowSec: 1.5,
  hopSec: 0.75,
  minWindowsRatio: 0.6,
  earlyRejectWindows: 3,
  nearFieldEnabled: true,
  nearFieldMarginDb: 8,
  cohortEnabled: true,
  cohortAutoLearn: true,
  cohortMaxSize: 60,
  sampleRate: 16000,
};

// Quanto ci si fida della variabilita' misurata su poche frasi: con 8
// registrazioni la deviazione standard per-dimensione e' rumorosa, quindi la si
// mescola con quella media di tutte le dimensioni.
const SHRINKAGE = 0.35;

/**
 * Profilo del proprietario: le impronte di arruolamento piu' le statistiche
 * che servono a standardizzare il confronto.
 */
export class VoiceProfile {
  /**
   * @param vectors      impronte che definiscono questa voce
   * @param referenceStd scala da usare quando le impronte sono troppo poche per
   *                     stimarne una propria. Fondamentale per la coorte: il
   *                     margine confronta il punteggio del proprietario con
   *                     quello degli estranei, e due punteggi calcolati con
   *                     scale diverse non sono confrontabili. Con una scala
   *                     inventata, un profilo costruito su una sola frase
   *                     assegna un punteggio altissimo a chiunque e il margine
   *                     rifiuta anche il proprietario.
   */
  constructor(vectors = [], referenceStd = null) {
    this.vectors = vectors.map((v) => Float32Array.from(v));
    this.referenceStd = referenceStd ? Float64Array.from(referenceStd) : null;
    this._recompute();
  }

  get size() { return this.vectors.length; }
  get isEmpty() { return this.vectors.length === 0; }

  add(vector) {
    this.vectors.push(Float32Array.from(vector));
    this._recompute();
  }

  _recompute() {
    if (!this.vectors.length) { this.mean = null; this.std = null; return; }
    const dim = this.vectors[0].length;
    const mean = new Float64Array(dim);
    for (const v of this.vectors) for (let i = 0; i < dim; i++) mean[i] += v[i] / this.vectors.length;

    const std = new Float64Array(dim);
    // Sotto le 4 impronte la varianza stimata da sole non vuol dire niente:
    // meglio la scala di riferimento (quella del proprietario), che rende i
    // punteggi confrontabili fra profili diversi.
    if (this.vectors.length >= 4) {
      for (const v of this.vectors) {
        for (let i = 0; i < dim; i++) std[i] += (v[i] - mean[i]) ** 2 / (this.vectors.length - 1);
      }
      for (let i = 0; i < dim; i++) std[i] = Math.sqrt(std[i]);
    } else if (this.referenceStd && this.referenceStd.length >= dim) {
      for (let i = 0; i < dim; i++) std[i] = this.referenceStd[i];
      this.mean = mean;
      this.std = std;
      return;   // scala presa in prestito: niente restringimento
    } else {
      std.fill(1);
    }

    // Restringimento verso la deviazione media: protegge dalle dimensioni che
    // per caso, sulle poche frasi registrate, sono uscite quasi costanti - e che
    // altrimenti diventerebbero infinitamente severe.
    let avg = 0;
    for (let i = 0; i < dim; i++) avg += std[i] / dim;
    for (let i = 0; i < dim; i++) {
      std[i] = Math.max((1 - SHRINKAGE) * std[i] + SHRINKAGE * avg, avg * 0.25, 1e-3);
    }

    this.mean = mean;
    this.std = std;
  }

  /**
   * Somiglianza fra un'impronta e il profilo, in (0, 1].
   *
   * Si misura di quante "deviazioni tipiche" l'impronta si allontana dalla mia
   * voce media, dimensione per dimensione. Una mia frase nuova sta a circa una
   * deviazione e prende ~0.6; la voce di un altro sta a tre o quattro e crolla
   * sotto 0.05. Il valore e' una probabilita' in senso lato, non calibrata:
   * serve a confrontarsi con una soglia, non a essere letto come percentuale.
   */
  score(vector) {
    if (this.isEmpty || !vector) return 0;
    const dim = Math.min(vector.length, this.mean.length);
    let sum = 0;
    for (let i = 0; i < dim; i++) {
      const z = (vector[i] - this.mean[i]) / this.std[i];
      sum += z * z;
    }
    return Math.exp(-sum / (2 * dim));
  }

  toJSON() { return { vectors: this.vectors.map((v) => Array.from(v)) }; }

  static fromJSON(data) {
    if (!data || !Array.isArray(data.vectors)) return new VoiceProfile();
    return new VoiceProfile(data.vectors);
  }
}

/**
 * Le voci degli altri.
 *
 * Si riempie da sola con cio' che viene rifiutato: dopo qualche minuto in una
 * stanza il telefono conosce chi c'e' e diventa piu' severo proprio verso quelle
 * voci. E' la contromisura piu' efficace che esista in un ambiente affollato, e
 * non chiede niente all'utente.
 */
export class Cohort {
  constructor(profiles = [], maxSize = DEFAULTS.cohortMaxSize, referenceStd = null) {
    this.referenceStd = referenceStd;
    this.profiles = profiles.map((p) => {
      const prof = VoiceProfile.fromJSON(p);
      prof.referenceStd = referenceStd ? Float64Array.from(referenceStd) : null;
      prof._recompute();
      return prof;
    });
    this.maxSize = maxSize;
  }

  get size() { return this.profiles.length; }

  /** Adotta la scala del proprietario, cosi' i punteggi restano confrontabili. */
  setScale(referenceStd) {
    this.referenceStd = referenceStd;
    for (const p of this.profiles) {
      p.referenceStd = referenceStd ? Float64Array.from(referenceStd) : null;
      p._recompute();
    }
  }

  add(vector) {
    if (!vector) return false;
    // Se somiglia molto a una voce gia' nota e' la stessa persona: la si
    // arricchisce invece di occupare un posto nuovo.
    for (const p of this.profiles) {
      if (p.score(vector) > 0.5) { p.add(vector); return false; }
    }
    this.profiles.push(new VoiceProfile([vector], this.referenceStd));
    if (this.profiles.length > this.maxSize) this.profiles.shift();
    return true;
  }

  /** Quanto l'impronta somiglia all'estraneo piu' somigliante. */
  bestMatch(vector) {
    let best = 0;
    for (const p of this.profiles) best = Math.max(best, p.score(vector));
    return this.profiles.length ? best : -1;
  }

  toJSON() { return { profiles: this.profiles.map((p) => p.toJSON()), maxSize: this.maxSize }; }

  static fromJSON(data) {
    if (!data || !Array.isArray(data.profiles)) return new Cohort();
    return new Cohort(data.profiles, data.maxSize || DEFAULTS.cohortMaxSize);
  }
}

/**
 * Spezza un audio nelle stesse finestre che si useranno in verifica.
 *
 * Serve ad arruolare nelle identiche condizioni in cui poi si giudica. Con
 * frasi intere l'impronta e' piu' stabile di quella di una finestra da un
 * secondo e mezzo, e il profilo finirebbe per considerare "diversa" la propria
 * voce solo perche' misurata su un pezzo piu' corto. Allineare le due cose vale
 * piu' di qualunque ritocco alle soglie.
 */
export function embedWindows(audio, cfg = DEFAULTS) {
  const win = Math.floor(cfg.windowSec * cfg.sampleRate);
  const hop = Math.floor(cfg.hopSec * cfg.sampleRate);
  const out = [];
  if (audio.length < win) {
    const v = embed(audio, cfg.sampleRate);
    return v ? [v] : [];
  }
  for (let start = 0; start + win <= audio.length; start += hop) {
    const v = embed(audio.subarray(start, start + win), cfg.sampleRate);
    if (v) out.push(v);
  }
  return out;
}

export class SpeakerVerifier {
  constructor(profile, options = {}, cohort = null) {
    this.profile = profile || new VoiceProfile();
    this.cfg = { ...DEFAULTS, ...options };
    this.cohort = cohort || new Cohort(undefined, this.cfg.cohortMaxSize);
    // Il margine ha senso solo se i due punteggi sono misurati con lo stesso metro.
    this.cohort.setScale(this.profile.std);
    this.noise = new NoiseFloor();
    this.locked = false;
    this.stats = { accepted: 0, rejected: 0, windows: 0 };
  }

  observeNoise(frame) { return this.noise.update(frame); }
  resetTurn() { this.locked = false; }
  get threshold() { return this.locked ? this.cfg.continueThreshold : this.cfg.acceptThreshold; }

  /** Valuta una finestra di ~1,5 secondi. */
  scoreWindow(audio, index = 0) {
    const levelDb = dbfs(audio);
    const near = this.cfg.nearFieldEnabled
      ? this.noise.isNearField(audio, this.cfg.nearFieldMarginDb)
      : true;

    const vector = embed(audio, this.cfg.sampleRate);
    if (!vector) {
      return { index, ownerScore: 0, cohortScore: -1, margin: 0, levelDb,
               nearField: near, decision: DECISION.UNCERTAIN, passed: false, vector: null };
    }

    const ownerScore = this.profile.score(vector);
    const cohortScore = this.cfg.cohortEnabled ? this.cohort.bestMatch(vector) : -1;
    const margin = cohortScore >= 0 ? ownerScore - cohortScore : Infinity;

    let decision;
    if (!near) decision = DECISION.STRANGER;                        // troppo lontano
    else if (ownerScore < this.threshold) decision = DECISION.STRANGER;   // non mi somiglia
    else if (margin < this.cfg.rejectMargin) decision = DECISION.STRANGER; // somiglia a un altro
    else decision = DECISION.OWNER;

    this.stats.windows++;
    return { index, ownerScore, cohortScore, margin: Number.isFinite(margin) ? margin : 1,
             levelDb, nearField: near, decision, passed: decision === DECISION.OWNER, vector };
  }

  _windows(audio) {
    const win = Math.floor(this.cfg.windowSec * this.cfg.sampleRate);
    const hop = Math.floor(this.cfg.hopSec * this.cfg.sampleRate);
    if (audio.length < win) return audio.length ? [audio] : [];
    const out = [];
    for (let start = 0; start + win <= audio.length; start += hop) {
      out.push(audio.subarray(start, start + win));
    }
    return out;
  }

  /** Verdetto su un turno completo di parlato. */
  verify(audio, { learn = true } = {}) {
    if (audio.length < 0.4 * this.cfg.sampleRate) {
      return { decision: DECISION.UNCERTAIN, score: 0, windows: [], acceptedRatio: 0,
               reason: 'troppo breve per riconoscere la voce' };
    }

    const windows = this._windows(audio).map((w, i) => this.scoreWindow(w, i));
    if (!windows.length) {
      return { decision: DECISION.UNCERTAIN, score: 0, windows: [], acceptedRatio: 0,
               reason: 'nessuna finestra analizzabile' };
    }

    const passed = windows.filter((w) => w.passed);
    const ratio = passed.length / windows.length;
    const scores = windows.map((w) => w.ownerScore).sort((a, b) => a - b);
    const median = scores[Math.floor(scores.length / 2)];

    if (ratio >= this.cfg.minWindowsRatio) {
      this.stats.accepted++;
      const passedScores = passed.map((w) => w.ownerScore).sort((a, b) => a - b);
      return {
        decision: DECISION.OWNER,
        score: passedScores[Math.floor(passedScores.length / 2)],
        windows, acceptedRatio: ratio, reason: 'voce del proprietario confermata',
      };
    }

    this.stats.rejected++;
    // Imparo la voce solo se e' CHIARAMENTE di un altro. Un mio turno respinto
    // per un soffio - ho parlato piano, mi sono girato dall'altra parte - non
    // deve finire fra gli estranei: da li' in poi il margine lavorerebbe contro
    // di me e il sistema smetterebbe progressivamente di riconoscermi.
    const clearlyStranger = median < this.threshold * 0.5;
    if (learn && this.cfg.cohortAutoLearn && ratio === 0 && clearlyStranger) {
      const vectors = windows.map((w) => w.vector).filter(Boolean);
      if (vectors.length) this.cohort.add(vectors[Math.floor(vectors.length / 2)]);
    }
    return {
      decision: DECISION.STRANGER, score: median, windows, acceptedRatio: ratio,
      reason: `voce non riconosciuta (${passed.length}/${windows.length} finestre superate)`,
    };
  }

  /**
   * Decisione parziale mentre l'utente sta ancora parlando.
   *
   * Permette di scartare un estraneo dopo un paio di secondi invece di
   * aspettare la fine della frase: l'assistente resta zitto e chi ha parlato
   * non si accorge di niente.
   */
  streamDecision(windows) {
    if (!windows.length) return DECISION.UNCERTAIN;
    const tail = windows.slice(-this.cfg.earlyRejectWindows);
    if (tail.length >= this.cfg.earlyRejectWindows && !tail.some((w) => w.passed)) {
      this.locked = false;
      return DECISION.STRANGER;
    }
    if (windows.some((w) => w.passed)) { this.locked = true; return DECISION.OWNER; }
    return DECISION.UNCERTAIN;
  }
}

/**
 * Calibra le soglie sulle frasi di arruolamento, invece di usare un numero fisso.
 *
 * Un valore scelto a priori non puo' andare bene per tutti: dipende dalla voce,
 * dal microfono e dalla stanza. Qui si misura direttamente quanto la persona
 * somiglia a se stessa, con la tecnica "lascia fuori uno": ogni frase viene
 * valutata contro un profilo costruito con le ALTRE, che e' esattamente la
 * situazione di una frase nuova. La soglia va poco sotto il peggiore di quei
 * punteggi, cosi' l'utente non deve ripetersi, e non piu' sotto di cosi'.
 */
export function calibrate(profile, { safety = 0.5, floor = 0.12 } = {}) {
  if (profile.size < 3) {
    return { acceptThreshold: DEFAULTS.acceptThreshold,
             continueThreshold: DEFAULTS.continueThreshold,
             samples: profile.size,
             note: 'poche frasi registrate: soglie prudenziali di default' };
  }

  const scores = [];
  for (let i = 0; i < profile.size; i++) {
    const others = profile.vectors.filter((_, j) => j !== i);
    scores.push(new VoiceProfile(others).score(profile.vectors[i]));
  }
  scores.sort((a, b) => a - b);

  // Il 20esimo percentile invece del minimo: una singola frase venuta male
  // (un colpo di tosse, un rumore) non deve abbassare la soglia per sempre.
  const p20 = scores[Math.floor(scores.length * 0.2)];
  // Ben sotto il proprio ventesimo percentile, non appena sotto.
  //
  // Misurando, la distanza fra le mie finestre peggiori e le migliori di un
  // estraneo e' enorme: abbassare la soglia toglie ripetizioni senza far
  // passare nessuno. La difesa vera contro gli altri non e' questo numero, e'
  // il margine sulla coorte - quello si adatta a chi c'e' davvero nella stanza,
  // una soglia fissa no.
  const accept = Math.max(floor, Math.min(p20 * safety, 0.5));
  return {
    acceptThreshold: Number(accept.toFixed(3)),
    continueThreshold: Number(Math.max(floor * 0.7, accept * 0.72).toFixed(3)),
    samples: profile.size,
    selfScores: scores.map((s) => Number(s.toFixed(3))),
    note: p20 < 0.2
      ? 'le tue frasi si somigliano poco fra loro: rifai l\'arruolamento in un posto piu\' silenzioso'
      : 'calibrazione riuscita',
  };
}

/**
 * Quanto e' omogeneo il profilo: rileva se in mezzo alle frasi registrate si e'
 * infilata un'altra persona.
 *
 * Misurando, le metriche basate sul punteggio non servono: contaminare un
 * profilo ne allarga la varianza, e i punteggi calcolati su quella varianza
 * allargata SALGONO invece di scendere. Conta invece la forma della nuvola di
 * punti - se le frasi sono di una persona sola le distanze dal centro si
 * somigliano tutte, se ce ne sono due la distribuzione si sdoppia.
 *
 * Il rapporto fra la distanza al 90esimo percentile e quella mediana e'
 * adimensionale, quindi non dipende dalla scala delle caratteristiche: intorno
 * a 1 il profilo e' pulito, sopra 2 qualcun altro ha parlato.
 */
export function profileHomogeneity(profile) {
  if (profile.size < 4) return { ratio: 1, clean: true, note: 'troppo poche frasi per giudicare' };

  const distanze = profile.vectors.map((v) => {
    let d = 0;
    for (let i = 0; i < v.length; i++) d += (v[i] - profile.mean[i]) ** 2;
    return Math.sqrt(d);
  }).sort((a, b) => a - b);

  const mediana = distanze[Math.floor(distanze.length * 0.5)] || 1e-6;
  const p90 = distanze[Math.floor(distanze.length * 0.9)];
  const ratio = p90 / Math.max(mediana, 1e-6);
  return {
    ratio: Number(ratio.toFixed(2)),
    clean: ratio < 2,
    note: ratio < 2
      ? 'profilo omogeneo'
      : 'le frasi registrate non sembrano tutte della stessa voce: rifai l\'arruolamento da solo e in un posto silenzioso',
  };
}

export { EMBED_DIM };

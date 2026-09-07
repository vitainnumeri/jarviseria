// L'orchestratore: mette insieme microfono, riconoscimento del parlante,
// trascrizione, modello e voce.
//
// Il nodo di tutto e' come si incrociano due flussi indipendenti:
//
//   - il MIO flusso audio, da cui ricavo ogni mezzo secondo un giudizio
//     "questa finestra e' il proprietario / e' un altro";
//   - il flusso del riconoscimento vocale del sistema, che trascrive tutto
//     quello che sente, mie parole e parole altrui allo stesso modo.
//
// Quando arriva una frase trascritta, guardo che cosa diceva la biometria
// NELL'INTERVALLO di quella frase. Se in quel momento parlavo io, la frase va
// al modello; altrimenti viene buttata senza che succeda nulla.

import { NoiseFloor, dbfs, resample } from './dsp.js';
import { Agente, frasi, svuotaFrasi } from './llm.js';
import { Cervello } from './cervello.js';
import { Asta, Listone } from './fanta.js';
import { DEFINIZIONI, Strumenti } from './strumenti.js';
import { istruzioni } from './prompt.js';
import { Trascrittore, Voce, sintesiDisponibile, trascrizioneDisponibile } from './voce.js';
import { calibrate, Cohort, DECISION, embedWindows, SpeakerVerifier, VoiceProfile } from './verifier.js';

export const SR = 16000;
const MEMORIA_FINESTRE_MS = 30000;   // quanto indietro ricordo chi ha parlato

// ------------------------------------------------------------- archivio
const CHIAVI = {
  profilo: 'jarvis.profilo', coorte: 'jarvis.coorte', soglie: 'jarvis.soglie',
  apiKey: 'jarvis.apikey', listone: 'jarvis.listone', asta: 'jarvis.asta',
  config: 'jarvis.config',
};

export const archivio = {
  leggi(chiave, def = null) {
    try { const v = localStorage.getItem(chiave); return v ? JSON.parse(v) : def; }
    catch { return def; }
  },
  scrivi(chiave, valore) {
    try { localStorage.setItem(chiave, JSON.stringify(valore)); return true; }
    catch { return false; }   // memoria piena o navigazione privata
  },
  cancella(chiave) { try { localStorage.removeItem(chiave); } catch { /* niente */ } },
};

export const FRASI_ARRUOLAMENTO = [
  'Ciao, sono io. Questa e la mia voce e voglio che tu riconosca solo me.',
  'Quest anno all asta punto forte sul centrocampo e tengo crediti per il finale.',
  'Quanto vale questo attaccante secondo le quotazioni e qual e il prezzo massimo?',
  'Schiera il tre cinque due con il portiere titolare e i due difensori della stessa squadra.',
  'Trentatre trentini entrarono a Trento tutti e trentatre trotterellando.',
  'Se il rigorista e diffidato preferisco la punta che gioca in casa contro l ultima in classifica.',
  'Aggiudicato a centoventi crediti: aggiorna la rosa e ricalcola quello che mi resta.',
  'Dimmi la probabile formazione, chi e infortunato e chi rientra dalla squalifica.',
];

// -------------------------------------------------------- cattura audio
// Il worklet gira nel thread audio e ricampiona a 16 kHz: il resto del
// programma vede sempre e solo frame a quella frequenza.
const WORKLET = `
class Cattura extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / ${SR}; this.pos = 0; this.coda = new Float32Array(0); }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    const buf = new Float32Array(this.coda.length + ch.length);
    buf.set(this.coda); buf.set(ch, this.coda.length);
    const out = [];
    let p = this.pos;
    while (p + 1 < buf.length) {
      const i = Math.floor(p), f = p - i;
      out.push(buf[i] * (1 - f) + buf[i + 1] * f);
      p += this.ratio;
    }
    const usati = Math.floor(p);
    this.coda = buf.slice(usati);
    this.pos = p - usati;
    if (out.length) this.port.postMessage(Float32Array.from(out));
    return true;
  }
}
registerProcessor('cattura', Cattura);
`;

export class Microfono {
  constructor(onFrame) { this.onFrame = onFrame; this.ctx = null; this.stream = null; }

  async avvia() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        // Serve: senza, il telefono si riascolta mentre parla.
        echoCancellation: true,
        // Queste due NO, ed e' importante.
        // Il guadagno automatico alzerebbe le voci lontane fino al livello
        // della mia, annullando il filtro che scarta chi e' lontano.
        autoGainControl: false,
        // La soppressione del rumore altera il timbro, cioe' esattamente cio'
        // che il riconoscimento del parlante misura.
        noiseSuppression: false,
      },
    });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await this.ctx.resume();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
    await this.ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const nodo = new AudioWorkletNode(this.ctx, 'cattura');
    nodo.port.onmessage = (e) => this.onFrame(e.data);
    this.ctx.createMediaStreamSource(this.stream).connect(nodo);
    this.nodo = nodo;
  }

  ferma() {
    try { this.nodo?.disconnect(); } catch { /* gia' scollegato */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.ctx = null; this.stream = null; this.nodo = null;
  }
}

// ------------------------------------------------------------- sessione
export class Sessione {
  constructor({ onEvento = () => {} } = {}) {
    this.onEvento = onEvento;
    this.config = { budget: 500, ...archivio.leggi(CHIAVI.config, {}) };

    this.listone = new Listone(archivio.leggi(CHIAVI.listone, []) || []);
    this.asta = Asta.fromJSON(archivio.leggi(CHIAVI.asta));
    this.asta.budget = this.config.budget;
    this.strumenti = new Strumenti(this.listone, this.asta);
    // Il cervello offline e' sempre pronto: e' la modalita' predefinita, non
    // un ripiego. Senza chiave l'app funziona e non costa niente.
    this.cervello = new Cervello(this.strumenti);

    this.profilo = VoiceProfile.fromJSON(archivio.leggi(CHIAVI.profilo));
    this.soglie = archivio.leggi(CHIAVI.soglie, {}) || {};
    this.verificatore = new SpeakerVerifier(this.profilo, this.soglie,
      Cohort.fromJSON(archivio.leggi(CHIAVI.coorte)));

    this.voce = new Voce();
    this.microfono = null;
    this.trascrittore = null;
    this.agente = null;

    this.buffer = new Float32Array(0);
    this.giudizi = [];          // { t, proprietario, punteggio }
    this.rumore = new NoiseFloor();
    this.staParlando = false;
    this.annullaRisposta = null;
    this.stats = { miei: 0, ignorati: 0, interruzioni: 0 };
  }

  get arruolato() { return this.profilo.size > 0; }

  /**
   * Quanto e' costata la conversazione finora.
   *
   * Misurato sui token che l'API dichiara di aver consumato, non stimato:
   * quando si spendono soldi veri, una stima non basta.
   */
  spesa() {
    if (!this.agente) return { dollari: 0, domande: 0, gratis: true };
    const c = this.agente.costoStimato();
    return { ...c, centesimi: Math.round(c.dollari * 100), euro: c.dollari * 0.92 };
  }
  get haChiave() { return Boolean(archivio.leggi(CHIAVI.apiKey)); }

  /**
   * 'gratis' = risponde il cervello dentro l'app; 'claude' = risponde il modello.
   *
   * La sceglie la presenza della chiave, non un interruttore: se non l'hai
   * messa e' perche' non la vuoi, e l'app deve funzionare lo stesso.
   */
  get modalita() { return this.haChiave ? 'claude' : 'gratis'; }

  // ------------------------------------------------------ configurazione
  salvaChiave(chiave) { archivio.scrivi(CHIAVI.apiKey, chiave.trim()); }
  dimenticaChiave() { archivio.cancella(CHIAVI.apiKey); }

  caricaListoneCSV(testo) {
    const listone = Listone.daCSV(testo);
    archivio.scrivi(CHIAVI.listone, listone.toJSON());
    this.listone = listone;
    this.strumenti.listone = listone;
    return listone.length;
  }

  impostaBudget(budget) {
    this.config.budget = budget;
    this.asta.budget = budget;
    archivio.scrivi(CHIAVI.config, this.config);
    archivio.scrivi(CHIAVI.asta, this.asta.toJSON());
  }

  azzeraAsta() {
    this.asta = new Asta({ budget: this.config.budget });
    this.strumenti.asta = this.asta;
    archivio.cancella(CHIAVI.asta);
  }

  // --------------------------------------------------------- arruolamento
  /**
   * Aggiunge una frase al profilo.
   *
   * Si arruola sulle stesse finestre che si useranno in verifica: usare frasi
   * intere qui e finestre corte li' farebbe sembrare "diversa" la propria voce
   * solo perche' misurata su pezzi di lunghezza diversa.
   */
  aggiungiFraseArruolamento(audio) {
    const vettori = embedWindows(audio, this.verificatore.cfg);
    for (const v of vettori) this.profilo.add(v);
    return vettori.length;
  }

  concludiArruolamento() {
    const soglie = calibrate(this.profilo);
    this.soglie = soglie;
    this.verificatore = new SpeakerVerifier(this.profilo, soglie, new Cohort());
    archivio.scrivi(CHIAVI.profilo, this.profilo.toJSON());
    archivio.scrivi(CHIAVI.soglie, soglie);
    archivio.cancella(CHIAVI.coorte);   // profilo nuovo, coorte da rifare
    return soglie;
  }

  dimenticaVoce() {
    this.profilo = new VoiceProfile();
    this.verificatore = new SpeakerVerifier(this.profilo, {}, new Cohort());
    [CHIAVI.profilo, CHIAVI.coorte, CHIAVI.soglie].forEach(archivio.cancella);
  }

  // ------------------------------------------------------------- ascolto
  async avvia() {
    if (!this.arruolato) throw new Error('devi prima registrare la tua voce');

    const chiave = archivio.leggi(CHIAVI.apiKey);
    this.agente = chiave ? new Agente({
      apiKey: chiave,
      system: istruzioni({ budget: this.config.budget, listone: this.listone.length }),
      tools: DEFINIZIONI,
      eseguiTool: (nome, args) => {
        const esito = this.strumenti.esegui(nome, args);
        archivio.scrivi(CHIAVI.asta, this.asta.toJSON());
        this.onEvento({ tipo: 'strumento', nome });
        return esito;
      },
    }) : null;

    this.microfono = new Microfono((frame) => this._frame(frame));
    await this.microfono.avvia();

    if (trascrizioneDisponibile()) {
      this.trascrittore = new Trascrittore({
        onParziale: (t) => this.onEvento({ tipo: 'parziale', testo: t }),
        onFinale: (r) => this._frase(r),
        onErrore: (e) => this.onEvento({ tipo: 'errore', testo: `trascrizione: ${e}` }),
      });
      this.trascrittore.avvia();
    } else {
      this.onEvento({ tipo: 'errore',
        testo: 'Questo browser non sa trascrivere la voce. Su iPhone usa Chrome, oppure la modalita\' con il computer.' });
    }
    this.onEvento({ tipo: 'pronto' });
  }

  ferma() {
    this.trascrittore?.ferma();
    this.microfono?.ferma();
    this.voce.zitto();
    this.annullaRisposta?.abort();
    archivio.scrivi(CHIAVI.coorte, this.verificatore.cohort.toJSON());
    archivio.scrivi(CHIAVI.asta, this.asta.toJSON());
    this.onEvento({ tipo: 'fermo' });
  }

  /** Un blocco di campioni dal microfono: qui si decide chi sta parlando. */
  _frame(campioni) {
    const unite = new Float32Array(this.buffer.length + campioni.length);
    unite.set(this.buffer); unite.set(campioni, this.buffer.length);
    this.buffer = unite;

    const finestra = Math.floor(this.verificatore.cfg.windowSec * SR);
    const passo = Math.floor(this.verificatore.cfg.hopSec * SR);
    while (this.buffer.length >= finestra) {
      const pezzo = this.buffer.subarray(0, finestra);
      this.buffer = this.buffer.slice(passo);

      // Sul silenzio non si giudica: lo si usa per imparare il rumore della stanza.
      if (dbfs(pezzo) < this.rumore.valueDb + 6) { this.rumore.update(pezzo); continue; }
      this.verificatore.observeNoise(pezzo);

      const esito = this.verificatore.scoreWindow(pezzo);
      const adesso = performance.now();
      this.giudizi.push({ t: adesso, proprietario: esito.passed, punteggio: esito.ownerScore });
      this.giudizi = this.giudizi.filter((g) => adesso - g.t < MEMORIA_FINESTRE_MS);

      if (esito.passed) {
        this.onEvento({ tipo: 'io', punteggio: esito.ownerScore });
        // Sono io e l'assistente sta parlando: ho ripreso la parola.
        if (this.staParlando) {
          this.stats.interruzioni++;
          this.voce.zitto();
          this.annullaRisposta?.abort();
          this.onEvento({ tipo: 'interrotto' });
        }
      } else if (!this.staParlando) {
        this.onEvento({ tipo: 'altri', punteggio: esito.ownerScore });
      }
    }
  }

  /**
   * Una frase trascritta e' pronta: era mia?
   *
   * Si guarda solo l'intervallo in cui la frase e' stata pronunciata. Se il
   * riconoscimento vocale non ha saputo dire quando e' cominciata, si guardano
   * gli ultimi secondi, che e' la stessa cosa nella pratica.
   */
  _frase({ testo, inizio, fine }) {
    if (this.staParlando) return;   // e' l'assistente che si e' riascoltato

    const da = inizio || fine - 6000;
    const dentro = this.giudizi.filter((g) => g.t >= da - 500 && g.t <= fine + 500);
    if (!dentro.length) {
      this.onEvento({ tipo: 'ignorato', testo, motivo: 'non ho sentito nessuna voce vicina' });
      this.stats.ignorati++;
      return;
    }
    const quota = dentro.filter((g) => g.proprietario).length / dentro.length;
    if (quota < this.verificatore.cfg.minWindowsRatio) {
      this.stats.ignorati++;
      const medio = dentro.reduce((n, g) => n + g.punteggio, 0) / dentro.length;
      this.onEvento({ tipo: 'ignorato', testo, punteggio: medio,
                      motivo: 'non e\' la tua voce' });
      return;
    }

    this.stats.miei++;
    this.onEvento({ tipo: 'trascritto', testo, quota });
    this._rispondi(testo);
  }

  async _rispondi(testo) {
    if (this.modalita === 'gratis') return this._rispondiOffline(testo);
    return this._rispondiConClaude(testo);
  }

  /**
   * Risposta del cervello offline: immediata, gratuita, senza rete.
   *
   * Non c'e' streaming perche' non c'e' niente da aspettare - la frase e' gia'
   * pronta nel momento in cui si capisce la domanda.
   */
  async _rispondiOffline(testo) {
    this.staParlando = true;
    const controller = new AbortController();
    this.annullaRisposta = controller;
    try {
      const { risposta, intenzione } = this.cervello.ascolta(testo);
      this.onEvento({ tipo: 'dice', testo: risposta, intenzione });
      archivio.scrivi(CHIAVI.asta, this.asta.toJSON());
      if (!controller.signal.aborted) await this.voce.parla(risposta);
      this.onEvento({ tipo: 'finito', testo: risposta });
    } finally {
      this.staParlando = false;
      this.annullaRisposta = null;
    }
  }

  async _rispondiConClaude(testo) {
    const controller = new AbortController();
    this.annullaRisposta = controller;
    const stato = { buffer: '' };
    const dette = [];
    this.staParlando = true;

    try {
      for await (const pezzo of this.agente.rispondi(testo, { segnale: controller.signal })) {
        if (controller.signal.aborted) break;
        for (const frase of frasi(pezzo, stato)) {
          if (controller.signal.aborted) break;
          dette.push(frase);
          this.onEvento({ tipo: 'dice', testo: frase });
          await this.voce.parla(frase);
        }
      }
      if (!controller.signal.aborted) {
        for (const frase of svuotaFrasi(stato)) {
          dette.push(frase);
          this.onEvento({ tipo: 'dice', testo: frase });
          await this.voce.parla(frase);
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') this.onEvento({ tipo: 'errore', testo: e.message });
    } finally {
      this.staParlando = false;
      this.annullaRisposta = null;
      archivio.scrivi(CHIAVI.asta, this.asta.toJSON());
      this.onEvento({ tipo: 'finito', testo: dette.join(' ') });
    }
  }
}

export { CHIAVI, sintesiDisponibile, trascrizioneDisponibile, DECISION };

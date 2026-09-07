// Trascrizione e sintesi, usando quello che il telefono ha gia' dentro.
//
// Nessun modello da scaricare: il riconoscimento vocale e la voce sintetica
// sono servizi del sistema operativo, esposti al browser. E' la ragione per cui
// questa app puo' funzionare su un telefono senza chiedere 500 MB di rete.

// ------------------------------------------------------------ trascrizione
const Riconoscitore = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;

export const trascrizioneDisponibile = () => Boolean(Riconoscitore);

/**
 * Riconoscimento vocale continuo.
 *
 * NON decide chi sta parlando: si limita a trasformare in testo tutto cio' che
 * sente, comprese le voci degli altri. La distinzione la fa il verificatore, e
 * il testo di un turno viene buttato se in quel momento la voce non era la tua.
 *
 * Nota sulla riservatezza: su Chrome questo servizio manda l'audio ai server di
 * Google per la trascrizione. E' scritto anche nella pagina.
 */
export class Trascrittore {
  constructor({ lingua = 'it-IT', onParziale = null, onFinale = null, onErrore = null } = {}) {
    this.lingua = lingua;
    this.onParziale = onParziale;
    this.onFinale = onFinale;
    this.onErrore = onErrore;
    this.attivo = false;
    this.rec = null;
    this.inizioFrase = 0;
  }

  avvia() {
    if (!Riconoscitore) throw new Error('questo browser non sa trascrivere la voce');
    if (this.attivo) return;

    const rec = new Riconoscitore();
    rec.lang = this.lingua;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (evento) => {
      for (let i = evento.resultIndex; i < evento.results.length; i++) {
        const risultato = evento.results[i];
        const testo = risultato[0].transcript.trim();
        if (!testo) continue;
        if (risultato.isFinal) {
          this.onFinale?.({ testo, inizio: this.inizioFrase, fine: performance.now(),
                            confidenza: risultato[0].confidence });
          this.inizioFrase = 0;
        } else {
          if (!this.inizioFrase) this.inizioFrase = performance.now();
          this.onParziale?.(testo);
        }
      }
    };

    rec.onerror = (evento) => {
      // 'no-speech' e 'aborted' sono normali in una sessione lunga: non sono
      // errori da mostrare, sono il silenzio.
      if (evento.error === 'no-speech' || evento.error === 'aborted') return;
      this.onErrore?.(evento.error);
    };

    // Il riconoscimento si ferma da solo dopo qualche secondo di silenzio:
    // riavviarlo e' l'unico modo per avere un ascolto davvero continuo.
    rec.onend = () => { if (this.attivo) { try { rec.start(); } catch { /* gia' avviato */ } } };

    this.rec = rec;
    this.attivo = true;
    rec.start();
  }

  ferma() {
    this.attivo = false;
    try { this.rec?.stop(); } catch { /* gia' fermo */ }
    this.rec = null;
  }
}

// ---------------------------------------------------------------- sintesi
export const sintesiDisponibile = () => Boolean(globalThis.speechSynthesis);

/** Voce sintetica del sistema. Zero latenza di rete, funziona anche offline. */
export class Voce {
  constructor({ lingua = 'it-IT', velocita = 1.08 } = {}) {
    this.lingua = lingua;
    this.velocita = velocita;
    this.voce = null;
    this.inCorso = false;
    this._scegliVoce();
    // L'elenco delle voci su alcuni browser arriva dopo, in modo asincrono.
    globalThis.speechSynthesis?.addEventListener?.('voiceschanged', () => this._scegliVoce());
  }

  _scegliVoce() {
    const voci = globalThis.speechSynthesis?.getVoices?.() || [];
    const italiane = voci.filter((v) => v.lang?.startsWith('it'));
    // Le voci locali non hanno latenza di rete: in asta e' cio' che conta.
    this.voce = italiane.find((v) => v.localService) || italiane[0] || null;
    return this.voce;
  }

  get nomeVoce() { return this.voce?.name || 'predefinita del sistema'; }

  /** Pronuncia una frase. Si risolve quando ha finito, o subito se interrotta. */
  parla(testo) {
    return new Promise((risolvi) => {
      const sintesi = globalThis.speechSynthesis;
      if (!sintesi || !testo.trim()) return risolvi(false);

      const u = new SpeechSynthesisUtterance(testo);
      u.lang = this.lingua;
      u.rate = this.velocita;
      if (this.voce) u.voice = this.voce;
      u.onend = () => { this.inCorso = false; risolvi(true); };
      u.onerror = () => { this.inCorso = false; risolvi(false); };
      this.inCorso = true;
      sintesi.speak(u);
    });
  }

  /** Interruzione immediata: e' cio' che permette di riprendere la parola. */
  zitto() {
    this.inCorso = false;
    try { globalThis.speechSynthesis?.cancel(); } catch { /* niente in coda */ }
  }
}

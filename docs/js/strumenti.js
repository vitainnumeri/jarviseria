// Gli strumenti dell'assistente: il ponte fra la conversazione e i conti.
//
// Girano nel telefono, non nel modello. La differenza non e' teorica: il
// vincolo "crediti residui meno gli slot da riempire" deve essere esatto,
// e un modello che lo calcola a mente ogni tanto sbaglia di qualche credito.
// Qui e' aritmetica.

import { Asta, Listone, confronta, costruisciFormazione, migliorFormazione,
         modificatoreDifesa, BONUS_MALUS, MODULI, STRATEGIE } from './fanta.js';

export const DEFINIZIONI = [
  {
    name: 'cerca_giocatore',
    description: 'Cerca un giocatore nel listone per nome, tollerando le storpiature della '
      + 'trascrizione vocale. Restituisce i candidati con quotazione, FVM e ruolo. Usalo ogni '
      + 'volta che ti serve un dato su un giocatore: non fidarti della memoria.',
    input_schema: { type: 'object', properties: {
      nome: { type: 'string', description: 'Il nome come lo hai sentito' },
      limite: { type: 'integer' } }, required: ['nome'] },
  },
  {
    name: 'migliori_per_ruolo',
    description: 'I giocatori piu\' quotati di un ruolo (P, D, C, A), ordinati per valore.',
    input_schema: { type: 'object', properties: {
      ruolo: { type: 'string', enum: ['P', 'D', 'C', 'A'] },
      limite: { type: 'integer' } }, required: ['ruolo'] },
  },
  {
    name: 'consiglio_offerta',
    description: 'Quanto posso offrire per un giocatore, adesso. Tiene conto dei crediti '
      + 'residui, degli slot mancanti e del piano di reparto. USALO SEMPRE prima di dire un '
      + 'prezzo in asta: il tetto non e\' una stima, e\' un vincolo.',
    input_schema: { type: 'object', properties: {
      nome: { type: 'string' },
      offerta_attuale: { type: 'integer', description: 'A quanto e\' arrivata l\'asta' },
      quanto_lo_voglio: { type: 'number', description: '0.8 solo se capita a poco, 1.0 a piano, 1.3 lo voglio' },
    }, required: ['nome'] },
  },
  {
    name: 'registra_acquisto',
    description: 'Registra un giocatore appena aggiudicato al prezzo pagato e aggiorna budget '
      + 'e slot. Chiamalo appena te lo dice: da quel momento tutti i conti cambiano.',
    input_schema: { type: 'object', properties: {
      nome: { type: 'string' }, prezzo: { type: 'integer' } }, required: ['nome', 'prezzo'] },
  },
  {
    name: 'annulla_acquisto',
    description: 'Toglie dalla rosa un giocatore registrato per errore.',
    input_schema: { type: 'object', properties: { nome: { type: 'string' } }, required: ['nome'] },
  },
  {
    name: 'stato_asta',
    description: 'Fotografia dell\'asta: crediti residui, slot mancanti, massimo offribile, '
      + 'spesa per reparto e rosa attuale.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'piano_asta',
    description: 'Il piano di spesa: quanto destinare a ogni reparto e il prezzo obiettivo di '
      + 'ogni slot. Puoi cambiare strategia passando il suo nome.',
    input_schema: { type: 'object', properties: {
      strategia: { type: 'string', enum: Object.keys(STRATEGIE) } } },
  },
  {
    name: 'costruisci_formazione',
    description: 'Sceglie la formazione migliore fra i giocatori indicati, provando tutti i '
      + 'moduli. Senza elenco usa la rosa comprata all\'asta.',
    input_schema: { type: 'object', properties: {
      giocatori: { type: 'array', items: { type: 'string' } },
      modulo: { type: 'string', enum: Object.keys(MODULI) },
      indisponibili: { type: 'array', items: { type: 'string' } } } },
  },
  {
    name: 'confronta_giocatori',
    description: 'Chi schierare fra due giocatori, con la ragione della scelta.',
    input_schema: { type: 'object', properties: {
      primo: { type: 'string' }, secondo: { type: 'string' },
      avversario_primo: { type: 'number', description: 'Forza avversario da 1 a 5' },
      avversario_secondo: { type: 'number' },
      in_casa_primo: { type: 'boolean' }, in_casa_secondo: { type: 'boolean' },
    }, required: ['primo', 'secondo'] },
  },
  {
    name: 'regolamento',
    description: 'Bonus, malus e modificatore di difesa. Usalo per rispondere su punteggi e '
      + 'regole invece di andare a memoria.',
    input_schema: { type: 'object', properties: {
      media_reparto: { type: 'number', description: 'Per calcolare il modificatore di difesa' } } },
  },
];

export class Strumenti {
  constructor(listone, asta) {
    this.listone = listone || new Listone();
    this.asta = asta || new Asta();
  }

  /**
   * Trova un giocatore, o chiede conferma se il nome e' ambiguo.
   *
   * In asta un nome scambiato costa crediti veri, quindi quando i primi due
   * candidati sono vicini si preferisce una domanda in piu' a un acquisto
   * sbagliato.
   */
  _risolvi(nome) {
    const risultati = this.listone.cerca(nome, 3);
    if (!risultati.length) return { giocatore: null, candidati: [] };
    const candidati = risultati.map((r) => ({
      nome: r.giocatore.nome, squadra: r.giocatore.squadra,
      ruolo: r.giocatore.ruolo, somiglianza: r.punteggio,
    }));
    const ambiguo = risultati.length > 1 && risultati[0].punteggio - risultati[1].punteggio < 0.08;
    return { giocatore: ambiguo ? null : risultati[0].giocatore, candidati };
  }

  cerca_giocatore({ nome, limite = 3 }) {
    if (!this.listone.length) return { errore: 'listone non caricato: non ho quotazioni' };
    const risultati = this.listone.cerca(nome, limite);
    if (!risultati.length) {
      return { trovato: false, cercato: nome,
               nota: 'nessuna corrispondenza: forse il nome e\' stato trascritto male' };
    }
    return { trovato: true, candidati: risultati.map((r) => ({ ...r.giocatore, somiglianza: r.punteggio })) };
  }

  migliori_per_ruolo({ ruolo, limite = 10 }) {
    if (!this.listone.length) return { errore: 'listone non caricato' };
    return { ruolo, giocatori: this.listone.migliori(ruolo, limite) };
  }

  consiglio_offerta({ nome, offerta_attuale = 0, quanto_lo_voglio = 1 }) {
    const { giocatore, candidati } = this._risolvi(nome);
    if (!giocatore) {
      return candidati.length
        ? { serve_conferma: true, candidati, nota: 'chiedi quale intende prima di dare un prezzo' }
        : { errore: `'${nome}' non e' nel listone` };
    }
    return {
      ...this.asta.consiglio(giocatore, { offertaAttuale: offerta_attuale, quantoLoVoglio: quanto_lo_voglio }),
      crediti_residui: this.asta.creditiResidui,
      slot_mancanti: this.asta.slotMancanti,
      slot_mancanti_nel_ruolo: this.asta.mancanti(giocatore.ruolo),
    };
  }

  registra_acquisto({ nome, prezzo }) {
    let { giocatore, candidati } = this._risolvi(nome);
    if (!giocatore) {
      if (candidati.length) return { serve_conferma: true, candidati };
      // Fuori listone (un arrivo dell'ultimo minuto): non deve bloccare l'asta.
      giocatore = { nome, squadra: '?', ruolo: 'C', quotazione: prezzo, fvm: 0, fantamedia: null };
    }
    try { return { registrato: `${giocatore.nome} a ${prezzo}`, ...this.asta.compra(giocatore, prezzo) }; }
    catch (e) { return { errore: e.message }; }
  }

  annulla_acquisto({ nome }) {
    try { return { annullato: nome, ...this.asta.annulla(nome) }; }
    catch (e) { return { errore: e.message }; }
  }

  stato_asta() { return this.asta.stato(); }

  piano_asta({ strategia } = {}) {
    if (strategia) {
      if (!STRATEGIE[strategia]) return { errore: `strategia sconosciuta: ${strategia}` };
      this.asta.split = { ...STRATEGIE[strategia] };
    }
    return { strategia: strategia || 'corrente', ripartizione: this.asta.split,
             piano: this.asta.piano(), crediti_residui: this.asta.creditiResidui };
  }

  costruisci_formazione({ giocatori = [], modulo = null, indisponibili = [] } = {}) {
    let pool;
    if (giocatori.length) {
      pool = giocatori.map((n) => this.listone.get(n) || this.listone.cerca(n, 1)[0]?.giocatore)
        .filter(Boolean);
    } else {
      pool = this.asta.rosa.map((s) => s.giocatore);
    }
    if (!pool.length) {
      return { errore: 'non ho giocatori: dimmi la rosa oppure registra gli acquisti d\'asta' };
    }
    // Copio: lo stato di giornata non deve sporcare il listone.
    const bloccati = new Set(indisponibili.map((n) => n.toLowerCase()));
    const copia = pool.map((g) => ({ ...g, stato: bloccati.has(g.nome.toLowerCase()) ? 'infortunato' : 'ok' }));
    try {
      const f = modulo ? costruisciFormazione(copia, modulo) : migliorFormazione(copia);
      return {
        modulo: f.modulo, totale_atteso: Number(f.totale.toFixed(2)),
        titolari: f.titolari.map((t) => ({ nome: t.giocatore.nome, ruolo: t.giocatore.ruolo,
                                           atteso: Number(t.atteso.toFixed(2)), origine: t.origine })),
        panchina: f.panchina.slice(0, 6).map((t) => ({ nome: t.giocatore.nome, ruolo: t.giocatore.ruolo,
                                                       atteso: Number(t.atteso.toFixed(2)) })),
        avvertenze: f.avvertenze,
      };
    } catch (e) { return { errore: e.message }; }
  }

  confronta_giocatori({ primo, secondo, avversario_primo = 3, avversario_secondo = 3,
                        in_casa_primo = true, in_casa_secondo = true }) {
    const a = this._risolvi(primo), b = this._risolvi(secondo);
    if (!a.giocatore || !b.giocatore) {
      return { serve_conferma: true, candidati_primo: a.candidati, candidati_secondo: b.candidati };
    }
    return confronta(a.giocatore, b.giocatore,
      { forzaAvversario: avversario_primo, inCasa: in_casa_primo },
      { forzaAvversario: avversario_secondo, inCasa: in_casa_secondo });
  }

  regolamento({ media_reparto } = {}) {
    if (media_reparto != null) {
      return { media_reparto, bonus_modificatore: modificatoreDifesa(media_reparto),
               nota: 'valori standard: verifica il regolamento della tua lega' };
    }
    return { bonus_malus: BONUS_MALUS,
             nota: 'impostazioni standard: assist, portiere imbattuto e modificatore possono '
                 + 'essere disattivati nella lega dell\'utente' };
  }

  /** Esegue lo strumento chiesto dal modello. Un errore qui non deve far cadere la telefonata. */
  esegui(nome, argomenti) {
    const metodo = this[nome];
    if (typeof metodo !== 'function' || nome.startsWith('_') || nome === 'esegui') {
      return { errore: `strumento sconosciuto: ${nome}` };
    }
    try { return metodo.call(this, argomenti || {}); }
    catch (e) { return { errore: `${e.name}: ${e.message}` }; }
  }
}

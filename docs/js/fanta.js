// Dominio fantacalcio: listone, motore d'asta, motore di formazione.
//
// Gli stessi calcoli della versione da computer, portati nel telefono. Girano
// qui e non nel modello perche' i numeri di un'asta devono essere esatti: il
// vincolo "crediti residui meno gli slot da riempire" non e' una cosa da
// stimare a mente mentre un banditore conta.

export const RUOLI = ['P', 'D', 'C', 'A'];
export const ROSA_STANDARD = { P: 3, D: 8, C: 8, A: 6 };
export const BUDGET_SPLIT_DEFAULT = { P: 0.07, D: 0.15, C: 0.30, A: 0.48 };

export const STRATEGIE = {
  equilibrata: { P: 0.07, D: 0.15, C: 0.30, A: 0.48 },
  modificatore: { P: 0.10, D: 0.24, C: 0.28, A: 0.38 },
  tre_top_attacco: { P: 0.05, D: 0.12, C: 0.25, A: 0.58 },
  centrocampo_forte: { P: 0.06, D: 0.14, C: 0.40, A: 0.40 },
};

// Quanta parte del budget di reparto va sul giocatore migliore, sul secondo, ecc.
export const PIANO_FASCE = {
  P: [0.70, 0.20, 0.10],
  D: [0.28, 0.20, 0.14, 0.12, 0.10, 0.07, 0.05, 0.04],
  C: [0.30, 0.22, 0.16, 0.11, 0.08, 0.06, 0.04, 0.03],
  A: [0.38, 0.26, 0.16, 0.10, 0.06, 0.04],
};

export const MODULI = {
  '3-4-3': [3, 4, 3], '3-5-2': [3, 5, 2], '4-3-3': [4, 3, 3], '4-4-2': [4, 4, 2],
  '4-5-1': [4, 5, 1], '5-3-2': [5, 3, 2], '5-4-1': [5, 4, 1],
};

export const BONUS_MALUS = {
  gol_segnato: 3, gol_subito_portiere: -1, rigore_segnato: 3, rigore_sbagliato: -3,
  rigore_parato: 3, autogol: -2, assist: 1, ammonizione: -0.5, espulsione: -1,
  portiere_imbattuto: 1,
};

export const MODIFICATORE_DIFESA = [
  [6.0, 6.24, 1], [6.25, 6.49, 2], [6.5, 6.74, 3],
  [6.75, 6.99, 4], [7.0, 7.24, 5], [7.25, 99, 6],
];

// ------------------------------------------------------------------ listone
/** Minuscolo, senza accenti, senza punteggiatura: la base di ogni confronto. */
export function normalizza(testo) {
  return String(testo || '')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/).filter(Boolean).join(' ');
}

/** Somiglianza fra stringhe (Dice sui bigrammi): tollera le storpiature. */
function somiglianza(a, b) {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const bigrammi = (s) => { const out = []; for (let i = 0; i < s.length - 1; i++) out.push(s.slice(i, i + 2)); return out; };
  const A = bigrammi(a), B = bigrammi(b);
  const conta = new Map();
  for (const g of A) conta.set(g, (conta.get(g) || 0) + 1);
  let comuni = 0;
  for (const g of B) { const n = conta.get(g) || 0; if (n > 0) { comuni++; conta.set(g, n - 1); } }
  return (2 * comuni) / (A.length + B.length);
}

const ALIAS = {
  name: ['nome', 'name', 'giocatore', 'calciatore'],
  team: ['squadra', 'team', 'club'],
  role: ['r', 'ruolo', 'role'],
  quotation: ['qt.a', 'qta', 'quotazione', 'quotazioneattuale', 'prezzo'],
  fvm: ['fvm', 'fantavalore'],
  fantamedia: ['fm', 'fantamedia'],
};

export class Listone {
  constructor(giocatori = []) {
    this.giocatori = giocatori;
    this.indice = new Map(giocatori.map((g) => [normalizza(g.nome), g]));
  }

  get length() { return this.giocatori.length; }

  /** Carica l'export ufficiale di Fantacalcio.it senza doverlo rimaneggiare. */
  static daCSV(testo) {
    const righe = testo.replace(/^﻿/, '').split(/\r?\n/).filter((r) => r.trim());
    if (!righe.length) throw new Error('il file e\' vuoto');
    const sep = (righe[0].match(/;/g) || []).length > (righe[0].match(/,/g) || []).length ? ';' : ',';
    const intestazioni = righe[0].split(sep).map((h) => h.trim().toLowerCase().replace(/[\s_]/g, ''));

    const colonna = {};
    for (const [campo, nomi] of Object.entries(ALIAS)) {
      const i = intestazioni.findIndex((h) => nomi.includes(h));
      if (i >= 0) colonna[campo] = i;
    }
    if (colonna.name === undefined) {
      throw new Error('non trovo la colonna con i nomi dei giocatori (attesa: Nome)');
    }

    const num = (v, def = 0) => {
      const n = parseFloat(String(v || '').replace(',', '.'));
      return Number.isFinite(n) ? n : def;
    };
    const giocatori = [];
    for (const riga of righe.slice(1)) {
      const c = riga.split(sep);
      const nome = (c[colonna.name] || '').trim();
      if (!nome) continue;
      const ruolo = (c[colonna.role] || '').trim().toUpperCase().slice(0, 1);
      giocatori.push({
        nome,
        squadra: (c[colonna.team] || '').trim().toUpperCase(),
        ruolo: RUOLI.includes(ruolo) ? ruolo : 'C',
        quotazione: num(c[colonna.quotation], 1) || 1,
        fvm: num(c[colonna.fvm]),
        fantamedia: colonna.fantamedia !== undefined && c[colonna.fantamedia]
          ? num(c[colonna.fantamedia], null) : null,
      });
    }
    if (!giocatori.length) throw new Error('nessun giocatore leggibile nel file');
    return new Listone(giocatori);
  }

  /**
   * Ricerca tollerante: la voce storpia i cognomi ("vlahovich" -> Vlahovic) e
   * chiedere all'utente di ripetere tre volte non e' un'opzione in asta.
   */
  cerca(query, limite = 3) {
    const ago = normalizza(query);
    if (!ago) return [];
    const risultati = [];
    for (const g of this.giocatori) {
      const pagliaio = normalizza(g.nome);
      let punteggio;
      if (pagliaio === ago) punteggio = 1;
      else if (pagliaio.startsWith(ago) || ago.startsWith(pagliaio)) punteggio = 0.95;
      else if (pagliaio.includes(ago) || ago.includes(pagliaio)) punteggio = 0.85;
      else punteggio = somiglianza(ago, pagliaio);
      if (punteggio >= 0.55) risultati.push({ giocatore: g, punteggio: Number(punteggio.toFixed(3)) });
    }
    risultati.sort((a, b) => b.punteggio - a.punteggio || b.giocatore.fvm - a.giocatore.fvm);
    return risultati.slice(0, limite);
  }

  get(nome) { return this.indice.get(normalizza(nome)) || null; }
  perRuolo(ruolo) { return this.giocatori.filter((g) => g.ruolo === String(ruolo).toUpperCase().slice(0, 1)); }
  migliori(ruolo, limite = 10) {
    const pool = ruolo ? this.perRuolo(ruolo) : this.giocatori.slice();
    return pool.sort((a, b) => b.fvm - a.fvm || b.quotazione - a.quotazione).slice(0, limite);
  }
  toJSON() { return this.giocatori; }
}

// --------------------------------------------------------------- asta
export class Asta {
  constructor({ budget = 500, slots = ROSA_STANDARD, split = BUDGET_SPLIT_DEFAULT,
                riferimentoListone = 500 } = {}) {
    this.budget = budget;
    this.slots = { ...slots };
    this.split = { ...split };
    this.riferimentoListone = riferimentoListone;
    this.rosa = [];
  }

  contaRuolo(r) { return this.rosa.filter((s) => s.giocatore.ruolo === r).length; }
  mancanti(r) { return Math.max(0, (this.slots[r] || 0) - this.contaRuolo(r)); }
  get slotMancanti() { return RUOLI.reduce((n, r) => n + this.mancanti(r), 0); }
  get speso() { return this.rosa.reduce((n, s) => n + s.prezzo, 0); }
  spesoRuolo(r) { return this.rosa.filter((s) => s.giocatore.ruolo === r).reduce((n, s) => n + s.prezzo, 0); }
  get creditiResidui() { return this.budget - this.speso; }

  /**
   * Il vincolo duro: il massimo offribile lasciando un credito per ogni altro
   * slot ancora da riempire. Superarlo significa non poter completare la rosa.
   */
  massimoOffribile() {
    if (this.slotMancanti <= 0) return 0;
    return Math.max(1, this.creditiResidui - (this.slotMancanti - 1));
  }

  budgetRuolo(r) { return Math.round(this.budget * (this.split[r] || 0)); }
  budgetRuoloResiduo(r) { return this.budgetRuolo(r) - this.spesoRuolo(r); }

  /** Prezzo di riferimento del PROSSIMO slot di quel reparto. */
  prezzoProssimoSlot(r) {
    const fasce = PIANO_FASCE[r] || [];
    const presi = this.contaRuolo(r);
    if (!fasce.length || presi >= fasce.length) {
      return Math.max(1, Math.floor(this.budgetRuoloResiduo(r) / Math.max(1, this.mancanti(r) || 1)));
    }
    return Math.max(1, Math.round(this.budgetRuolo(r) * fasce[presi]));
  }

  /** Valore del giocatore riscalato sul MIO budget: 60 su 500 valgono 30 su 250. */
  valore(g) {
    const scala = this.budget / Math.max(1, this.riferimentoListone);
    const base = g.quotazione > 1 ? g.quotazione : Math.max(g.fvm / 10, 1);
    return Math.max(1, Math.round(base * scala));
  }

  consiglio(g, { offertaAttuale = 0, quantoLoVoglio = 1 } = {}) {
    const r = g.ruolo;
    const valore = this.valore(g);
    const limite = this.massimoOffribile();
    const reparto = this.budgetRuoloResiduo(r);
    const obiettivo = this.prezzoProssimoSlot(r);

    if (this.mancanti(r) === 0) {
      return { giocatore: g.nome, ruolo: r, valore_stimato: valore, offerta_massima: 0,
               limite_assoluto: limite, verdetto: 'lascia',
               motivo: `gli slot ${r} sono gia' completi: ogni credito qui e' sprecato` };
    }

    let tetto = Math.round(Math.max(valore, obiettivo) * quantoLoVoglio);
    tetto = Math.min(tetto, Math.max(reparto, obiettivo));
    tetto = Math.max(1, Math.min(tetto, limite));

    let verdetto, motivo;
    if (offertaAttuale && offertaAttuale >= tetto) {
      verdetto = 'lascia';
      motivo = `a ${offertaAttuale} sei oltre il tuo tetto di ${tetto}: con ${this.creditiResidui} crediti e ${this.slotMancanti} slot non conviene`;
    } else if (offertaAttuale && offertaAttuale <= Math.floor(tetto * 0.6)) {
      verdetto = 'affare';
      motivo = `a ${offertaAttuale} paghi molto sotto il tetto di ${tetto}: rilancia`;
    } else if (tetto >= valore * 1.15) {
      verdetto = 'prendi';
      motivo = `puoi arrivare a ${tetto} restando dentro il piano del reparto ${r}`;
    } else {
      verdetto = 'prezzo giusto';
      motivo = `il tetto sensato e' ${tetto}; oltre stai pagando la fretta, non il giocatore`;
    }
    return { giocatore: g.nome, ruolo: r, valore_stimato: valore, offerta_massima: tetto,
             limite_assoluto: limite, budget_reparto_residuo: reparto, verdetto, motivo };
  }

  compra(g, prezzo) {
    prezzo = Math.round(prezzo);
    if (this.rosa.some((s) => normalizza(s.giocatore.nome) === normalizza(g.nome))) {
      throw new Error(`${g.nome} e' gia' in rosa`);
    }
    if (this.mancanti(g.ruolo) === 0) throw new Error(`slot ${g.ruolo} gia' completi`);
    if (prezzo > this.creditiResidui) {
      throw new Error(`${prezzo} crediti ma ne hai ${this.creditiResidui}`);
    }
    if (prezzo > this.massimoOffribile()) {
      throw new Error(`a ${prezzo} non riusciresti a completare la rosa (massimo ora: ${this.massimoOffribile()})`);
    }
    this.rosa.push({ giocatore: g, prezzo });
    return this.stato();
  }

  annulla(nome) {
    const i = this.rosa.findIndex((s) => normalizza(s.giocatore.nome) === normalizza(nome));
    if (i < 0) throw new Error(`${nome} non risulta in rosa`);
    this.rosa.splice(i, 1);
    return this.stato();
  }

  stato() {
    const reparti = {};
    for (const r of RUOLI) {
      reparti[r] = {
        presi: this.contaRuolo(r), mancanti: this.mancanti(r), spesi: this.spesoRuolo(r),
        budget_reparto: this.budgetRuolo(r), residuo_reparto: this.budgetRuoloResiduo(r),
        prezzo_prossimo_slot: this.prezzoProssimoSlot(r),
      };
    }
    return {
      budget: this.budget, crediti_residui: this.creditiResidui, slot_mancanti: this.slotMancanti,
      massimo_offribile_ora: this.massimoOffribile(),
      media_per_slot_residuo: this.slotMancanti
        ? Number((this.creditiResidui / this.slotMancanti).toFixed(1)) : 0,
      reparti,
      rosa: this.rosa.map((s) => ({ nome: s.giocatore.nome, ruolo: s.giocatore.ruolo,
                                    squadra: s.giocatore.squadra, prezzo: s.prezzo })),
    };
  }

  piano() {
    const out = {};
    for (const r of RUOLI) {
      out[r] = {
        budget_reparto: this.budgetRuolo(r), slot: this.slots[r],
        prezzi_obiettivo: (PIANO_FASCE[r] || []).slice(0, this.slots[r])
          .map((f) => Math.max(1, Math.round(this.budgetRuolo(r) * f))),
      };
    }
    return out;
  }

  toJSON() { return { budget: this.budget, slots: this.slots, split: this.split, rosa: this.rosa }; }

  static fromJSON(d) {
    if (!d) return new Asta();
    const a = new Asta({ budget: d.budget, slots: d.slots, split: d.split });
    a.rosa = Array.isArray(d.rosa) ? d.rosa : [];
    return a;
  }
}

// ---------------------------------------------------------- formazione
const W_TITOLARE = 2.2, W_AVVERSARIO = 0.3, W_CASA = 0.15, W_RIGORISTA = 0.45;

/** Fantamedia di partenza, e da dove viene. */
export function baseAttesa(g) {
  if (g.fantamedia != null) return { base: g.fantamedia, origine: 'storica' };
  // Il mercato non e' un oracolo, ma un giocatore da 40 rende sistematicamente
  // piu' di uno da 5: ignorarlo significherebbe trattarli come identici.
  const q = Math.max(g.quotazione || 1, (g.fvm || 0) / 10, 1);
  return { base: Math.min(5.6 + 0.95 * Math.log1p(q / 10), 8.5), origine: 'stimata dalla quotazione' };
}

export function punteggioAtteso(g, ctx = {}) {
  const { base, origine } = baseAttesa(g);
  if (g.stato === 'infortunato' || g.stato === 'squalificato') {
    return { giocatore: g, atteso: 0, escluso: g.stato, origine };
  }
  const prob = Math.min(Math.max(g.probabilitaTitolare ?? 0.8, 0), 1);
  const dettaglio = {
    base,
    avversario: W_AVVERSARIO * (3 - (ctx.forzaAvversario ?? 3)),
    campo: (ctx.inCasa ?? true) ? W_CASA : -W_CASA,
    rigorista: g.rigorista ? W_RIGORISTA : 0,
    titolarita: -W_TITOLARE * (1 - prob),   // la certezza di giocare domina tutto
  };
  const atteso = Math.max(0, Object.values(dettaglio).reduce((a, b) => a + b, 0));
  return { giocatore: g, atteso, dettaglio, escluso: null, origine };
}

export function costruisciFormazione(giocatori, modulo, contesti = {}) {
  if (!MODULI[modulo]) throw new Error(`modulo non riconosciuto: ${modulo}`);
  const [nD, nC, nA] = MODULI[modulo];
  const valutati = giocatori.map((g) => punteggioAtteso(g, contesti[g.nome]));
  const disponibili = valutati.filter((v) => !v.escluso);
  const avvertenze = valutati.filter((v) => v.escluso)
    .map((v) => `${v.giocatore.nome} indisponibile (${v.escluso})`);

  const titolari = [], panchina = [];
  for (const [ruolo, quanti] of [['P', 1], ['D', nD], ['C', nC], ['A', nA]]) {
    const pool = disponibili.filter((v) => v.giocatore.ruolo === ruolo)
      .sort((a, b) => b.atteso - a.atteso);
    if (pool.length < quanti) {
      avvertenze.push(`servono ${quanti} giocatori di ruolo ${ruolo} ma ne hai ${pool.length}`);
    }
    titolari.push(...pool.slice(0, quanti));
    panchina.push(...pool.slice(quanti));
  }
  for (const t of titolari) {
    const p = t.giocatore.probabilitaTitolare;
    if (p != null && p < 0.6) {
      avvertenze.push(`${t.giocatore.nome} e' schierato ma la titolarita' e' incerta (${Math.round(p * 100)}%)`);
    }
  }
  panchina.sort((a, b) => b.atteso - a.atteso);
  return {
    modulo, titolari, panchina, avvertenze,
    totale: titolari.reduce((n, t) => n + t.atteso, 0),
  };
}

/** Il modulo si sceglie DOPO aver visto chi gioca, non prima. */
export function migliorFormazione(giocatori, contesti = {}) {
  const candidate = [];
  for (const modulo of Object.keys(MODULI)) {
    try {
      const f = costruisciFormazione(giocatori, modulo, contesti);
      if (!f.avvertenze.some((a) => a.startsWith('servono'))) candidate.push(f);
    } catch { /* modulo non copribile */ }
  }
  if (!candidate.length) {
    throw new Error('nessun modulo copribile con questi giocatori: controlla ruoli e indisponibili');
  }
  return candidate.reduce((a, b) => (b.totale > a.totale ? b : a));
}

export function confronta(a, b, ctxA = {}, ctxB = {}) {
  const sa = punteggioAtteso(a, ctxA), sb = punteggioAtteso(b, ctxB);
  const [vince, perde] = sa.atteso >= sb.atteso ? [sa, sb] : [sb, sa];
  const distacco = vince.atteso - perde.atteso;

  let motivo;
  if (!vince.escluso && perde.escluso) {
    motivo = `${perde.giocatore.nome} e' ${perde.escluso}: non e' una scelta`;
  } else if (distacco < 0.15) {
    motivo = 'sostanzialmente equivalenti: decidi con l\'avversario piu\' morbido';
  } else {
    const etichette = {
      base: 'rende di piu\' sul lungo periodo', titolarita: 'e\' piu\' sicuro di scendere in campo',
      avversario: 'ha l\'avversario piu\' abbordabile', campo: 'gioca in casa',
      rigorista: 'tira i rigori',
    };
    let chiave = 'base', max = -Infinity;
    for (const k of Object.keys(etichette)) {
      const d = Math.abs((vince.dettaglio?.[k] ?? 0) - (perde.dettaglio?.[k] ?? 0));
      if (d > max) { max = d; chiave = k; }
    }
    motivo = `${vince.giocatore.nome} ${etichette[chiave]}`;
  }
  return { scelta: vince.giocatore.nome, distacco: Number(distacco.toFixed(2)), motivo };
}

export function modificatoreDifesa(media) {
  for (const [lo, hi, bonus] of MODIFICATORE_DIFESA) if (media >= lo && media <= hi) return bonus;
  return 0;
}

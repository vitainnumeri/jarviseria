// Il cervello offline: capisce cosa hai chiesto e risponde, senza rete.
//
// Non e' un modello linguistico: e' un riconoscitore di intenzioni piu' i
// motori di calcolo. Il compromesso e' esplicito e va conosciuto:
//
//   quello che perdi   la conversazione libera. Non discute, non ragiona su
//                      quello che non e' previsto, non capisce le frasi
//                      storte. Se non riconosce l'intenzione lo dice.
//
//   quello che guadagni gratis per sempre, funziona senza rete e senza
//                      account, e i numeri d'asta sono aritmetica esatta -
//                      il tetto d'offerta non e' una stima ma un vincolo.
//
// In asta le domande sono poche e sempre le stesse ("quanto posso offrire",
// "preso a tot", "quanto mi resta"), quindi la copertura e' alta proprio dove
// serve.

import { normalizza } from './fanta.js';
import { estraiNumero, numeroInParola } from './numeri.js';

const RUOLI_PAROLA = {
  portiere: 'P', portieri: 'P', porta: 'P',
  difensore: 'D', difensori: 'D', difesa: 'D',
  centrocampista: 'C', centrocampisti: 'C', centrocampo: 'C',
  attaccante: 'A', attaccanti: 'A', attacco: 'A', punta: 'A', punte: 'A',
};

/** Toglie le parole di contorno per isolare il nome del giocatore. */
function ripulisciNome(testo) {
  return testo
    .replace(/\b(per|il|lo|la|un|uno|una|di|del|della|su|a|ad|da|con|che|mi|conviene|vale|prendo|prendere|offrire|spingere|arrivare|pagare|quanto|posso|devo|puo|posso)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const INTENZIONI = [
  {
    nome: 'acquisto',
    // "preso lautaro a 180", "aggiudicato dimarco a centoventi"
    prova: (t) => /\b(preso|presa|aggiudicat[oa]|comprat[oa]|mio|acquistat[oa])\b/.test(t)
                  && estraiNumero(t) !== null,
    estrai: (t) => {
      const prezzo = estraiNumero(t);
      const senza = t.replace(/\b(preso|presa|aggiudicat[oa]|comprat[oa]|mio|acquistat[oa])\b/g, ' ')
        .replace(/\bper\b|\ba\b|\bcrediti?\b/g, ' ')
        .replace(/\d+/g, ' ');
      return { nome: ripulisciNome(senza), prezzo };
    },
  },
  {
    nome: 'annulla',
    prova: (t) => /\b(annulla|annullare|togli|togliere|cancella|rimuovi|sbagliat[oa])\b/.test(t),
    estrai: (t) => ({ nome: ripulisciNome(
      t.replace(/\b(annulla|annullare|togli|togliere|cancella|rimuovi|sbagliat[oa]|dalla|rosa)\b/g, ' ')) }),
  },
  {
    nome: 'confronto',
    // "meglio lautaro o vlahovic", "chi schiero fra dimarco e bastoni"
    prova: (t) => /\b(meglio|preferisci|chi (schiero|metto|gioco))\b/.test(t)
                  && /\b(o|oppure|contro|e)\b/.test(t),
    estrai: (t) => {
      const pulito = t.replace(/\b(meglio|preferisci|chi|schiero|metto|gioco|fra|tra|il|lo|la)\b/g, ' ');
      const parti = pulito.split(/\s+\b(?:o|oppure|contro|e)\b\s+/);
      return parti.length >= 2
        ? { primo: parti[0].trim(), secondo: parti[1].trim() }
        : null;
    },
  },
  {
    nome: 'formazione',
    prova: (t) => /\b(formazione|schieramento|modulo|chi schiero|come gioco|undici)\b/.test(t),
    estrai: () => ({}),
  },
  {
    nome: 'piano',
    prova: (t) => /\b(piano|come divido|come spartisco|quanto spendo per|strategia|ripartizione)\b/.test(t),
    estrai: (t) => {
      const s = /\b(modificatore|tre top|centrocampo forte|equilibrat[ao])\b/.exec(t);
      const mappa = { modificatore: 'modificatore', 'tre top': 'tre_top_attacco',
                      'centrocampo forte': 'centrocampo_forte', equilibrata: 'equilibrata',
                      equilibrato: 'equilibrata' };
      return { strategia: s ? mappa[s[1]] : null };
    },
  },
  {
    nome: 'stato',
    prova: (t) => /\b(quanto mi resta|quanti crediti|crediti (mi )?(restano|rimasti)|situazione|come sto|come sono messo|budget|(la )?mia rosa|riepilogo)\b/.test(t),
    estrai: () => ({}),
  },
  {
    nome: 'migliori',
    prova: (t) => /\b(migliori|top|piu forti|meglio quotati)\b/.test(t)
                  && Object.keys(RUOLI_PAROLA).some((r) => t.includes(r)),
    estrai: (t) => {
      const parola = Object.keys(RUOLI_PAROLA).find((r) => t.includes(r));
      return { ruolo: RUOLI_PAROLA[parola], limite: 3 };
    },
  },
  {
    nome: 'regolamento',
    prova: (t) => /\b(bonus|malus|quanto vale un gol|modificatore di difesa|regole|regolamento|punteggio)\b/.test(t),
    estrai: (t) => ({ media_reparto: /\bmodificatore\b/.test(t) ? estraiNumero(t) : null }),
  },
  {
    nome: 'offerta',
    // L'ultima della lista: e' la piu' generica e prenderebbe tutto.
    prova: (t) => /\b(quanto|prezzo|vale|offr|spinger|arrivare|pagare|conviene|massimo|tetto)\b/.test(t),
    estrai: (t) => {
      const offerta = /\b(siamo a|sta a|e a|arrivat[oa] a|ora a)\b/.test(t) ? estraiNumero(t) : 0;
      const senza = t.replace(/\d+/g, ' ')
        .replace(/\b(siamo|sta|arrivat[oa]|ora|crediti?|massimo|tetto|prezzo|conviene|offrire|spingere|arrivare|pagare)\b/g, ' ');
      return { nome: ripulisciNome(senza), offertaAttuale: offerta || 0 };
    },
  },
];

/** Riconosce l'intenzione di una frase. Null se non ne trova nessuna. */
export function riconosci(testo) {
  const t = normalizza(testo);
  if (!t) return null;
  for (const intenzione of INTENZIONI) {
    if (!intenzione.prova(t)) continue;
    const dati = intenzione.estrai(t);
    if (dati === null) continue;
    return { intenzione: intenzione.nome, ...dati, testo: t };
  }
  return null;
}

// -------------------------------------------------------------- risposte
const euro = (n) => numeroInParola(n);
const NOMI_RUOLO = { P: 'portieri', D: 'difensori', C: 'centrocampisti', A: 'attaccanti' };

/**
 * Il cervello: capisce, calcola, e formula la frase da dire.
 *
 * Le risposte sono scritte per essere ASCOLTATE, non lette: corte, il numero
 * per primo, la ragione dopo, e i prezzi in lettere perche' la voce sintetica
 * li scandisca bene.
 */
export class Cervello {
  constructor(strumenti) { this.strumenti = strumenti; }

  ascolta(testo) {
    const capito = riconosci(testo);
    if (!capito) {
      return { risposta: 'Non ho capito. Puoi chiedermi quanto offrire per un giocatore, '
                       + 'dirmi chi hai preso e a quanto, o chiedere quanto ti resta.',
               intenzione: null };
    }
    const metodo = this[`_${capito.intenzione}`];
    const risposta = metodo.call(this, capito);
    return { risposta, intenzione: capito.intenzione, dati: capito };
  }

  _conferma(candidati) {
    const nomi = candidati.slice(0, 2).map((c) => c.nome);
    return nomi.length > 1
      ? `Intendi ${nomi[0]} o ${nomi[1]}?`
      : `Intendi ${nomi[0]}?`;
  }

  _offerta({ nome, offertaAttuale }) {
    if (!nome) return 'Per quale giocatore?';
    const esito = this.strumenti.esegui('consiglio_offerta',
      { nome, offerta_attuale: offertaAttuale });
    if (esito.errore) return `Non trovo ${nome} nel listone.`;
    if (esito.serve_conferma) return this._conferma(esito.candidati);

    const tetto = euro(esito.offerta_massima);
    if (esito.verdetto === 'lascia' && esito.offerta_massima === 0) {
      return `Lascia perdere: i ${NOMI_RUOLO[esito.ruolo]} li hai gia' completi.`;
    }
    if (esito.verdetto === 'lascia') {
      return `Lascia. Il tuo tetto e' ${tetto}, oltre resti scoperto.`;
    }
    if (esito.verdetto === 'affare') {
      return `Rilancia: puoi arrivare a ${tetto} e stai pagando molto meno.`;
    }
    const residui = euro(esito.crediti_residui);
    return `Fino a ${tetto}. Ti restano ${residui} crediti e `
         + `${euro(esito.slot_mancanti)} slot da riempire.`;
  }

  _acquisto({ nome, prezzo }) {
    if (!nome) return 'Chi hai preso?';
    const esito = this.strumenti.esegui('registra_acquisto', { nome, prezzo });
    if (esito.serve_conferma) return this._conferma(esito.candidati);
    if (esito.errore) return `Non posso: ${esito.errore}.`;
    const mancanti = esito.slot_mancanti;
    return `Segnato. Ti restano ${euro(esito.crediti_residui)} crediti `
         + `per ${euro(mancanti)} giocatori, cioe' ${euro(Math.floor(esito.crediti_residui / Math.max(mancanti, 1)))} a testa.`;
  }

  _annulla({ nome }) {
    if (!nome) return 'Quale giocatore devo togliere?';
    const esito = this.strumenti.esegui('annulla_acquisto', { nome });
    if (esito.errore) return `${nome} non risulta in rosa.`;
    return `Tolto. Sei di nuovo a ${euro(esito.crediti_residui)} crediti.`;
  }

  _stato() {
    const s = this.strumenti.esegui('stato_asta', {});
    if (!s.rosa.length) {
      return `Non hai ancora preso nessuno. Hai ${euro(s.budget)} crediti per venticinque giocatori.`;
    }
    const vuoti = Object.entries(s.reparti).filter(([, r]) => r.mancanti > 0)
      .map(([ruolo, r]) => `${euro(r.mancanti)} ${NOMI_RUOLO[ruolo]}`);
    return `Hai ${euro(s.crediti_residui)} crediti e ${euro(s.slot_mancanti)} slot. `
         + `Ti mancano ${vuoti.slice(0, 3).join(', ')}. `
         + `Il massimo che puoi offrire adesso e' ${euro(s.massimo_offribile_ora)}.`;
  }

  _piano({ strategia }) {
    const esito = this.strumenti.esegui('piano_asta', strategia ? { strategia } : {});
    if (esito.errore) return esito.errore;
    const p = esito.piano;
    return `Con questa ripartizione: ${euro(p.P.budget_reparto)} in porta, `
         + `${euro(p.D.budget_reparto)} in difesa, ${euro(p.C.budget_reparto)} a centrocampo, `
         + `${euro(p.A.budget_reparto)} in attacco. `
         + `Il primo attaccante puntalo a ${euro(p.A.prezzi_obiettivo[0])}.`;
  }

  _migliori({ ruolo, limite }) {
    const esito = this.strumenti.esegui('migliori_per_ruolo', { ruolo, limite });
    if (esito.errore) return 'Non ho il listone caricato, quindi non ho le quotazioni.';
    if (!esito.giocatori.length) return `Non trovo ${NOMI_RUOLO[ruolo]} nel listone.`;
    const nomi = esito.giocatori.map((g) => `${g.nome} a ${euro(Math.round(g.quotazione))}`);
    return `I piu' quotati: ${nomi.join(', ')}.`;
  }

  _confronto({ primo, secondo }) {
    const esito = this.strumenti.esegui('confronta_giocatori', { primo, secondo });
    if (esito.serve_conferma) return 'Non ho riconosciuto i nomi. Ripetimeli uno alla volta.';
    if (esito.errore) return esito.errore;
    if (/equivalenti/.test(esito.motivo)) {
      return 'Sono equivalenti, scegli tu: guarda chi ha l\'avversario piu\' morbido.';
    }
    return `${esito.scelta}. ${esito.motivo}.`;
  }

  _formazione() {
    const esito = this.strumenti.esegui('costruisci_formazione', {});
    if (esito.errore) return `Non posso: ${esito.errore}.`;
    const reparti = { D: [], C: [], A: [] };
    let portiere = '';
    for (const t of esito.titolari) {
      if (t.ruolo === 'P') portiere = t.nome; else reparti[t.ruolo]?.push(t.nome);
    }
    return `Modulo ${esito.modulo}. In porta ${portiere}. `
         + `Dietro ${reparti.D.join(', ')}. A centrocampo ${reparti.C.join(', ')}. `
         + `Davanti ${reparti.A.join(', ')}.`;
  }

  _regolamento({ media_reparto }) {
    const esito = this.strumenti.esegui('regolamento',
      media_reparto ? { media_reparto } : {});
    if (esito.bonus_modificatore !== undefined) {
      return `Con quella media prendi ${euro(esito.bonus_modificatore)} punti di modificatore.`;
    }
    return 'Gol tre punti, rigore sbagliato meno tre, assist uno, ammonizione meno mezzo, '
         + 'espulsione meno uno. Ma controlla il regolamento della tua lega.';
  }
}

export const ESEMPI = [
  'Quanto posso offrire per Lautaro?',
  'Preso Dimarco a centoventi',
  'Quanto mi resta?',
  'Meglio Lautaro o Vlahovic?',
  'I migliori attaccanti',
  'Fammi la formazione',
];

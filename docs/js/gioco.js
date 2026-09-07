// Il motore del gioco: solo stato e regole, nessun DOM.
//
// Lo stato e' un oggetto semplice, sempre serializzabile in JSON: cosi' la
// partita sopravvive a una ricarica della pagina e la logica si puo' provare
// senza browser.
//
// Un round si svolge in quattro tempi:
//   1. il telefono passa a chi da' l'indizio, che vede il bersaglio;
//   2. quello scrive la parola o la frase;
//   3. il telefono gira: ognuno degli altri segna il suo punto senza vedere
//      ne' il bersaglio ne' i tiri di chi lo ha preceduto;
//   4. si scopre tutto e si contano i punti.

import { COPPIE } from './coppie.js';

export const VERSIONE = 1;
export const MIN_GIOCATORI = 3;
export const MAX_GIOCATORI = 12;

// Il bersaglio non finisce mai a ridosso degli estremi: un indizio da 0 o da
// 100 e' troppo facile da dare e da indovinare.
const MARGINE = 5;

// Quanto vale un tiro, in base a quanto dista dal bersaglio sulla scala 0-100.
const FASCE = [
  { entro: 4, punti: 5, esito: 'In pieno' },
  { entro: 9, punti: 4, esito: 'Vicinissimo' },
  { entro: 16, punti: 3, esito: 'Ci siamo' },
  { entro: 25, punti: 2, esito: 'Nella zona' },
  { entro: 36, punti: 1, esito: 'Lontanuccio' },
];
const FUORI = { punti: 0, esito: 'Fuori strada' };

export const FASCE_PUNTEGGIO = FASCE.map(f => ({ ...f }));

/** Punti e commento per una distanza sulla scala 0-100. */
export function valuta(distanza) {
  const fascia = FASCE.find(f => distanza <= f.entro) || FUORI;
  return { punti: fascia.punti, esito: fascia.esito };
}

function mescola(lista, casuale) {
  const copia = lista.slice();
  for (let i = copia.length - 1; i > 0; i--) {
    const j = Math.floor(casuale() * (i + 1));
    [copia[i], copia[j]] = [copia[j], copia[i]];
  }
  return copia;
}

function nuovoMazzo(casuale) {
  return mescola(COPPIE.map((_, i) => i), casuale);
}

/**
 * Comincia una partita.
 * @param {string[]} nomi           i giocatori, nell'ordine in cui siedono
 * @param {number}   giri           quante volte ciascuno da' l'indizio
 * @param {function} casuale        sorgente casuale, iniettabile per i test
 */
export function nuovaPartita(nomi, giri = 2, casuale = Math.random) {
  const puliti = nomi.map(n => n.trim()).filter(Boolean);
  if (puliti.length < MIN_GIOCATORI) {
    throw new Error(`Servono almeno ${MIN_GIOCATORI} giocatori.`);
  }
  if (puliti.length > MAX_GIOCATORI) {
    throw new Error(`Non si può giocare in più di ${MAX_GIOCATORI}.`);
  }

  const stato = {
    versione: VERSIONE,
    giocatori: puliti.map(nome => ({ nome, punti: 0 })),
    giri,
    roundTotali: giri * puliti.length,
    roundNumero: 0,
    mazzo: nuovoMazzo(casuale),
    pescate: 0,
    round: null,
    storico: [],
    fase: 'passaggio-indizio',
  };
  apparecchiaRound(stato, casuale);
  return stato;
}

/** Prepara il round successivo: carta, bersaglio, turni. */
function apparecchiaRound(stato, casuale = Math.random) {
  if (stato.pescate >= stato.mazzo.length) {
    stato.mazzo = nuovoMazzo(casuale);
    stato.pescate = 0;
  }
  const [alto, basso] = COPPIE[stato.mazzo[stato.pescate]];
  stato.pescate += 1;
  stato.roundNumero += 1;

  const totale = stato.giocatori.length;
  const indizio = (stato.roundNumero - 1) % totale;
  // Gli altri tirano in ordine di posto, partendo da chi siede dopo.
  const ordine = [];
  for (let k = 1; k < totale; k++) ordine.push((indizio + k) % totale);

  stato.round = {
    coppia: { alto, basso },
    bersaglio: MARGINE + Math.round(casuale() * (100 - 2 * MARGINE)),
    indizio,
    testoIndizio: '',
    ordine,
    cursore: 0,
    tiri: {},
    esiti: null,
  };
  stato.fase = 'passaggio-indizio';
  return stato;
}

/** Chi deve avere il telefono in mano adesso. */
export function diTurno(stato) {
  const r = stato.round;
  if (!r) return null;
  if (stato.fase === 'passaggio-indizio' || stato.fase === 'indizio') {
    return { indice: r.indizio, ...stato.giocatori[r.indizio], ruolo: 'indizio' };
  }
  if (stato.fase === 'passaggio-tiro' || stato.fase === 'tiro') {
    const indice = r.ordine[r.cursore];
    return { indice, ...stato.giocatori[indice], ruolo: 'tiro' };
  }
  return null;
}

/** Il giocatore ha preso il telefono: si scopre la schermata del suo turno. */
export function prendiTelefono(stato) {
  if (stato.fase === 'passaggio-indizio') stato.fase = 'indizio';
  else if (stato.fase === 'passaggio-tiro') stato.fase = 'tiro';
  return stato;
}

/** L'indizio e' stato detto ad alta voce: si comincia a girare il telefono. */
export function confermaIndizio(stato, testo) {
  const pulito = String(testo || '').trim();
  if (!pulito) throw new Error('Scrivi la parola o la frase.');
  stato.round.testoIndizio = pulito;
  stato.fase = 'passaggio-tiro';
  return stato;
}

/** Registra il tiro di chi ha il telefono e passa al prossimo. */
export function confermaTiro(stato, valore) {
  const r = stato.round;
  const indice = r.ordine[r.cursore];
  r.tiri[indice] = Math.min(100, Math.max(0, Math.round(valore)));
  r.cursore += 1;
  if (r.cursore >= r.ordine.length) chiudiRound(stato);
  else stato.fase = 'passaggio-tiro';
  return stato;
}

/** Conta i punti del round e li somma alla classifica. */
function chiudiRound(stato) {
  const r = stato.round;
  const esiti = r.ordine.map(indice => {
    const valore = r.tiri[indice];
    const distanza = Math.abs(valore - r.bersaglio);
    const { punti, esito } = valuta(distanza);
    return { indice, nome: stato.giocatori[indice].nome, valore, distanza, punti, esito };
  });

  // Chi da' l'indizio vale quanto e' riuscito a farsi capire: la media di chi
  // lo ha ascoltato.
  const media = esiti.reduce((s, e) => s + e.punti, 0) / esiti.length;
  const puntiIndizio = Math.round(media);

  for (const e of esiti) stato.giocatori[e.indice].punti += e.punti;
  stato.giocatori[r.indizio].punti += puntiIndizio;

  r.esiti = esiti;
  r.puntiIndizio = puntiIndizio;
  stato.fase = 'rivelazione';
  return stato;
}

/** Dalla rivelazione alla classifica, e poi al round dopo (o alla fine). */
export function prossimo(stato, casuale = Math.random) {
  if (stato.fase === 'rivelazione') {
    stato.fase = 'classifica';
    return stato;
  }
  if (stato.fase !== 'classifica') return stato;

  stato.storico.push({
    numero: stato.roundNumero,
    coppia: stato.round.coppia,
    bersaglio: stato.round.bersaglio,
    indizio: stato.giocatori[stato.round.indizio].nome,
    testoIndizio: stato.round.testoIndizio,
    esiti: stato.round.esiti,
    puntiIndizio: stato.round.puntiIndizio,
  });

  if (stato.roundNumero >= stato.roundTotali) {
    stato.fase = 'fine';
    return stato;
  }
  return apparecchiaRound(stato, casuale);
}

/** La classifica, dal primo all'ultimo, con i pari merito allo stesso posto. */
export function classifica(stato) {
  const righe = stato.giocatori
    .map((g, indice) => ({ indice, nome: g.nome, punti: g.punti }))
    .sort((a, b) => b.punti - a.punti || a.indice - b.indice);
  let posto = 0;
  let precedente = null;
  return righe.map((riga, i) => {
    if (riga.punti !== precedente) { posto = i + 1; precedente = riga.punti; }
    return { ...riga, posto };
  });
}

/** Il giro in corso, 1-based, per la barra in alto. */
export function giroCorrente(stato) {
  return Math.floor((stato.roundNumero - 1) / stato.giocatori.length) + 1;
}

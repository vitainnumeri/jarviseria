// Test del cervello offline: capire la frase e rispondere con i numeri giusti.

import assert from 'node:assert/strict';
import test from 'node:test';

import { Cervello, riconosci } from '../docs/js/cervello.js';
import { Asta, Listone } from '../docs/js/fanta.js';
import { Strumenti } from '../docs/js/strumenti.js';
import { estraiNumero, numeroInParola, parolaInNumero } from '../docs/js/numeri.js';

const GIOCATORI = [
  { nome: 'Lautaro Martinez', ruolo: 'A', squadra: 'INT', quotazione: 42, fvm: 520, fantamedia: null },
  { nome: 'Vlahovic', ruolo: 'A', squadra: 'JUV', quotazione: 36, fvm: 440, fantamedia: null },
  { nome: 'Leao', ruolo: 'A', squadra: 'MIL', quotazione: 37, fvm: 450, fantamedia: null },
  { nome: 'Dimarco', ruolo: 'D', squadra: 'INT', quotazione: 22, fvm: 260, fantamedia: null },
  { nome: 'Bastoni', ruolo: 'D', squadra: 'INT', quotazione: 18, fvm: 210, fantamedia: null },
  { nome: 'Maignan', ruolo: 'P', squadra: 'MIL', quotazione: 16, fvm: 180, fantamedia: null },
  { nome: 'Barella', ruolo: 'C', squadra: 'INT', quotazione: 24, fvm: 280, fantamedia: null },
];

const nuovo = (budget = 500) =>
  new Cervello(new Strumenti(new Listone(GIOCATORI), new Asta({ budget })));

// ------------------------------------------------------------- numeri

test('capisce i prezzi detti in lettere', () => {
  for (const [parola, atteso] of [['centoventi', 120], ['centottanta', 180],
                                  ['duecentocinquanta', 250], ['trentatre', 33],
                                  ['ventuno', 21], ['novecentonovantanove', 999]]) {
    assert.equal(parolaInNumero(parola), atteso, parola);
  }
});

test('l' + "'elisione di cento non lo confonde", () => {
  // "centottanta", non "centoottanta": serve tornare sui propri passi
  assert.equal(parolaInNumero('centottanta'), 180);
  assert.equal(parolaInNumero('centotto'), 108);
});

test('una parola che non e' + "' un numero resta null", () => {
  assert.equal(parolaInNumero('lautaro'), null);
  assert.equal(estraiNumero('ciao come stai'), null);
});

test('le cifre hanno la precedenza sulle parole', () => {
  assert.equal(estraiNumero('preso a 180'), 180);
  assert.equal(estraiNumero('preso a centoventi'), 120);
});

test('i numeri tornano in lettere per la voce sintetica', () => {
  for (const [n, atteso] of [[5, 'cinque'], [21, 'ventuno'], [28, 'ventotto'],
                             [180, 'centottanta'], [250, 'duecentocinquanta'], [1000, 'mille']]) {
    assert.equal(numeroInParola(n), atteso, String(n));
  }
});

// -------------------------------------------------- riconoscere l'intenzione

const casi = [
  ['quanto posso offrire per Lautaro', 'offerta'],
  ['fino a quanto posso spingere su Vlahovic', 'offerta'],
  ['quanto vale Leao', 'offerta'],
  ['preso Dimarco a 120', 'acquisto'],
  ['aggiudicato Bastoni a centoventi', 'acquisto'],
  ['annulla Dimarco', 'annulla'],
  ['quanto mi resta', 'stato'],
  ['come sono messo', 'stato'],
  ['come divido il budget', 'piano'],
  ['dammi la strategia', 'piano'],
  ['meglio Lautaro o Vlahovic', 'confronto'],
  ['i migliori attaccanti', 'migliori'],
  ['fammi la formazione', 'formazione'],
  ['quanto vale un gol', 'regolamento'],
];

for (const [frase, atteso] of casi) {
  test(`riconosce: "${frase}"`, () => {
    assert.equal(riconosci(frase)?.intenzione, atteso);
  });
}

test('una frase fuori tema non viene forzata in un' + "'intenzione", () => {
  assert.equal(riconosci('che tempo fa domani'), null);
  assert.equal(riconosci(''), null);
});

test('quando non capisce lo dice e suggerisce cosa chiedere', () => {
  const r = nuovo().ascolta('che tempo fa domani');
  assert.equal(r.intenzione, null);
  assert.match(r.risposta, /Non ho capito/);
  assert.match(r.risposta, /quanto offrire/);
});

// ------------------------------------------------------------- risposte

test('il consiglio d' + "'offerta dice il tetto e perche'", () => {
  const r = nuovo().ascolta('quanto posso offrire per Lautaro');
  assert.match(r.risposta, /Fino a novantuno/);
  assert.match(r.risposta, /cinquecento crediti/);
});

test('registrare un acquisto cambia davvero i conti', () => {
  const c = nuovo();
  assert.match(c.ascolta('preso Dimarco a centoventi').risposta, /trecentottanta/);
  assert.match(c.ascolta('quanto mi resta').risposta, /trecentottanta crediti/);
});

test('un acquisto impossibile viene rifiutato con la ragione', () => {
  const r = nuovo().ascolta('preso Lautaro a 499');
  assert.match(r.risposta, /Non posso/);
  assert.match(r.risposta, /rosa/);
});

test('annullare restituisce i crediti', () => {
  const c = nuovo();
  c.ascolta('preso Dimarco a 120');
  assert.match(c.ascolta('annulla Dimarco').risposta, /cinquecento/);
});

test('annullare chi non c' + "'e' lo dice", () => {
  assert.match(nuovo().ascolta('annulla Maignan').risposta, /non risulta in rosa/);
});

test('a rosa piena consiglia di lasciar perdere', () => {
  const c = nuovo();
  c.ascolta('preso Maignan a 10');
  c.strumenti.asta.compra({ nome: 'P2', ruolo: 'P', quotazione: 5, fvm: 0 }, 5);
  c.strumenti.asta.compra({ nome: 'P3', ruolo: 'P', quotazione: 5, fvm: 0 }, 5);
  c.strumenti.listone = new Listone([...GIOCATORI,
    { nome: 'Altro Portiere', ruolo: 'P', squadra: 'X', quotazione: 12, fvm: 130, fantamedia: null }]);
  assert.match(c.ascolta('quanto offro per Altro Portiere').risposta, /gia' completi/);
});

test('il piano d' + "'asta dice i crediti per reparto", () => {
  const r = nuovo().ascolta('come divido il budget');
  assert.match(r.risposta, /in porta/);
  assert.match(r.risposta, /in attacco/);
});

test('i migliori per ruolo escono in ordine di valore', () => {
  const r = nuovo().ascolta('i migliori attaccanti');
  assert.match(r.risposta, /Lautaro Martinez/);
  assert.ok(r.risposta.indexOf('Lautaro') < r.risposta.indexOf('Vlahovic'));
});

test('senza listone lo dice invece di inventare', () => {
  const c = new Cervello(new Strumenti(new Listone([]), new Asta()));
  assert.match(c.ascolta('i migliori attaccanti').risposta, /non ho le quotazioni/);
});

test('quando due giocatori sono equivalenti non annuncia un vincitore', () => {
  // Sarebbe una risposta che contraddice se stessa.
  const r = nuovo().ascolta('meglio Lautaro o Leao');
  assert.match(r.risposta, /equivalenti/);
  assert.ok(!/^Lautaro Martinez\./.test(r.risposta));
});

test('la formazione senza rosa lo dice', () => {
  assert.match(nuovo().ascolta('fammi la formazione').risposta, /Non posso/);
});

test('le risposte sono corte, da ascoltare', () => {
  const c = nuovo();
  for (const frase of ['quanto posso offrire per Lautaro', 'quanto mi resta',
                       'come divido il budget', 'i migliori attaccanti']) {
    const r = c.ascolta(frase).risposta;
    assert.ok(r.length < 240, `troppo lunga da ascoltare (${r.length}): ${r}`);
  }
});

test('i prezzi nelle risposte sono in lettere, non in cifre', () => {
  // La voce sintetica scandisce male le cifre in mezzo alla frase.
  const r = nuovo().ascolta('quanto posso offrire per Lautaro');
  assert.ok(!/\d/.test(r.risposta), `ci sono cifre da leggere: ${r.risposta}`);
});

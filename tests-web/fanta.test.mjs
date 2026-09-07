// Test del dominio fantacalcio nella versione telefono.
// Il vincolo che non deve mai saltare e' sempre lo stesso: poter completare la rosa.

import assert from 'node:assert/strict';
import test from 'node:test';

import { Asta, Listone, confronta, costruisciFormazione, migliorFormazione,
         normalizza, baseAttesa, modificatoreDifesa } from '../docs/js/fanta.js';
import { Strumenti, DEFINIZIONI } from '../docs/js/strumenti.js';

const g = (nome, ruolo, quotazione = 30, extra = {}) =>
  ({ nome, ruolo, squadra: 'XXX', quotazione, fvm: quotazione * 12, fantamedia: null, ...extra });

// -------------------------------------------------------------- asta

test('il massimo offribile lascia un credito per ogni altro slot', () => {
  assert.equal(new Asta({ budget: 500 }).massimoOffribile(), 476);   // 500 - 24
});

test('non posso spendere tutto e restare con slot vuoti', () => {
  assert.throws(() => new Asta({ budget: 500 }).compra(g('Fenomeno', 'A'), 500),
    /completare la rosa/);
});

test('il massimo scende dopo ogni acquisto', () => {
  const a = new Asta({ budget: 500 });
  a.compra(g('Lautaro', 'A'), 200);
  assert.equal(a.creditiResidui, 300);
  assert.equal(a.massimoOffribile(), 300 - 23);
});

test('niente doppioni e niente slot sforati', () => {
  const a = new Asta({ budget: 500 });
  a.compra(g('Unico', 'C'), 30);
  assert.throws(() => a.compra(g('Unico', 'C'), 20), /gia' in rosa/);
  for (let i = 0; i < 6; i++) a.compra(g(`Att${i}`, 'A', 5), 3);
  assert.throws(() => a.compra(g('Att7', 'A'), 3), /slot A/);
});

test('annullare un acquisto sbagliato restituisce i crediti', () => {
  const a = new Asta({ budget: 500 });
  a.compra(g('Errore', 'C'), 90);
  a.annulla('errore');
  assert.equal(a.creditiResidui, 500);
  assert.throws(() => a.annulla('Nessuno'), /non risulta in rosa/);
});

test('le quotazioni si riscalano sul mio budget', () => {
  assert.equal(new Asta({ budget: 250 }).valore(g('X', 'A', 60)), 30);
  assert.equal(new Asta({ budget: 1000 }).valore(g('X', 'A', 60)), 120);
});

test('il tetto consigliato non supera mai il limite assoluto', () => {
  const a = new Asta({ budget: 500 });
  for (let i = 0; i < 16; i++) a.compra(g(`T${i}`, i < 8 ? 'D' : 'C', 5), 28);
  const c = a.consiglio(g('Costoso', 'A', 200));
  assert.ok(c.offerta_massima <= c.limite_assoluto);
  assert.ok(c.offerta_massima <= a.creditiResidui);
});

test('non consiglia di comprare un reparto gia' + "' completo", () => {
  const a = new Asta({ budget: 500 });
  for (let i = 0; i < 3; i++) a.compra(g(`P${i}`, 'P', 10), 5);
  const c = a.consiglio(g('P4', 'P'));
  assert.equal(c.verdetto, 'lascia');
  assert.equal(c.offerta_massima, 0);
});

test('il piano a fasce e' + "' decrescente e sta nel budget di reparto", () => {
  const a = new Asta({ budget: 500 });
  const prezzi = a.piano().A.prezzi_obiettivo;
  assert.deepEqual(prezzi, [...prezzi].sort((x, y) => y - x));
  assert.ok(prezzi.reduce((s, p) => s + p, 0) <= a.budgetRuolo('A') * 1.02);
});

// ------------------------------------------------------------ listone

test('la ricerca tollera le storpiature della trascrizione', () => {
  const L = new Listone([g('Vlahovic', 'A', 36), g('Dimarco', 'D', 22),
                         g('Kvaratskhelia', 'C', 34), g('Calhanoglu', 'C', 26)]);
  for (const [detto, atteso] of [['vlahovich', 'Vlahovic'], ['di marco', 'Dimarco'],
                                 ['kvaratskelia', 'Kvaratskhelia'], ['calhanoglou', 'Calhanoglu']]) {
    assert.equal(L.cerca(detto)[0]?.giocatore.nome, atteso, `"${detto}" non trova ${atteso}`);
  }
  assert.deepEqual(L.cerca('supercalifragilistico'), []);
});

test('normalizza toglie accenti e punteggiatura', () => {
  assert.equal(normalizza('Vlahović, D.'), 'vlahovic d');
  assert.equal(normalizza('  Di  Marco '), 'di marco');
});

test('legge il formato ufficiale con punto e virgola', () => {
  const L = Listone.daCSV('Id;R;Nome;Squadra;Qt.A;FVM\n1;A;Lautaro Martinez;INTER;42;520\n2;D;Bastoni;INTER;18;210');
  assert.equal(L.length, 2);
  assert.equal(L.get('Lautaro Martinez').quotazione, 42);
  assert.equal(L.get('Bastoni').ruolo, 'D');
});

test('legge i decimali con la virgola', () => {
  // Gli export italiani usano il punto e virgola proprio perche' i decimali
  // hanno la virgola: il caricatore deve reggere quella combinazione.
  const L = Listone.daCSV('Nome;R;Qt.A;Fm\nTizio;C;12,5;6,75');
  assert.equal(L.get('Tizio').quotazione, 12.5);
  assert.equal(L.get('Tizio').fantamedia, 6.75);
});

test('riconosce da solo il separatore virgola', () => {
  const L = Listone.daCSV('Nome,R,Qt.A\nTizio,C,12');
  assert.equal(L.get('Tizio').quotazione, 12);
});

test('un CSV senza nomi lo dice chiaramente', () => {
  assert.throws(() => Listone.daCSV('Squadra;R\nMIL;A'), /nomi dei giocatori/);
});

// --------------------------------------------------------- formazione

test('senza storico la quotazione fa da stima, e viene dichiarato', () => {
  const caro = baseAttesa(g('Top', 'A', 40)), economico = baseAttesa(g('Riserva', 'A', 5));
  assert.ok(caro.base > economico.base);
  assert.equal(caro.origine, 'stimata dalla quotazione');
  assert.equal(baseAttesa(g('X', 'A', 40, { fantamedia: 6.1 })).origine, 'storica');
});

test('la titolarita' + "' domina sul talento", () => {
  const rosa = [g('Por', 'P'), ...Array.from({ length: 3 }, (_, i) => g(`D${i}`, 'D')),
                ...Array.from({ length: 4 }, (_, i) => g(`C${i}`, 'C')),
                g('Fenomeno', 'A', 60, { fantamedia: 8, probabilitaTitolare: 0.2 }),
                g('Onesto', 'A', 10, { fantamedia: 6.3, probabilitaTitolare: 1 }),
                g('Terzo', 'A', 10, { fantamedia: 6.2, probabilitaTitolare: 1 })];
  const f = costruisciFormazione(rosa, '3-4-3');
  const nomi = f.titolari.map((t) => t.giocatore.nome);
  assert.ok(nomi.includes('Onesto'));
  assert.ok(f.avvertenze.some((a) => a.includes('Fenomeno')));
});

test('gli indisponibili non scendono in campo', () => {
  const rosa = [g('Por', 'P'), ...Array.from({ length: 5 }, (_, i) => g(`D${i}`, 'D')),
                ...Array.from({ length: 6 }, (_, i) => g(`C${i}`, 'C')),
                ...Array.from({ length: 4 }, (_, i) => g(`A${i}`, 'A'))];
  rosa[1].stato = 'squalificato';
  const f = costruisciFormazione(rosa, '3-4-3');
  assert.ok(!f.titolari.some((t) => t.giocatore.nome === 'D0'));
  assert.ok(f.avvertenze.some((a) => /squalificato/.test(a)));
});

test('il modulo migliore segue i giocatori forti', () => {
  const rosa = [g('Por', 'P'), ...Array.from({ length: 5 }, (_, i) => g(`D${i}`, 'D', 5, { fantamedia: 5 })),
                ...Array.from({ length: 5 }, (_, i) => g(`C${i}`, 'C', 5, { fantamedia: 6 })),
                ...Array.from({ length: 3 }, (_, i) => g(`A${i}`, 'A', 5, { fantamedia: 9 }))];
  assert.ok(migliorFormazione(rosa).modulo.endsWith('-3'));
});

test('rosa incompleta: nessun modulo copribile', () => {
  assert.throws(() => migliorFormazione([g('Por', 'P'), g('Att', 'A')]), /nessun modulo copribile/);
});

test('il confronto sceglie il titolare certo e lo spiega', () => {
  const e = confronta(g('Panchinaro', 'A', 60, { fantamedia: 8, probabilitaTitolare: 0.2 }),
                      g('Titolare', 'A', 20, { fantamedia: 6.5, probabilitaTitolare: 1 }));
  assert.equal(e.scelta, 'Titolare');
  assert.match(e.motivo, /campo/);
});

test('il modificatore di difesa segue le fasce standard', () => {
  assert.equal(modificatoreDifesa(6.6), 3);
  assert.equal(modificatoreDifesa(5.0), 0);
});

// --------------------------------------------------------- strumenti

test('ogni strumento dichiarato ha la sua implementazione', () => {
  const s = new Strumenti(new Listone([]), new Asta());
  for (const d of DEFINIZIONI) {
    assert.equal(typeof s[d.name], 'function', `manca ${d.name}`);
    assert.ok(d.description.length > 40, `descrizione troppo corta: ${d.name}`);
  }
});

test('gli strumenti non espongono i metodi privati', () => {
  const s = new Strumenti(new Listone([]), new Asta());
  assert.match(s.esegui('_risolvi', {}).errore, /sconosciuto/);
  assert.match(s.esegui('inventato', {}).errore, /sconosciuto/);
});

test('un acquisto impossibile torna come errore, non come eccezione', () => {
  const L = new Listone([g('Lautaro Martinez', 'A', 42)]);
  const s = new Strumenti(L, new Asta({ budget: 500 }));
  assert.match(s.esegui('registra_acquisto', { nome: 'lautaro', prezzo: 499 }).errore, /rosa/);
});

test('lo stato d' + "'asta cambia dopo un acquisto dettato a voce", () => {
  const L = new Listone([g('Lautaro Martinez', 'A', 42)]);
  const s = new Strumenti(L, new Asta({ budget: 500 }));
  s.esegui('registra_acquisto', { nome: 'lautaro martines', prezzo: 180 });
  assert.equal(s.esegui('stato_asta', {}).crediti_residui, 320);
});

test('senza listone lo dice invece di inventare', () => {
  const s = new Strumenti(new Listone([]), new Asta());
  assert.match(s.esegui('cerca_giocatore', { nome: 'Lautaro' }).errore, /listone non caricato/);
});

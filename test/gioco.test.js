import test from 'node:test';
import assert from 'node:assert/strict';

import {
  classifica, confermaIndizio, confermaTiro, diTurno, giroCorrente,
  nuovaPartita, prendiTelefono, prossimo, valuta,
} from '../docs/js/gioco.js';

const SEI = ['Ada', 'Bea', 'Carlo', 'Dino', 'Ema', 'Fabio'];

// Una sorgente casuale prevedibile, cosi' i test non ballano.
function finta(valori) {
  let i = 0;
  return () => valori[i++ % valori.length];
}

/** Gioca un round intero: ogni indovino tira il valore che gli passi. */
function giocaRound(stato, tiri) {
  prendiTelefono(stato);
  confermaIndizio(stato, 'un indizio');
  for (const valore of tiri) {
    assert.equal(stato.fase, 'passaggio-tiro');
    prendiTelefono(stato);
    assert.equal(stato.fase, 'tiro');
    confermaTiro(stato, valore);
  }
  return stato;
}

test('si gioca in sei: dodici round per due giri, uno a testa per giro', () => {
  const s = nuovaPartita(SEI, 2);
  assert.equal(s.roundTotali, 12);
  assert.equal(s.round.ordine.length, 5, 'tirano tutti tranne chi ha dato l\'indizio');
  assert.equal(giroCorrente(s), 1);
});

test('il turno gira: ognuno da l\'indizio una volta per giro', () => {
  const s = nuovaPartita(SEI, 2);
  const dato = [];
  for (let r = 0; r < 12; r++) {
    dato.push(s.giocatori[s.round.indizio].nome);
    giocaRound(s, [50, 50, 50, 50, 50]);
    prossimo(s); // rivelazione -> classifica
    prossimo(s); // classifica -> round dopo (o fine)
  }
  assert.deepEqual(dato.slice(0, 6), SEI);
  assert.deepEqual(dato.slice(6), SEI, 'il secondo giro ricomincia da capo');
  assert.equal(s.fase, 'fine');
});

test('chi tira non e mai chi ha dato l\'indizio, e ognuno tira una volta sola', () => {
  const s = nuovaPartita(SEI, 1);
  for (let r = 0; r < 6; r++) {
    const visti = [];
    prendiTelefono(s);
    confermaIndizio(s, 'via');
    for (let k = 0; k < 5; k++) {
      const chi = diTurno(s);
      assert.notEqual(chi.indice, s.round.indizio);
      visti.push(chi.indice);
      prendiTelefono(s);
      confermaTiro(s, 10 * k);
    }
    assert.equal(new Set(visti).size, 5);
    prossimo(s); prossimo(s);
  }
});

test('i punti seguono la distanza dal bersaglio', () => {
  assert.deepEqual(valuta(0), { punti: 5, esito: 'In pieno' });
  assert.equal(valuta(4).punti, 5);
  assert.equal(valuta(5).punti, 4);
  assert.equal(valuta(9).punti, 4);
  assert.equal(valuta(16).punti, 3);
  assert.equal(valuta(25).punti, 2);
  assert.equal(valuta(36).punti, 1);
  assert.equal(valuta(37).punti, 0);
  assert.equal(valuta(100).punti, 0);
});

test('chi da l\'indizio prende la media di chi lo ha ascoltato', () => {
  const s = nuovaPartita(SEI, 1, finta([0.5]));
  const bersaglio = s.round.bersaglio;
  // 5 + 5 + 3 + 0 + 0 = 13 su cinque tiri -> media 2.6 -> 3
  giocaRound(s, [bersaglio, bersaglio + 2, bersaglio + 12, bersaglio + 40, bersaglio - 40]);

  assert.deepEqual(s.round.esiti.map(e => e.punti), [5, 5, 3, 0, 0]);
  assert.equal(s.round.puntiIndizio, 3);
  assert.equal(s.giocatori[s.round.indizio].punti, 3);
  assert.equal(s.giocatori[s.round.ordine[0]].punti, 5);
});

test('il bersaglio sta sempre dentro la scala, lontano dagli estremi', () => {
  for (let i = 0; i < 300; i++) {
    const s = nuovaPartita(SEI, 1);
    assert.ok(s.round.bersaglio >= 5 && s.round.bersaglio <= 95, `fuori: ${s.round.bersaglio}`);
  }
  const basso = nuovaPartita(SEI, 1, finta([0]));
  const alto = nuovaPartita(SEI, 1, finta([0.999999]));
  assert.equal(basso.round.bersaglio, 5);
  assert.equal(alto.round.bersaglio, 95);
});

test('i tiri restano dentro la scala anche se arrivano storti', () => {
  const s = nuovaPartita(SEI, 1);
  prendiTelefono(s); confermaIndizio(s, 'via');
  confermaTiro(s, -30);
  confermaTiro(s, 180);
  assert.equal(s.round.tiri[s.round.ordine[0]], 0);
  assert.equal(s.round.tiri[s.round.ordine[1]], 100);
});

test('la classifica ordina per punti e mette i pari merito allo stesso posto', () => {
  const s = nuovaPartita(SEI, 1);
  const punti = [3, 7, 7, 1, 0, 9];
  s.giocatori.forEach((g, i) => { g.punti = punti[i]; });
  const c = classifica(s);
  assert.deepEqual(c.map(r => r.nome), ['Fabio', 'Bea', 'Carlo', 'Ada', 'Dino', 'Ema']);
  assert.deepEqual(c.map(r => r.posto), [1, 2, 2, 4, 5, 6]);
});

test('non si gioca da soli e non si gioca in trenta', () => {
  assert.throws(() => nuovaPartita(['Ada', 'Bea'], 1), /almeno 3/);
  assert.throws(() => nuovaPartita(Array.from({ length: 13 }, (_, i) => `G${i}`), 1), /più di 12/);
  assert.throws(() => nuovaPartita(['Ada', '  ', 'Bea'], 1), /almeno 3/);
});

test('l\'indizio vuoto non passa', () => {
  const s = nuovaPartita(SEI, 1);
  prendiTelefono(s);
  assert.throws(() => confermaIndizio(s, '   '), /Scrivi/);
  assert.equal(s.fase, 'indizio');
});

test('lo stato regge il salvataggio e il ritorno da JSON', () => {
  const s = nuovaPartita(SEI, 2);
  prendiTelefono(s); confermaIndizio(s, 'mezzogiorno'); confermaTiro(s, 40);
  const tornato = JSON.parse(JSON.stringify(s));
  assert.deepEqual(tornato, s);
  assert.equal(diTurno(tornato).nome, diTurno(s).nome);
});

test('le carte non si ripetono finche il mazzo non e finito', () => {
  const s = nuovaPartita(SEI, 2);
  const viste = new Set();
  for (let r = 0; r < 12; r++) {
    const carta = `${s.round.coppia.alto}|${s.round.coppia.basso}`;
    assert.ok(!viste.has(carta), `carta ripetuta: ${carta}`);
    viste.add(carta);
    giocaRound(s, [50, 50, 50, 50, 50]);
    prossimo(s); prossimo(s);
  }
});

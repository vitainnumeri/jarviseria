import assert from 'node:assert/strict';
import test from 'node:test';

import { cosine, dbfs, embed, EMBED_DIM, NoiseFloor, pitch, resample } from '../docs/js/dsp.js';
import {
  calibrate, Cohort, DECISION, embedWindows, profileHomogeneity,
  SpeakerVerifier, VoiceProfile,
} from '../docs/js/verifier.js';
import { parla, PERSONE, silenzio, SR } from './voci.mjs';

const IO = 0;

function profiloProprietario(frasi = 8) {
  const profilo = new VoiceProfile();
  for (let i = 0; i < frasi; i++) {
    for (const v of embedWindows(parla(IO, 3, i + 1))) profilo.add(v);
  }
  return profilo;
}

function costruisciVerificatore(opzioni = {}) {
  const profilo = profiloProprietario();
  const cal = calibrate(profilo);
  return new SpeakerVerifier(profilo, { ...cal, nearFieldEnabled: false, ...opzioni });
}

// ------------------------------------------------------------------- DSP

test('il pitch riconosce l\'altezza della voce', () => {
  for (const p of PERSONE.slice(0, 4)) {
    const stimato = pitch(parla(PERSONE.indexOf(p), 0.05, 1).subarray(0, 400));
    assert.ok(Math.abs(stimato - p.f0) < 12, `${p.nome}: ${stimato} invece di ${p.f0}`);
  }
});

test('l\'impronta ha dimensione fissa e nota', () => {
  assert.equal(embed(parla(IO, 2, 1)).length, EMBED_DIM);
});

test('un segmento troppo corto non produce impronta', () => {
  assert.equal(embed(new Float32Array(500)), null);
});

test('il silenzio non produce impronta', () => {
  assert.equal(embed(silenzio(2)), null);
});

test('il livello distingue vicino e lontano', () => {
  assert.ok(dbfs(parla(IO, 1, 1, 0.3)) > dbfs(parla(IO, 1, 1, 0.01)) + 20);
});

test('il rumore di fondo sale piano e scende in fretta', () => {
  const rumore = new NoiseFloor(-60);
  for (let i = 0; i < 40; i++) rumore.update(parla(2, 0.02, i, 0.05));
  const dopoBrusio = rumore.valueDb;
  assert.ok(dopoBrusio > -60);
  for (let i = 0; i < 40; i++) rumore.update(silenzio(0.02));
  assert.ok(rumore.valueDb < dopoBrusio);
});

test('il ricampionamento cambia la lunghezza e non il resto', () => {
  assert.equal(resample(parla(IO, 1, 1), SR, 8000).length, 8000);
  const a = parla(IO, 0.1, 1);
  assert.equal(resample(a, SR, SR), a);
});

test('il coseno di un vettore con se stesso vale uno', () => {
  const v = embed(parla(IO, 2, 1));
  assert.ok(Math.abs(cosine(v, v) - 1) < 1e-5 || cosine(v, v) > 0.99);
});

// -------------------------------------------------------------- profilo

test('il profilo riconosce la propria voce e non le altre', () => {
  const profilo = profiloProprietario();
  const mio = profilo.score(embed(parla(IO, 3, 99)));
  assert.ok(mio > 0.3, `punteggio mio troppo basso: ${mio}`);
  for (let p = 1; p < PERSONE.length; p++) {
    const altro = profilo.score(embed(parla(p, 3, 99)));
    assert.ok(altro < mio / 2, `${PERSONE[p].nome} prende ${altro}, io ${mio}`);
  }
});

test('il profilo si salva e si ricarica identico', () => {
  const profilo = profiloProprietario(3);
  const riletto = VoiceProfile.fromJSON(JSON.parse(JSON.stringify(profilo.toJSON())));
  const v = embed(parla(IO, 3, 77));
  assert.ok(Math.abs(profilo.score(v) - riletto.score(v)) < 1e-6);
});

test('un profilo vuoto non riconosce nessuno', () => {
  assert.equal(new VoiceProfile().score(embed(parla(IO, 2, 1))), 0);
});

test('rileva se in mezzo all\'arruolamento ha parlato qualcun altro', () => {
  const pulito = profiloProprietario(6);
  const sporco = new VoiceProfile();
  for (const p of [IO, IO, IO, 1, 3, 4]) {
    for (const v of embedWindows(parla(p, 3, p + 7))) sporco.add(v);
  }
  assert.equal(profileHomogeneity(pulito).clean, true);
  assert.equal(profileHomogeneity(sporco).clean, false);
  assert.match(profileHomogeneity(sporco).note, /rifai l'arruolamento/);
});

test('con poche frasi non si azzarda un giudizio sull\'omogeneita\'', () => {
  assert.match(profileHomogeneity(new VoiceProfile()).note, /troppo poche/);
});

// ---------------------------------------------------------- calibrazione

test('la soglia viene calibrata sulle frasi registrate', () => {
  const cal = calibrate(profiloProprietario());
  assert.ok(cal.acceptThreshold > 0.1 && cal.acceptThreshold < 0.5);
  assert.ok(cal.continueThreshold < cal.acceptThreshold);
  assert.equal(cal.note, 'calibrazione riuscita');
});

test('con poche frasi si usano soglie prudenziali', () => {
  const cal = calibrate(new VoiceProfile([embed(parla(IO, 2, 1))]));
  assert.match(cal.note, /poche frasi/);
});

// -------------------------------------------- il caso che conta davvero

test('riconosce me e ignora tutti gli altri', () => {
  const ver = costruisciVerificatore();
  assert.equal(ver.verify(parla(IO, 3, 500)).decision, DECISION.OWNER);
  for (let p = 1; p < PERSONE.length; p++) {
    assert.equal(ver.verify(parla(p, 3, 500)).decision, DECISION.STRANGER,
      `${PERSONE[p].nome} e' passato`);
  }
});

test('stanza affollata: cinque estranei parlano a turno, rispondo a uno solo', () => {
  const ver = costruisciVerificatore();
  const accettati = [];
  for (let p = 0; p < PERSONE.length; p++) {
    if (ver.verify(parla(p, 3, 600 + p)).decision === DECISION.OWNER) accettati.push(p);
  }
  assert.deepEqual(accettati, [IO]);
});

test('misura su molti turni alternati: nessun estraneo passa', () => {
  const ver = costruisciVerificatore();
  let miei = 0, mieiTot = 0, estranei = 0, estraneiTot = 0;
  for (let k = 0; k < 12; k++) {
    mieiTot++;
    if (ver.verify(parla(IO, 3, 200 + k * 11)).decision === DECISION.OWNER) miei++;
    for (let p = 1; p < PERSONE.length; p++) {
      estraneiTot++;
      if (ver.verify(parla(p, 3, 300 + k * 13 + p)).decision === DECISION.OWNER) estranei++;
    }
  }
  const falsiAccessi = estranei / estraneiTot;
  const falsiRifiuti = 1 - miei / mieiTot;
  assert.equal(falsiAccessi, 0, `${estranei} estranei su ${estraneiTot} sono passati`);
  assert.ok(falsiRifiuti <= 0.2, `mi rifiuta troppo spesso: ${(falsiRifiuti * 100).toFixed(0)}%`);
});

test('un segmento troppo breve resta incerto, non viene accettato', () => {
  assert.equal(costruisciVerificatore().verify(parla(IO, 0.2, 1)).decision, DECISION.UNCERTAIN);
});

// ------------------------------------------------------ coorte e margine

test('la coorte impara da sola le voci della stanza', () => {
  const ver = costruisciVerificatore();
  assert.equal(ver.cohort.size, 0);
  for (let p = 1; p < PERSONE.length; p++) ver.verify(parla(p, 3, 700 + p));
  assert.ok(ver.cohort.size >= 3, `ha imparato solo ${ver.cohort.size} voci`);
});

test('la coorte usa la scala del proprietario', () => {
  // Senza scala condivisa i due punteggi del margine non sono confrontabili:
  // un profilo costruito su una frase sola darebbe 1.00 a chiunque e il margine
  // finirebbe per rifiutare anche me.
  const ver = costruisciVerificatore();
  ver.cohort.add(embed(parla(3, 3, 1)));
  const mio = embed(parla(IO, 3, 2));
  assert.ok(ver.cohort.bestMatch(mio) < 0.5,
    `un estraneo assomiglia troppo a me: ${ver.cohort.bestMatch(mio)}`);
});

test('imparare gli estranei non mi fa smettere di essere riconosciuto', () => {
  // Il difetto trovato misurando: un mio turno rifiutato per un soffio finiva
  // fra gli estranei, e da li' in poi il margine lavorava contro di me.
  const ver = costruisciVerificatore();
  for (let k = 0; k < 15; k++) {
    for (let p = 1; p < PERSONE.length; p++) ver.verify(parla(p, 3, 800 + k * 7 + p));
  }
  let riconosciuti = 0;
  for (let k = 0; k < 6; k++) {
    if (ver.verify(parla(IO, 3, 900 + k * 5)).decision === DECISION.OWNER) riconosciuti++;
  }
  assert.ok(riconosciuti >= 5, `dopo aver imparato ${ver.cohort.size} voci mi riconosce solo ${riconosciuti}/6`);
});

test('la coorte non blocca il proprietario nemmeno da satura', () => {
  const ver = costruisciVerificatore();
  for (let k = 0; k < 40; k++) ver.cohort.add(embed(parla(1 + (k % 5), 3, k)));
  assert.equal(ver.verify(parla(IO, 3, 1000)).decision, DECISION.OWNER);
});

// ------------------------------------------------------- campo vicino

test('la mia voce da lontano non apre un turno', () => {
  const ver = costruisciVerificatore({ nearFieldEnabled: true, nearFieldMarginDb: 8 });
  for (let i = 0; i < 60; i++) ver.observeNoise(parla(2, 0.02, i, 0.02));
  assert.equal(ver.verify(parla(IO, 3, 1, 0.3)).decision, DECISION.OWNER);
  assert.notEqual(ver.verify(parla(IO, 3, 1, 0.002)).decision, DECISION.OWNER);
});

// -------------------------------------------------- rifiuto precoce

test('un estraneo viene scartato dopo poche finestre', () => {
  const ver = costruisciVerificatore();
  const audio = parla(3, 6, 1);
  const finestre = [];
  for (let i = 0; i * 0.75 * SR + 1.5 * SR <= audio.length; i++) {
    const inizio = Math.floor(i * 0.75 * SR);
    finestre.push(ver.scoreWindow(audio.subarray(inizio, inizio + 1.5 * SR), i));
    if (ver.streamDecision(finestre) === DECISION.STRANGER) {
      assert.ok(i <= 3, `ci ha messo ${i} finestre a capire che non ero io`);
      return;
    }
  }
  assert.fail('non ha mai scartato l\'estraneo');
});

test('la decisione parziale aggancia il proprietario', () => {
  const ver = costruisciVerificatore();
  const audio = parla(IO, 4, 1);
  const finestre = [];
  for (let i = 0; i < 2; i++) {
    const inizio = Math.floor(i * 0.75 * SR);
    finestre.push(ver.scoreWindow(audio.subarray(inizio, inizio + 1.5 * SR), i));
  }
  assert.equal(ver.streamDecision(finestre), DECISION.OWNER);
  assert.ok(ver.locked);
});

test('l\'isteresi abbassa la soglia a turno aperto', () => {
  const ver = costruisciVerificatore({ acceptThreshold: 0.4, continueThreshold: 0.3 });
  assert.equal(ver.threshold, 0.4);
  ver.locked = true;
  assert.equal(ver.threshold, 0.3);
  ver.resetTurn();
  assert.equal(ver.threshold, 0.4);
});

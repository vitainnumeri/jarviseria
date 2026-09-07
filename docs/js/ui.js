// L'interfaccia: schermate, passaggi di mano e salvataggio.
//
// La regola che tiene in piedi il gioco e' una sola: fra un giocatore e
// l'altro si passa sempre da una schermata di passaggio, e cio' che non deve
// vedere chi ha il telefono in mano non viene disegnato affatto. Il bersaglio,
// mentre gli altri tirano, non sta da nessuna parte nella pagina.

import {
  MAX_GIOCATORI, MIN_GIOCATORI,
  classifica, confermaIndizio, confermaTiro, diTurno, giroCorrente,
  nuovaPartita, prendiTelefono, prossimo,
} from './gioco.js';
import { creaScala } from './scala.js';

const CHIAVE = 'viadimezzo.partita';
const GIRI = [
  { valore: 1, nome: 'Corta', nota: 'un giro' },
  { valore: 2, nome: 'Normale', nota: 'due giri' },
  { valore: 3, nome: 'Lunga', nota: 'tre giri' },
];

const $ = id => document.getElementById(id);
const SCHERMATE = ['setup', 'passaggio', 'indizio', 'tiro', 'rivelazione', 'classifica', 'fine'];

let partita = null;
let nomi = ['', '', '', '', '', ''];
let giri = 2;

// ----------------------------------------------------------------- archivio
function salva() {
  try {
    if (partita) localStorage.setItem(CHIAVE, JSON.stringify(partita));
    else localStorage.removeItem(CHIAVE);
  } catch { /* niente spazio o navigazione privata: si gioca lo stesso */ }
}

function recupera() {
  try {
    const grezzo = localStorage.getItem(CHIAVE);
    if (!grezzo) return null;
    const s = JSON.parse(grezzo);
    return s && s.giocatori && s.fase && s.fase !== 'setup' ? s : null;
  } catch { return null; }
}

// ------------------------------------------------------------------ schermi
function mostra(quale) {
  for (const nome of SCHERMATE) {
    $(`schermata-${nome}`).classList.toggle('nascosta', nome !== quale);
  }
  window.scrollTo(0, 0);
}

/** Il nome accorciato per stare nelle targhette sulla scala. */
function sigla(nome) {
  const pulito = nome.trim();
  return pulito.length > 8 ? `${pulito.slice(0, 7)}\u2026` : pulito;
}

// -------------------------------------------------------------------- setup
function disegnaNomi() {
  const lista = $('lista-nomi');
  lista.textContent = '';
  nomi.forEach((nome, i) => {
    const riga = document.createElement('li');
    riga.className = 'riga-nome';

    const campo = document.createElement('input');
    campo.type = 'text';
    campo.value = nome;
    campo.maxLength = 16;
    campo.placeholder = `Giocatore ${i + 1}`;
    campo.autocomplete = 'off';
    campo.setAttribute('aria-label', `Nome del giocatore ${i + 1}`);
    campo.addEventListener('input', () => { nomi[i] = campo.value; });

    const via = document.createElement('button');
    via.className = 'icona';
    via.innerHTML = '&times;';
    via.setAttribute('aria-label', `Togli il giocatore ${i + 1}`);
    via.disabled = nomi.length <= MIN_GIOCATORI;
    via.addEventListener('click', () => {
      nomi.splice(i, 1);
      disegnaNomi();
    });

    riga.append(campo, via);
    lista.append(riga);
  });
  $('aggiungi-giocatore').disabled = nomi.length >= MAX_GIOCATORI;
}

function disegnaGiri() {
  const scelte = $('scelta-giri');
  scelte.textContent = '';
  for (const g of GIRI) {
    const bottone = document.createElement('button');
    bottone.className = 'scelta' + (g.valore === giri ? ' attiva' : '');
    bottone.setAttribute('role', 'radio');
    bottone.setAttribute('aria-checked', String(g.valore === giri));
    bottone.innerHTML = `<strong>${g.nome}</strong><small>${g.nota}</small>`;
    bottone.addEventListener('click', () => { giri = g.valore; disegnaGiri(); });
    scelte.append(bottone);
  }
}

function avvia() {
  const errore = $('errore-setup');
  try {
    partita = nuovaPartita(nomi, giri);
    errore.classList.add('nascosta');
    salva();
    rendi();
  } catch (e) {
    errore.textContent = e.message;
    errore.classList.remove('nascosta');
  }
}

// ------------------------------------------------------------------- scale
const scalaIndizio = creaScala();
const scalaTiro = creaScala({
  interattiva: true,
  onCambio: () => { $('conferma-tiro').disabled = false; },
});
const scalaRivelazione = creaScala();
$('scala-indizio').append(scalaIndizio.nodo);
$('scala-tiro').append(scalaTiro.nodo);
$('scala-rivelazione').append(scalaRivelazione.nodo);

// ------------------------------------------------------------- schermate
function intestazione() {
  const conta = $('conta-round');
  const menu = $('apri-menu');
  const in_corso = partita && partita.fase !== 'fine';
  conta.classList.toggle('nascosta', !in_corso);
  menu.classList.toggle('nascosta', !partita);
  if (in_corso) {
    conta.textContent = `Round ${partita.roundNumero}/${partita.roundTotali}` +
      (partita.giri > 1 ? ` · giro ${giroCorrente(partita)}` : '');
  }
}

function rendiPassaggio() {
  const chi = diTurno(partita);
  const daIndizio = chi.ruolo === 'indizio';
  $('passaggio-ruolo').textContent = daIndizio ? 'Passa il telefono a' : 'Tocca a';
  $('passaggio-nome').textContent = chi.nome;
  $('passaggio-nota').textContent = daIndizio
    ? 'Guarderai tu il bersaglio: tieni lo schermo per te.'
    : `Segna il tuo punto. Restano ${partita.round.ordine.length - partita.round.cursore} tiri.`;
  $('prendi-telefono').textContent = daIndizio ? 'Ci sono, sono solo io a guardare' : 'Ci sono, tocca a me';
  mostra('passaggio');
}

function rendiIndizio() {
  const r = partita.round;
  scalaIndizio.pulisci();
  scalaIndizio.coppia(r.coppia);
  scalaIndizio.segna({ valore: r.bersaglio, tipo: 'bersaglio', etichetta: 'qui' });
  $('indizio-chi').textContent = partita.giocatori[r.indizio].nome;
  $('testo-indizio').value = r.testoIndizio || '';
  $('errore-indizio').classList.add('nascosta');
  copri(true);
  mostra('indizio');
}

function rendiTiro() {
  const r = partita.round;
  const chi = diTurno(partita);
  scalaTiro.pulisci();
  scalaTiro.coppia(r.coppia);
  scalaTiro.abilita(true);
  $('tiro-chi').textContent = chi.nome;
  $('tiro-progresso').textContent = `${r.cursore + 1} di ${r.ordine.length}`;
  $('tiro-indizio').textContent = `“${r.testoIndizio}”`;
  $('conferma-tiro').disabled = true;
  mostra('tiro');
}

function rendiRivelazione() {
  const r = partita.round;
  scalaRivelazione.pulisci();
  scalaRivelazione.coppia(r.coppia);
  scalaRivelazione.segna({ valore: r.bersaglio, tipo: 'bersaglio', etichetta: 'bersaglio' });
  for (const e of r.esiti) {
    scalaRivelazione.segna({ valore: e.valore, tipo: 'tiro', etichetta: sigla(e.nome) });
  }

  $('rivelazione-indizio').textContent =
    `${partita.giocatori[r.indizio].nome}: “${r.testoIndizio}”`;

  const elenco = $('esiti');
  elenco.textContent = '';
  const righe = r.esiti
    .slice()
    .sort((a, b) => a.distanza - b.distanza)
    .map(e => ({ nome: e.nome, esito: e.esito, dettaglio: `${e.distanza} di scarto`, punti: e.punti }));
  righe.push({
    nome: partita.giocatori[r.indizio].nome,
    esito: 'Indizio',
    dettaglio: 'media di chi ha tirato',
    punti: r.puntiIndizio,
    indizio: true,
  });

  for (const riga of righe) {
    const li = document.createElement('li');
    li.className = 'esito' + (riga.indizio ? ' esito-indizio' : '') + (riga.punti === 0 ? ' zero' : '');
    li.innerHTML =
      `<span class="esito-nome">${escapa(riga.nome)}</span>` +
      `<span class="esito-nota">${escapa(riga.esito)} · ${escapa(riga.dettaglio)}</span>` +
      `<span class="esito-punti">+${riga.punti}</span>`;
    elenco.append(li);
  }
  mostra('rivelazione');
}

function rendiClassifica() {
  disegnaTabellone($('tabellone'));
  $('prossimo-round').textContent =
    partita.roundNumero >= partita.roundTotali ? 'Vedi chi ha vinto' : 'Prossimo round';
  mostra('classifica');
}

function rendiFine() {
  const ordine = classifica(partita);
  const primi = ordine.filter(r => r.posto === 1);
  $('vincitore').textContent = primi.length === 1
    ? `Vince ${primi[0].nome} con ${primi[0].punti} punti`
    : `Pari merito: ${primi.map(p => p.nome).join(', ')}`;
  disegnaTabellone($('tabellone-finale'));
  mostra('fine');
}

function disegnaTabellone(dove) {
  dove.textContent = '';
  for (const riga of classifica(partita)) {
    const li = document.createElement('li');
    li.className = 'riga-tabellone' + (riga.posto === 1 ? ' primo' : '');
    li.innerHTML =
      `<span class="posto">${riga.posto}</span>` +
      `<span class="nome">${escapa(riga.nome)}</span>` +
      `<span class="punti">${riga.punti}</span>`;
    dove.append(li);
  }
}

function escapa(testo) {
  const d = document.createElement('div');
  d.textContent = testo;
  return d.innerHTML;
}

/** Disegna la schermata giusta per la fase in cui siamo. */
function rendi() {
  intestazione();
  // Una schermata nascosta e' pur sempre nella pagina: le scale che non
  // servono si svuotano, cosi' mentre gli altri tirano il bersaglio non e'
  // scritto da nessuna parte.
  if (!partita || partita.fase !== 'indizio') scalaIndizio.pulisci();
  if (!partita || partita.fase !== 'rivelazione') scalaRivelazione.pulisci();
  if (!partita) { mostra('setup'); return; }
  switch (partita.fase) {
    case 'passaggio-indizio':
    case 'passaggio-tiro': rendiPassaggio(); break;
    case 'indizio': rendiIndizio(); break;
    case 'tiro': rendiTiro(); break;
    case 'rivelazione': rendiRivelazione(); break;
    case 'classifica': rendiClassifica(); break;
    case 'fine': rendiFine(); break;
    default: mostra('setup');
  }
}

// ------------------------------------------------------------------ il velo
// Il bersaglio sta sotto un velo che si alza solo finche' tieni il dito
// premuto: chi da' l'indizio puo' sbirciare girando il telefono, e se lo
// posa sul tavolo non resta niente in mostra.
function copri(si) {
  $('scala-indizio').classList.toggle('coperta', si);
  $('scopri').classList.toggle('alzato', !si);
}

// ------------------------------------------------------------------ comandi
$('aggiungi-giocatore').addEventListener('click', () => {
  if (nomi.length < MAX_GIOCATORI) { nomi.push(''); disegnaNomi(); }
});
$('avvia').addEventListener('click', avvia);

$('prendi-telefono').addEventListener('click', () => {
  prendiTelefono(partita);
  salva();
  rendi();
});

const velo = $('scopri');
velo.addEventListener('pointerdown', evento => {
  evento.preventDefault();
  velo.setPointerCapture(evento.pointerId);
  copri(false);
});
for (const fine of ['pointerup', 'pointercancel', 'pointerleave']) {
  velo.addEventListener(fine, () => copri(true));
}
velo.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') copri(false); });
velo.addEventListener('keyup', () => copri(true));
velo.addEventListener('blur', () => copri(true));

$('conferma-indizio').addEventListener('click', () => {
  const errore = $('errore-indizio');
  try {
    confermaIndizio(partita, $('testo-indizio').value);
    errore.classList.add('nascosta');
    salva();
    rendi();
  } catch (e) {
    errore.textContent = e.message;
    errore.classList.remove('nascosta');
    $('testo-indizio').focus();
  }
});
$('testo-indizio').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); $('conferma-indizio').click(); }
});

$('conferma-tiro').addEventListener('click', () => {
  const valore = scalaTiro.valore();
  if (valore == null) return;
  scalaTiro.abilita(false);
  confermaTiro(partita, valore);
  salva();
  rendi();
});

$('vai-classifica').addEventListener('click', () => { prossimo(partita); salva(); rendi(); });
$('prossimo-round').addEventListener('click', () => { prossimo(partita); salva(); rendi(); });

$('rivincita').addEventListener('click', () => {
  nomi = partita.giocatori.map(g => g.nome);
  giri = partita.giri;
  partita = nuovaPartita(nomi, giri);
  salva();
  rendi();
});

$('da-capo').addEventListener('click', abbandona);
$('apri-menu').addEventListener('click', () => {
  if (partita.fase === 'fine' || confirm('Chiudere la partita in corso?')) abbandona();
});

function abbandona() {
  if (partita) { nomi = partita.giocatori.map(g => g.nome); giri = partita.giri; }
  while (nomi.length < MIN_GIOCATORI) nomi.push('');
  partita = null;
  salva();
  disegnaNomi();
  disegnaGiri();
  rendi();
}

// -------------------------------------------------------------------- via
partita = recupera();
if (partita) { nomi = partita.giocatori.map(g => g.nome); giri = partita.giri; }
disegnaNomi();
disegnaGiri();
rendi();

// L'interfaccia: tre schermate (avvio, registrazione della voce, ascolto) piu'
// il pannello delle impostazioni. Tutto lo stato vero vive in Sessione: qui si
// disegna e si raccolgono i tocchi.

import { FRASI_ARRUOLAMENTO, Microfono, Sessione, SR, archivio, CHIAVI,
         sintesiDisponibile, trascrizioneDisponibile } from './app.js';
import { dbfs } from './dsp.js';
import { profileHomogeneity } from './verifier.js';

const $ = (id) => document.getElementById(id);
const mostra = (id, visibile) => $(id).classList.toggle('nascosta', !visibile);

const sessione = new Sessione({ onEvento: gestisciEvento });
let wakeLock = null;
let inAscolto = false;

// ---------------------------------------------------------------- avvisi
function avviso(testo, grave = false) {
  const el = document.createElement('div');
  el.className = 'avviso' + (grave ? ' grave' : '');
  el.textContent = testo;
  $('avvisi').appendChild(el);
}

function controllaCompatibilita() {
  $('avvisi').innerHTML = '';
  if (!window.isSecureContext) {
    avviso('Questa pagina va aperta in https, altrimenti il browser non da\' accesso al microfono.', true);
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    avviso('Questo browser non da\' accesso al microfono.', true);
  }
  if (!trascrizioneDisponibile()) {
    avviso('Questo browser non sa trascrivere la voce. Su iPhone Safari non lo supporta: '
         + 'prova con Chrome, oppure usa la modalita\' con il computer.', true);
  }
  if (!sintesiDisponibile()) avviso('Questo browser non sa parlare: leggerai le risposte.');
}

// --------------------------------------------------------- schermata avvio
function disegnaPassi() {
  const passi = [
    {
      fatto: sessione.haChiave,
      titolo: 'Chiave di Claude',
      nota: sessione.haChiave ? 'impostata' : 'serve per far ragionare l\'assistente',
      azione: sessione.haChiave ? null : { testo: 'Inserisci la chiave', fn: apriImpostazioni },
    },
    {
      fatto: sessione.arruolato,
      titolo: 'La tua voce',
      nota: sessione.arruolato
        ? `${sessione.profilo.size} impronte registrate`
        : 'otto frasi, un minuto: e\' cosi' + '’ che impara a riconoscere te',
      azione: sessione.arruolato ? null : { testo: 'Registra la voce', fn: avviaArruolamento },
    },
    {
      fatto: sessione.listone.length > 0,
      titolo: 'Listone (facoltativo)',
      nota: sessione.listone.length
        ? `${sessione.listone.length} giocatori caricati`
        : 'senza, parla di strategia ma non di quotazioni',
      azione: sessione.listone.length ? null : { testo: 'Carica il CSV', fn: apriImpostazioni },
    },
  ];

  const ol = $('passi');
  ol.innerHTML = '';
  for (const [i, p] of passi.entries()) {
    const li = document.createElement('li');
    li.className = 'passo' + (p.fatto ? ' fatto' : '');
    const num = document.createElement('div');
    num.className = 'passo-num';
    num.textContent = p.fatto ? '✓' : String(i + 1);
    const testo = document.createElement('div');
    testo.className = 'passo-testo';
    const t = document.createElement('div'); t.className = 'passo-titolo'; t.textContent = p.titolo;
    const n = document.createElement('div'); n.className = 'passo-nota'; n.textContent = p.nota;
    testo.append(t, n);
    if (p.azione) {
      const b = document.createElement('button');
      b.className = 'primario'; b.textContent = p.azione.testo;
      b.onclick = p.azione.fn;
      testo.appendChild(b);
    }
    li.append(num, testo);
    ol.appendChild(li);
  }

  if (sessione.haChiave && sessione.arruolato) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'primario';
    b.textContent = 'Tutto pronto: comincia';
    b.onclick = () => { mostraSchermata('ascolto'); };
    li.appendChild(b);
    ol.appendChild(li);
  }
}

function mostraSchermata(quale) {
  mostra('schermata-avvio', quale === 'avvio');
  mostra('schermata-voce', quale === 'voce');
  mostra('schermata-ascolto', quale === 'ascolto');
  if (quale === 'avvio') disegnaPassi();
}

// ------------------------------------------------------- arruolamento
const arruolamento = { indice: 0, microfono: null, campioni: [], registrando: false };

async function avviaArruolamento() {
  arruolamento.indice = 0;
  sessione.dimenticaVoce();
  mostraSchermata('voce');
  disegnaFrase();
  try {
    arruolamento.microfono = new Microfono((frame) => {
      if (arruolamento.registrando) arruolamento.campioni.push(frame);
    });
    await arruolamento.microfono.avvia();
    $('stato-registrazione').textContent = 'Tieni premuto il pulsante mentre leggi.';
  } catch (e) {
    $('stato-registrazione').textContent = messaggioMicrofono(e);
  }
}

function messaggioMicrofono(e) {
  if (e?.name === 'NotAllowedError') {
    return 'Microfono negato. Nelle impostazioni del sito consenti il microfono e ricarica.';
  }
  if (!window.isSecureContext) return 'Serve https: controlla l\'indirizzo.';
  return 'Non riesco ad aprire il microfono: ' + (e?.message || e);
}

function disegnaFrase() {
  const n = FRASI_ARRUOLAMENTO.length;
  $('frase-corrente').textContent = '«' + FRASI_ARRUOLAMENTO[arruolamento.indice] + '»';
  $('contatore-frasi').textContent = `Frase ${arruolamento.indice + 1} di ${n}`;
  $('barra-progresso').style.width = `${(arruolamento.indice / n) * 100}%`;
}

function iniziaRegistrazione() {
  if (!arruolamento.microfono?.ctx) return;
  arruolamento.campioni = [];
  arruolamento.registrando = true;
  $('registra').classList.add('attivo');
  $('registra').textContent = 'Sto registrando... rilascia quando hai finito';
  $('stato-registrazione').textContent = 'Registrazione in corso';
  $('stato-registrazione').className = 'stato-reg registra';
}

function fineRegistrazione() {
  if (!arruolamento.registrando) return;
  arruolamento.registrando = false;
  $('registra').classList.remove('attivo');
  $('registra').textContent = 'Tieni premuto e leggi';
  $('stato-registrazione').className = 'stato-reg';

  const totale = arruolamento.campioni.reduce((n, c) => n + c.length, 0);
  const audio = new Float32Array(totale);
  let off = 0;
  for (const c of arruolamento.campioni) { audio.set(c, off); off += c.length; }
  arruolamento.campioni = [];

  const durata = audio.length / SR;
  if (durata < 1.5) {
    $('stato-registrazione').textContent = 'Troppo corta: tieni premuto per tutta la frase.';
    return;
  }
  const livello = dbfs(audio);
  if (livello < -45) {
    $('stato-registrazione').textContent = 'Audio troppo basso: avvicina il microfono e ripeti.';
    return;
  }
  if (livello > -6) {
    $('stato-registrazione').textContent = 'Audio troppo forte, distorce: allontanati e ripeti.';
    return;
  }

  const aggiunte = sessione.aggiungiFraseArruolamento(audio);
  if (!aggiunte) {
    $('stato-registrazione').textContent = 'Non ho sentito voce: riprova.';
    return;
  }

  arruolamento.indice++;
  if (arruolamento.indice >= FRASI_ARRUOLAMENTO.length) return concludiArruolamento();
  disegnaFrase();
  $('stato-registrazione').textContent = `Ok (${durata.toFixed(1)}s). Avanti con la prossima.`;
}

function concludiArruolamento() {
  arruolamento.microfono?.ferma();
  arruolamento.microfono = null;
  $('barra-progresso').style.width = '100%';

  const soglie = sessione.concludiArruolamento();
  const omogeneita = profileHomogeneity(sessione.profilo);

  mostraSchermata('avvio');
  $('avvisi').innerHTML = '';
  if (!omogeneita.clean) {
    avviso(omogeneita.note, true);
  } else if (soglie.note !== 'calibrazione riuscita') {
    avviso(soglie.note);
  } else {
    avviso(`Voce registrata: ${sessione.profilo.size} impronte, soglia calibrata a ${soglie.acceptThreshold}.`);
  }
}

// ------------------------------------------------------------- ascolto
function stato(classe, testo, nota) {
  $('spia').className = classe;
  $('stato-testo').textContent = testo;
  if (nota !== undefined) $('stato-nota').textContent = nota;
}

function riga(tipo, testo, meta) {
  const el = document.createElement('div');
  el.className = 'riga ' + tipo;
  el.textContent = testo;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta'; m.textContent = meta;
    el.appendChild(m);
  }
  const box = $('conversazione');
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  while (box.children.length > 80) box.removeChild(box.firstChild);
  return el;
}

let rigaBot = null;

function gestisciEvento(e) {
  switch (e.tipo) {
    case 'pronto':
      stato('attiva', 'In ascolto', 'Rispondo solo alla tua voce');
      riga('sys', 'Collegato. Parla pure.');
      break;
    case 'io':
      if (!sessione.staParlando) stato('io', 'Ti sto ascoltando', `punteggio ${e.punteggio.toFixed(2)}`);
      break;
    case 'altri':
      stato('altri', 'Voce ignorata', `non sei tu: ${e.punteggio.toFixed(2)}`);
      break;
    case 'trascritto':
      riga('tu', e.testo, `voce riconosciuta (${Math.round(e.quota * 100)}% delle finestre)`);
      stato('parla', 'Sto rispondendo', '');
      rigaBot = null;
      break;
    case 'ignorato':
      riga('scartata', e.testo, e.motivo);
      break;
    case 'dice':
      if (!rigaBot) rigaBot = riga('bot', e.testo);
      else rigaBot.firstChild.textContent += ' ' + e.testo;
      break;
    case 'interrotto':
      riga('sys', 'Interrotto: hai ripreso la parola');
      break;
    case 'finito':
      rigaBot = null;
      stato('attiva', 'In ascolto', 'Rispondo solo alla tua voce');
      break;
    case 'errore':
      riga('sys', 'Errore: ' + e.testo);
      break;
    case 'fermo':
      stato('', 'Fermo', 'Tocca Avvia per riprendere');
      break;
  }
}

async function tieniSveglio() {
  try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); }
  catch { /* non supportato: pazienza */ }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && inAscolto && !wakeLock) tieniSveglio();
});

async function alternaAscolto() {
  if (inAscolto) {
    sessione.ferma();
    inAscolto = false;
    wakeLock?.release?.().catch(() => {});
    wakeLock = null;
    $('ascolta').textContent = 'Avvia';
    $('ascolta').classList.remove('attivo');
    $('zitto').disabled = true;
    return;
  }
  try {
    await sessione.avvia();
    await tieniSveglio();
    inAscolto = true;
    $('ascolta').textContent = 'Ferma';
    $('ascolta').classList.add('attivo');
    $('zitto').disabled = false;
  } catch (e) {
    riga('sys', messaggioMicrofono(e));
  }
}

// -------------------------------------------------------- impostazioni
function apriImpostazioni() {
  $('api-key').value = archivio.leggi(CHIAVI.apiKey, '') || '';
  $('budget').value = sessione.config.budget;
  $('stato-listone').textContent = sessione.listone.length
    ? `${sessione.listone.length} giocatori caricati`
    : 'nessun listone: l\'assistente non avra\' le quotazioni';
  $('diagnostica').textContent =
    `voce di sistema: ${sessione.voce.nomeVoce} · trascrizione: `
    + `${trascrizioneDisponibile() ? 'disponibile' : 'non disponibile'}`;
  mostra('pannello', true);
  mostra('velo', true);
}

function chiudiImpostazioni() {
  const chiave = $('api-key').value.trim();
  if (chiave) sessione.salvaChiave(chiave); else sessione.dimenticaChiave();
  const budget = parseInt($('budget').value, 10);
  if (Number.isFinite(budget) && budget > 0) sessione.impostaBudget(budget);
  mostra('pannello', false);
  mostra('velo', false);
  disegnaPassi();
}

// ------------------------------------------------------------- eventi
$('apri-impostazioni').onclick = apriImpostazioni;
$('chiudi-impostazioni').onclick = chiudiImpostazioni;
$('velo').onclick = chiudiImpostazioni;

$('file-listone').onchange = async (ev) => {
  const file = ev.target.files?.[0];
  if (!file) return;
  try {
    const quanti = sessione.caricaListoneCSV(await file.text());
    $('stato-listone').textContent = `${quanti} giocatori caricati`;
  } catch (e) {
    $('stato-listone').textContent = 'Non riesco a leggerlo: ' + e.message;
  }
};

$('azzera-asta').onclick = () => {
  if (!confirm('Azzero budget e rosa di questa asta?')) return;
  sessione.azzeraAsta();
  $('stato-listone').textContent = 'Asta azzerata.';
};

$('rifai-voce').onclick = () => {
  if (!confirm('Cancello il profilo vocale e ricomincio la registrazione?')) return;
  chiudiImpostazioni();
  avviaArruolamento();
};

$('cancella-tutto').onclick = () => {
  if (!confirm('Cancello TUTTO: voce, chiave, listone e asta. Sicuro?')) return;
  Object.values(CHIAVI).forEach(archivio.cancella);
  location.reload();
};

// Registrazione a pressione: dito giu' registra, dito su' conclude.
const bottoneReg = $('registra');
['pointerdown'].forEach((e) => bottoneReg.addEventListener(e, (ev) => {
  ev.preventDefault(); iniziaRegistrazione();
}));
['pointerup', 'pointercancel', 'pointerleave'].forEach((e) =>
  bottoneReg.addEventListener(e, (ev) => { ev.preventDefault(); fineRegistrazione(); }));

$('annulla-voce').onclick = () => {
  arruolamento.microfono?.ferma();
  arruolamento.microfono = null;
  mostraSchermata('avvio');
};

$('ascolta').onclick = alternaAscolto;
$('zitto').onclick = () => {
  sessione.voce.zitto();
  sessione.annullaRisposta?.abort();
};

// ------------------------------------------------------------- avvio
controllaCompatibilita();
mostraSchermata(sessione.haChiave && sessione.arruolato ? 'ascolto' : 'avvio');
if (sessione.haChiave && sessione.arruolato) {
  stato('', 'Pronto', 'Tocca Avvia');
}

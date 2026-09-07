// Numeri detti a voce.
//
// Il riconoscimento vocale a volte scrive "180" e a volte "centottanta": in
// asta si dettano prezzi in continuazione, quindi vanno capiti entrambi.
// In italiano i numeri si scrivono attaccati ("duecentocinquanta"), quindi non
// basta cercare parole separate: bisogna scandire dentro la parola.

const VALORI = [
  ['mille', 1000], ['mila', 1000], ['cento', 100],
  // "cent" senza la o finale: in italiano cade davanti a otto e undici
  // ("centottanta", non "centoottanta"), ed e' la ragione per cui questo
  // parser deve poter tornare sui suoi passi invece di prendere sempre il
  // prefisso piu' lungo.
  ['cent', 100],
  ['novanta', 90], ['ottanta', 80], ['settanta', 70], ['sessanta', 60],
  ['cinquanta', 50], ['quaranta', 40], ['trenta', 30], ['venti', 20],
  // Forme elise davanti a uno e otto: "ventuno", "trentotto", "quarantuno".
  ['novant', 90], ['ottant', 80], ['settant', 70], ['sessant', 60],
  ['cinquant', 50], ['quarant', 40], ['trent', 30], ['vent', 20],
  ['diciannove', 19], ['diciotto', 18], ['diciassette', 17], ['sedici', 16],
  ['quindici', 15], ['quattordici', 14], ['tredici', 13], ['dodici', 12],
  ['undici', 11], ['dieci', 10],
  ['nove', 9], ['otto', 8], ['sette', 7], ['sei', 6], ['cinque', 5],
  ['quattro', 4], ['tre', 3], ['due', 2], ['uno', 1], ['una', 1], ['un', 1],
].sort((a, b) => b[0].length - a[0].length);   // si prova prima il piu' lungo

/**
 * Scandisce la parola provando tutte le divisioni possibili.
 *
 * Prendere sempre il prefisso piu' lungo non basta: in "centottanta" il
 * prefisso piu' lungo e' "cento", ma la divisione giusta e' "cent" + "ottanta".
 * Quindi si prova, e se il resto non si interpreta si torna indietro.
 */
function scandisci(resto, totale, corrente) {
  if (!resto.length) return totale + corrente;

  for (const [prefisso, valore] of VALORI) {
    if (!resto.startsWith(prefisso)) continue;
    let t = totale, c = corrente;
    if (valore === 1000) { t += (c || 1) * 1000; c = 0; }
    else if (valore === 100) { c = (c || 1) * 100; }
    else { c += valore; }
    const esito = scandisci(resto.slice(prefisso.length), t, c);
    if (esito !== null) return esito;
  }
  return null;
}

/** Converte una parola-numero italiana in cifra. Restituisce null se non lo e'. */
export function parolaInNumero(parola) {
  if (!parola) return null;
  return scandisci(parola, 0, 0);
}

/**
 * Estrae il primo numero da una frase, in cifre o in lettere.
 *
 * Cerca le cifre per prime perche' sono inequivocabili; solo se non ce ne sono
 * prova a interpretare le parole.
 */
export function estraiNumero(testo) {
  const cifre = String(testo).match(/\d+/);
  if (cifre) return parseInt(cifre[0], 10);
  for (const parola of String(testo).toLowerCase().split(/[\s,.;:!?]+/)) {
    const n = parolaInNumero(parola);
    if (n !== null && n > 0) return n;
  }
  return null;
}

const UNITA = ['zero', 'uno', 'due', 'tre', 'quattro', 'cinque', 'sei', 'sette', 'otto', 'nove',
               'dieci', 'undici', 'dodici', 'tredici', 'quattordici', 'quindici', 'sedici',
               'diciassette', 'diciotto', 'diciannove'];
const DECINE = ['', '', 'venti', 'trenta', 'quaranta', 'cinquanta', 'sessanta', 'settanta',
                'ottanta', 'novanta'];

/**
 * Numero in lettere, per farlo pronunciare bene.
 *
 * La voce sintetica legge "180" come "centottanta" da sola, ma sbaglia i tagli
 * di frase e i prezzi vanno detti scorrevoli: meglio scriverli in lettere.
 */
export function numeroInParola(n) {
  n = Math.round(n);
  if (n < 0) return 'meno ' + numeroInParola(-n);
  if (n < 20) return UNITA[n];
  if (n < 100) {
    const d = Math.floor(n / 10), u = n % 10;
    let base = DECINE[d];
    if (u === 1 || u === 8) base = base.slice(0, -1);   // ventuno, ventotto
    return base + (u ? UNITA[u] : '');
  }
  if (n < 1000) {
    const c = Math.floor(n / 100), resto = n % 100;
    const testa = c === 1 ? 'cento' : UNITA[c] + 'cento';
    // centottanta, non "centoottanta"
    const coda = resto ? numeroInParola(resto) : '';
    return testa.endsWith('o') && coda.startsWith('o') ? testa.slice(0, -1) + coda : testa + coda;
  }
  const migliaia = Math.floor(n / 1000), resto = n % 1000;
  const testa = migliaia === 1 ? 'mille' : numeroInParola(migliaia) + 'mila';
  return testa + (resto ? numeroInParola(resto) : '');
}

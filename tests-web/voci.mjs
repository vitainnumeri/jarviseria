// Voci sintetiche per i test: modello sorgente-filtro.
//
// Impulsi glottali a una data frequenza fondamentale, filtrati da tre formanti.
// E' il modo in cui funziona davvero l'apparato fonatorio, quindi due "persone"
// con F0 e formanti diverse suonano diverse per le stesse ragioni per cui lo
// sono due persone vere - molto piu' onesto che confrontare rumori a caso.

export const SR = 16000;

export const PERSONE = [
  { nome: 'proprietario', f0: 115, formanti: [[700, 80], [1220, 90], [2600, 120]] },
  { nome: 'donna acuta',  f0: 190, formanti: [[820, 80], [1900, 90], [2900, 120]] },
  { nome: 'uomo medio',   f0: 145, formanti: [[600, 80], [1050, 90], [2400, 120]] },
  { nome: 'voce acuta',   f0: 230, formanti: [[900, 80], [2100, 90], [3000, 120]] },
  { nome: 'uomo grave',   f0: 100, formanti: [[650, 80], [1150, 90], [2500, 120]] },
  { nome: 'simile a me',  f0: 135, formanti: [[720, 80], [1300, 90], [2650, 120]] },
];

export function voce(f0, formanti, secondi, ampiezza = 0.25, seme = 1) {
  const n = Math.floor(secondi * SR);
  const sorgente = new Float32Array(n);
  let fase = 0, rnd = seme;
  for (let i = 0; i < n; i++) {
    rnd = (rnd * 1103515245 + 12345) & 0x7fffffff;
    const jitter = 1 + (rnd / 0x7fffffff - 0.5) * 0.02;  // la voce non e' un metronomo
    fase += (f0 * jitter) / SR;
    if (fase >= 1) { fase -= 1; sorgente[i] = 1; }
    sorgente[i] += (rnd / 0x7fffffff - 0.5) * 0.01;      // soffio
  }
  const out = new Float32Array(n);
  for (const [fc, bw] of formanti) {
    const r = Math.exp((-Math.PI * bw) / SR), th = (2 * Math.PI * fc) / SR;
    const a1 = 2 * r * Math.cos(th), a2 = -r * r;
    let y1 = 0, y2 = 0;
    for (let i = 0; i < n; i++) {
      const y = sorgente[i] + a1 * y1 + a2 * y2;
      out[i] += y; y2 = y1; y1 = y;
    }
  }
  let max = 0;
  for (let i = 0; i < n; i++) max = Math.max(max, Math.abs(out[i]));
  for (let i = 0; i < n; i++) out[i] = (out[i] / max) * ampiezza;
  return out;
}

/** Audio della persona indicata. `seme` cambia la frase, non la voce. */
export const parla = (persona, secondi = 3, seme = 1, ampiezza = 0.25) =>
  voce(PERSONE[persona].f0, PERSONE[persona].formanti, secondi, ampiezza, seme);

export const silenzio = (secondi) => new Float32Array(Math.floor(secondi * SR));

// La scala verticale: la tabella con i due estremi.
//
// Serve in tre vesti diverse - a chi da' l'indizio (con il bersaglio in
// mostra), a chi tira (vuota, si tocca e si trascina) e alla rivelazione
// (ferma, con tutti i segni sopra) - quindi e' un pezzo solo, comandato da
// fuori.

const ALTEZZA_TACCHE = 10; // una tacca ogni 10 punti di scala

function crea(tag, classe, testo) {
  const nodo = document.createElement(tag);
  if (classe) nodo.className = classe;
  if (testo != null) nodo.textContent = testo;
  return nodo;
}

export function creaScala({ interattiva = false, onCambio = null } = {}) {
  const nodo = crea('div', 'scala');
  const alto = crea('div', 'estremo alto');
  const basso = crea('div', 'estremo basso');
  const zona = crea('div', 'pista-zona');
  const pista = crea('div', 'pista');
  const tacche = crea('div', 'tacche');
  const segni = crea('div', 'segni');
  const maniglia = crea('div', 'maniglia');
  maniglia.append(crea('div', 'filo'), crea('div', 'pomello'));
  maniglia.hidden = true;

  for (let v = ALTEZZA_TACCHE; v < 100; v += ALTEZZA_TACCHE) {
    const tacca = crea('div', 'tacca');
    tacca.style.top = `${v}%`;
    tacche.append(tacca);
  }

  // I segni e la maniglia stanno sopra la pista ma fuori dal suo ritaglio:
  // un tiro a filo di 0 o di 100 deve mostrare la targhetta per intero.
  pista.append(tacche);
  zona.append(pista, segni, maniglia);
  nodo.append(alto, zona, basso);

  let valore = null;
  let attiva = interattiva;
  let contaSegni = 0;

  if (interattiva) {
    pista.classList.add('viva');
    pista.tabIndex = 0;
    pista.setAttribute('role', 'slider');
    pista.setAttribute('aria-orientation', 'vertical');
    pista.setAttribute('aria-valuemin', '0');
    pista.setAttribute('aria-valuemax', '100');
    pista.setAttribute('aria-label', 'Scegli il punto sulla scala');
  }

  function daPuntatore(evento) {
    const zona = pista.getBoundingClientRect();
    const grezzo = ((evento.clientY - zona.top) / zona.height) * 100;
    return Math.min(100, Math.max(0, Math.round(grezzo)));
  }

  function imponi(nuovo, avvisa = true) {
    valore = Math.min(100, Math.max(0, Math.round(nuovo)));
    maniglia.hidden = false;
    maniglia.style.top = `${valore}%`;
    if (interattiva) {
      pista.setAttribute('aria-valuenow', String(valore));
      pista.setAttribute('aria-valuetext',
        `${valore} su 100, da ${alto.textContent} in cima a ${basso.textContent} in fondo`);
    }
    if (avvisa && onCambio) onCambio(valore);
  }

  if (interattiva) {
    const muovi = evento => {
      if (!attiva) return;
      evento.preventDefault();
      imponi(daPuntatore(evento));
    };
    pista.addEventListener('pointerdown', evento => {
      if (!attiva) return;
      pista.setPointerCapture(evento.pointerId);
      pista.classList.add('in-mano');
      muovi(evento);
    });
    pista.addEventListener('pointermove', evento => {
      if (pista.hasPointerCapture?.(evento.pointerId)) muovi(evento);
    });
    const molla = evento => {
      pista.classList.remove('in-mano');
      if (pista.hasPointerCapture?.(evento.pointerId)) pista.releasePointerCapture(evento.pointerId);
    };
    pista.addEventListener('pointerup', molla);
    pista.addEventListener('pointercancel', molla);

    pista.addEventListener('keydown', evento => {
      if (!attiva) return;
      const partenza = valore == null ? 50 : valore;
      const passi = { ArrowUp: -1, ArrowDown: 1, PageUp: -10, PageDown: 10 };
      if (evento.key in passi) imponi(partenza + passi[evento.key]);
      else if (evento.key === 'Home') imponi(0);
      else if (evento.key === 'End') imponi(100);
      else return;
      evento.preventDefault();
    });
  }

  return {
    nodo,

    /** Scrive i due estremi in cima e in fondo. */
    coppia({ alto: sopra, basso: sotto }) {
      alto.textContent = sopra;
      basso.textContent = sotto;
    },

    /** Il punto scelto, oppure null se non e' ancora stato toccato niente. */
    valore: () => valore,

    imponi,

    /** Toglie i segni e la maniglia: la scala torna vuota. */
    pulisci() {
      segni.textContent = '';
      segni.classList.remove('folto');
      contaSegni = 0;
      valore = null;
      maniglia.hidden = true;
      pista.removeAttribute('aria-valuenow');
      pista.removeAttribute('aria-valuetext');
    },

    /**
     * Posa un segno fisso sulla scala.
     * @param {object} p  { valore, etichetta, tipo: 'bersaglio'|'tiro' }
     */
    segna({ valore: v, etichetta = '', tipo = 'tiro' }) {
      const segno = crea('div', `segno ${tipo}`);
      segno.style.top = `${Math.min(100, Math.max(0, v))}%`;
      // Le etichette si alternano a destra e a sinistra: con sei giocatori
      // capita spesso che due tiri finiscano quasi alla stessa altezza.
      segno.classList.add(contaSegni % 2 === 0 ? 'a-destra' : 'a-sinistra');
      contaSegni += 1;
      segni.classList.toggle('folto', contaSegni > 7);
      segno.append(crea('div', 'filo-segno'));
      if (etichetta) segno.append(crea('span', 'targhetta', etichetta));
      segni.append(segno);
      return segno;
    },

    /** Accende o spegne il tocco (a rivelazione fatta la scala si blocca). */
    abilita(si) {
      attiva = si && interattiva;
      pista.classList.toggle('spenta', !attiva);
    },
  };
}

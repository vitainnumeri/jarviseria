# JarvisEria — versione telefono

Questa cartella e' l'applicazione che gira **interamente nel telefono**. Viene
pubblicata su GitHub Pages, quindi si apre da un indirizzo `https://` normale:
nessun computer acceso, nessun certificato da accettare, niente da installare.

## Come attivarla (una volta sola)

1. Vai su **Settings → Pages** del repository.
2. In *Source* scegli **Deploy from a branch**.
3. Branch: quello di questo lavoro; cartella: **`/docs`**.
4. Salva. Dopo un minuto l'app e' a
   `https://vitainnumeri.github.io/jarviseria/`.

Poi dal telefono apri quell'indirizzo e, se vuoi, **Aggiungi a schermata Home**:
diventa un'icona come un'app vera.

## Cosa gira dove

| Pezzo | Dove |
|---|---|
| Riconoscimento della tua voce | **nel telefono** (non esce mai) |
| Rilevamento del parlato, MFCC, pitch | **nel telefono** |
| Motore d'asta e di formazione | **nel telefono** |
| Trascrizione | riconoscimento vocale del browser (su Chrome passa da Google) |
| Ragionamento | API di Claude (ci va il testo, non l'audio) |
| Voce sintetica | **nel telefono** (voce di sistema) |

## File

```
index.html      la pagina
stile.css       l'aspetto
manifest.json   per l'icona sulla schermata Home
js/dsp.js       MFCC, pitch, livelli, rumore di fondo
js/verifier.js  profilo vocale, coorte, decisione            <- il cuore
js/fanta.js     listone, motore d'asta, motore di formazione
js/strumenti.js gli strumenti che l'assistente puo' chiamare
js/llm.js       client di Claude in streaming, con ciclo strumenti
js/voce.js      trascrizione e sintesi del sistema
js/prompt.js    le istruzioni dell'assistente
js/app.js       orchestrazione: incrocia biometria e trascrizione
js/ui.js        interfaccia
```

Nessun passo di compilazione e nessuna dipendenza: sono moduli ES che il
browser carica cosi' come sono. E' voluto — meno pezzi ci sono, meno cose
possono rompersi fra te e l'asta.

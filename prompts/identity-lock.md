# Identity lock — far restare il volto *suo*

Il problema numero uno di queste clip: lo Shot 1 è perfettamente lui, e tre
generazioni dopo è un tizio qualunque con la stessa pettinatura. Il modello non
"ricorda" un volto tra una generazione e l'altra — va riancorato ogni volta.

## Il principio che risolve metà del problema

**La trasformazione deve cambiare tutto tranne i tratti del viso.**

È controintuitivo, perché l'istinto è descrivere un mostro. Ma se il volto si
deforma, l'effetto comico sparisce: non è più il tuo amico trasformato, è una
creatura. Quello che deve cambiare è *intorno* al viso — dimensione, pelle,
arcata sopraccigliare, mascella. La geometria che lo rende riconoscibile
(distanza tra gli occhi, forma del naso, proporzioni degli zigomi) resta ferma.

Detto al modello, esplicitamente, in ogni prompt.

## [IDENTITY] — blocco fisso

Incollalo in **ogni** generazione, insieme a `[CHARACTER]`:

```
CRITICAL — facial identity: the face must remain unmistakably the reference
person. Preserve exactly: the distance between the eyes, the shape and width of
the nose, the cheekbone structure, the shape of the jawline, the hairline, the
set of the mouth. These do not change at any point in the shot. Only the skin
material, the scale, the brow ridge and the jaw width change around them. A
viewer who knows this person must recognize him instantly in every frame.
```

## Negative prompt

Se il preset che usi ha un campo per il negative prompt:

```
different person, generic face, face morphing, shifting facial features,
symmetrical idealized face, model face, plastic skin, face drifting between
frames, changed nose, changed eye spacing
```

`symmetrical idealized face` è il più importante: i modelli video tendono a
"migliorare" i volti verso una media bella e anonima. È esattamente ciò che
distrugge la somiglianza.

## Tecnica: riancorare a ogni shot

Non basta la foto sul primo shot.

1. **Ogni** generazione riceve la foto frontale come reference, anche gli shot
   3 e 4 dove il personaggio è già trasformato.
2. Se il preset accetta più immagini, dagli frontale + tre quarti + profilo.
   Il volto regge molto meglio sulle rotazioni della testa.
3. Se accetta un peso per la reference (identity strength / similarity), tienilo
   **alto**: 0.8–0.9. Sotto 0.6 la somiglianza evapora.
4. Per gli shot in sequenza, usa come immagine di partenza l'ultimo frame dello
   shot precedente — ma **aggiungi comunque** la foto originale come reference.
   Solo l'ultimo frame non basta: gli errori si accumulano di shot in shot.

## Inquadrature: cosa aiuta e cosa no

| Aiuta | Danneggia |
|---|---|
| Volto grande nel frame | Campi lunghi, volto piccolo |
| Luce frontale o a 45° | Controluce, volto in ombra |
| Testa relativamente ferma | Rotazioni rapide della testa |
| 3–4 secondi | Clip lunghe |

Se ti serve assolutamente un campo lungo, generalo **dopo** aver fissato un buon
primo piano, e usa quel frame come reference.

## Controllo qualità

Metti il frame generato e la foto originale **affiancati**, a dimensione piena.
A schermo piccolo sembrano sempre uguali. Guarda nell'ordine: distanza tra gli
occhi, larghezza del naso, linea della mascella. Se uno dei tre è sbagliato,
rigenera — non passare allo shot successivo sperando che si sistemi. Non si
sistema, peggiora.

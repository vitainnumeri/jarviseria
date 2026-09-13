# Workflow

## Prima di iniziare

1. Scegli **una** variante da `docs/personaggio.md` e non cambiarla più.
2. Metti le foto in `reference/` (restano in locale, vedi il README lì dentro).
3. Apri `results/LOG.md` e tienilo aperto mentre lavori. Annotare i parametri
   mentre generi costa dieci secondi; ricostruirli dopo è impossibile.

## Ordine delle generazioni

Non in ordine di montaggio. In ordine di difficoltà crescente:

| # | Shot | Perché in questa posizione |
|---|---|---|
| 1 | **Shot 3** — il reveal, camera ferma | Il più facile. Ti dice subito se il design regge. Se il colosso non funziona qui, non funzionerà da nessuna parte: cambia variante prima di bruciare crediti. |
| 2 | **Shot 2** — la trasformazione | Il più difficile, ed è il cuore della clip. Affrontalo quando sai già che il personaggio tiene. |
| 3 | **Shot 1** — il preludio | Facile, ma va generato dopo perché deve raccordarsi allo Shot 2. |
| 4 | **Shot 4** — la vetrata | Indipendente dagli altri. Falla per ultima, con calma. |

## Regole che fanno la differenza

**Uno shot alla volta, brevi.** Tre-quattro secondi ciascuno. Su clip più
lunghe i modelli perdono coerenza a metà e il personaggio deriva.

**Il blocco `[CHARACTER]` identico ogni volta.** Copiato e incollato, non
riscritto a memoria. È l'unica cosa che tiene insieme il design tra le
generazioni.

**La foto di riferimento anche negli shot successivi**, non solo nel primo.
È quello che impedisce al volto di diventare di qualcun altro a metà sequenza.

**Genera più varianti dello stesso prompt** prima di modificarlo. Spesso il
prompt era giusto e il seed era sfortunato. Cambiare il testo dopo un solo
tentativo fallito ti fa inseguire il problema sbagliato.

**Annota i seed dei tentativi riusciti.** Sono l'unica cosa che ti permette di
tornare indietro.

## Montaggio

Higgsfield genera gli shot, non li monta. Per unirli serve un editor —
DaVinci Resolve è gratuito e sufficiente. Taglia sul movimento: lo stacco tra
Shot 2 e Shot 3 funziona meglio se cade **durante** un gesto, non dopo.

Il suono fa metà del lavoro e viene sempre trascurato: un impatto grave sulla
rottura del vetro e un sub-bass sotto la trasformazione alzano il risultato
percepito più di qualsiasi rigenerazione.

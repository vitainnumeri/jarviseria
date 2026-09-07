# Via di mezzo

Gioco di gruppo da passarsi al telefono. Da 3 a 12 giocatori, un telefono solo,
niente da installare: e' una pagina web che gira tutta nel browser.

## Come si gioca

Ogni round c'e' una scala verticale con due estremi, per esempio **Buono** in
cima e **Cattivo** in fondo.

1. **Chi da' l'indizio guarda.** Il telefono passa a lui, che tiene premuto per
   scoprire un punto segreto sulla scala. Dice a voce una parola o una frase
   che secondo lui sta esattamente in quel punto, e la scrive.
2. **Il telefono gira.** Ognuno degli altri, a turno, tocca il punto dove crede
   che sia il bersaglio. Non vede ne' il punto segreto ne' i tiri di chi lo ha
   preceduto: fra un giocatore e l'altro c'e' sempre una schermata di
   passaggio, e il bersaglio non resta scritto da nessuna parte nella pagina.
3. **Si scopre tutto.** Compaiono il bersaglio e tutti i tiri, con i punti.

Poi tocca al giocatore dopo dare l'indizio, e cosi' via: in una partita
"normale" ognuno lo da' due volte.

## I punti

Quanto vale un tiro, in base allo scarto dal bersaglio sulla scala 0-100:

| Scarto | Punti | |
|---|---|---|
| fino a 4 | 5 | In pieno |
| fino a 9 | 4 | Vicinissimo |
| fino a 16 | 3 | Ci siamo |
| fino a 25 | 2 | Nella zona |
| fino a 36 | 1 | Lontanuccio |
| oltre | 0 | Fuori strada |

Chi ha dato l'indizio prende la **media** dei punti di chi lo ha ascoltato:
non conviene un indizio che capisce una persona sola.

## Come si apre

La cartella `docs/` e' l'intero gioco: HTML, CSS e moduli JavaScript, nessuna
dipendenza. Serve un server statico qualsiasi, perche' i moduli ES non si
caricano da `file://`:

```sh
cd docs && python3 -m http.server 8777    # poi http://localhost:8777
```

Pubblicata su GitHub Pages (sorgente: la cartella `docs/`) si aggiunge alla
schermata del telefono e si apre a tutto schermo.

La partita in corso viene salvata nel telefono: se la pagina si ricarica per
sbaglio, si riprende dal punto esatto in cui era.

## Com'e' fatto

| File | |
|---|---|
| `docs/js/gioco.js` | le regole: stato, turni, bersaglio, punteggi. Nessun DOM. |
| `docs/js/coppie.js` | il mazzo delle coppie di estremi. |
| `docs/js/scala.js` | la scala verticale: tocco, trascinamento, tastiera. |
| `docs/js/ui.js` | schermate, passaggi di mano, salvataggio. |

Le regole stanno in un modulo a parte proprio per poterle provare senza
browser:

```sh
npm test
```

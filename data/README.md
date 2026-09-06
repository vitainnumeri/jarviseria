# Dati

## `esempio_listone_PLACEHOLDER.csv`

File di esempio, **non ufficiale**. Serve solo a far girare i test e a provare i
comandi senza avere sotto mano l'export vero.

I nomi dei giocatori e delle squadre sono reali; **le quotazioni e i valori FVM
sono inventati** e non corrispondono a nessuna stagione. Non usarli per decidere
un'asta.

## Come ottenere il listone vero

1. Scarica le quotazioni ufficiali della stagione da
   [fantacalcio.it/quotazioni-fantacalcio](https://www.fantacalcio.it/quotazioni-fantacalcio)
   (file `.xlsx`).
2. Salvalo come CSV con separatore `;` (da Excel: *Salva con nome → CSV UTF-8*).
3. Mettilo in `data/listone.csv`, oppure indica il percorso in `config/local.yaml`:

   ```yaml
   fanta:
     listone_path: /percorso/al/mio/listone.csv
   ```

Il caricatore riconosce le intestazioni ufficiali (`Id`, `R`, `RM`, `Nome`,
`Squadra`, `Qt.A`, `Qt.I`, `FVM`) e diverse varianti, quindi non serve
rimaneggiare il file a mano. Colonne aggiuntive di statistiche (`Fm`, `Mv`,
`Pv`, `Gf`, `Ass`) vengono usate se presenti.

Il file `data/listone.csv` e' escluso da git: i tuoi dati restano tuoi.

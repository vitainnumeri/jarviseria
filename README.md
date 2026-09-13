# Progetto "Trasformazione" — archivio prompt

Generazione di una clip originale su **Higgsfield**: una persona normale si
trasforma in un colosso e sfonda una vetrata.

Questo repo **non contiene video**. È l'archivio della parte che si perde
sempre: i prompt che hanno funzionato, i parametri, e cosa è andato storto.
I file generati restano fuori (vedi `.gitignore`) — su Git i binari pesanti
non si cancellano più.

## Struttura

| Cartella | Contenuto |
|---|---|
| `docs/personaggio.md` | Il design del colosso — tre varianti, specificate nel dettaglio |
| `docs/workflow.md` | Come eseguire le generazioni, in ordine |
| `prompts/prompt-pack.md` | I prompt shot-by-shot, da copiare e incollare |
| `results/LOG.md` | Registro dei tentativi: seed, parametri, esito |
| `reference/` | Foto di riferimento del soggetto |

## Perché originale e non un personaggio esistente

Due ragioni, una pratica e una legale.

**Pratica:** i generatori video rendono male i personaggi noti. Hanno visto
migliaia di versioni contrastanti e restituiscono una media sfocata —
proporzioni che ballano tra un fotogramma e l'altro, volti che slittano. Una
descrizione fisica precisa di un personaggio inventato dà molta più stabilità,
perché il modello segue *le tue* specifiche invece di una memoria confusa.

**Legale:** un personaggio originale lo puoi pubblicare ovunque senza pensarci.

## Nota sul soggetto

Le foto ritraggono una persona reale e riconoscibile. Serve il suo consenso —
è richiesto anche dai termini di Higgsfield per la somiglianza di persone reali.

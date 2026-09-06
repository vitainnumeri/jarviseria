# JarvisEria

Assistente vocale di fantacalcio che **risponde soltanto alla tua voce**.

Conversazione continua, stile telefonata: parli, ti risponde, puoi interromperlo
a meta' frase. In mezzo a una stanza di gente che parla — una sala d'asta, per
dire — sente te e ignora tutti gli altri, senza parola di attivazione.

```
tu>     quanto posso spingere su Lookman?
jarvis> Fino a novantaquattro. Hai duecentodieci crediti e nove slot,
        oltre quella cifra ti resta un attacco da riempire con gli avanzi.

(uno accanto a te, ad alta voce)  "IO ARRIVO A CENTO!"
jarvis>  ...
         (niente: non e' la tua voce)
```

---

## Come fa a sentire solo te

Non c'e' un trucco unico, perche' non esiste. Ci sono quattro filtri in
cascata, dal piu' economico al piu' costoso, piu' due meccanismi temporali.
Ogni voce che arriva al microfono deve passarli tutti.

| # | Filtro | Cosa fa | Perche' serve |
|---|--------|---------|---------------|
| 1 | **Guardia d'eco** | Correla l'ingresso con cio' che l'altoparlante sta suonando | L'assistente non si riascolta e non si risponde da solo |
| 2 | **VAD** (Silero) | Tiene solo i frame che contengono voce umana | Non si spreca nulla sul silenzio e sul rumore |
| 3 | **Campo vicino** | Scarta chi arriva pochi dB sopra il brusio della stanza | Chi parla a tre metri viene escluso per **fisica**, non per statistica |
| 4 | **Biometria** (ECAPA-TDNN) | Impronta vocale della finestra confrontata col tuo profilo | E' il riconoscimento vero e proprio |
| 5 | **Margine sulla coorte** | Devi somigliare a te *piu' che a chiunque altro presente*, e di un margine | E' la regola che regge in mezzo alla gente (vedi sotto) |
| 6 | **Maggioranza** | Un turno vale se lo supera la maggior parte delle sue finestre | Una finestra fortunata non basta ad aprire la porta |

E i due meccanismi temporali:

- **Isteresi.** Appena ti aggancia, la soglia si abbassa: una frase lunga non si
  spezza a meta' perche' hai abbassato la voce su una parola.
- **Rifiuto precoce.** Le finestre vengono valutate **mentre** l'altro parla, non
  dopo. Dopo circa un secondo e mezzo il turno di un estraneo e' gia' buttato:
  non viene mai trascritto, non consuma latenza, non produce nessuna reazione.

### Il punto chiave: il margine sulla coorte

Il filtro 5 e' quello che fa la differenza fra "funziona a casa da solo" e
"funziona in sala d'asta".

Un sistema normale chiede: *"questa voce somiglia a David?"*. Con venti persone
che parlano, prima o poi qualcuna somiglia abbastanza e passa.

JarvisEria chiede un'altra cosa: *"questa voce somiglia a David **piu' di quanto
somigli a chiunque altro presente**, e di almeno un margine?"*. E per poterlo
chiedere tiene una **coorte**: le impronte di tutti gli altri.

La coorte si popola in due modi:

- **da sola**, durante l'uso: ogni voce rifiutata ci finisce dentro. Dopo qualche
  minuto nella stanza il sistema conosce chi c'e' e diventa piu' severo proprio
  verso quelle voci;
- **in anticipo**, con `jarvis cohort --files <registrazioni di altri>`, se sai
  gia' chi ci sara'.

### Prima di tutto questo: il microfono

Il consiglio piu' utile del progetto e' anche il meno tecnologico.

**Usa un auricolare o un archetto con microfono vicino alla bocca.** Un microfono
a cinque centimetri riceve la tua voce 20-25 dB piu' forte di chiunque altro
nella stanza. Nessun modello puo' pareggiare quel vantaggio, e il filtro 3 lo
sfrutta gratis.

Con il microfono del portatile in mezzo al tavolo il sistema funziona lo stesso,
ma dovrai alzare le soglie e qualche frase tua verra' persa. In una sala d'asta
rumorosa, con il microfono lontano, aspettati errori: e' un limite fisico.

---

## Installazione

Serve Python 3.10 o superiore.

```bash
git clone https://github.com/vitainnumeri/jarviseria
cd jarviseria

python -m venv .venv && source .venv/bin/activate
pip install -e ".[audio,asr-local,llm]"

cp .env.example .env      # e metti dentro ANTHROPIC_API_KEY
```

Su Linux serve anche PortAudio: `sudo apt install portaudio19-dev`.

Per la voce dell'assistente, scarica una voce italiana di
[Piper](https://github.com/rhasspy/piper/releases) (servono i due file
`.onnx` e `.onnx.json`) e mettila in `models/piper/`. In alternativa configura
ElevenLabs o OpenAI in `config/local.yaml`.

### Cosa gira dove

| Componente | Dove gira | Nota |
|---|---|---|
| Riconoscimento del parlante | **In locale** | La tua voce non esce mai dal computer |
| VAD | **In locale** | |
| Trascrizione (Whisper) | **In locale** di default | Con `asr.provider: openai` va in rete |
| Ragionamento (Claude) | In rete | Serve `ANTHROPIC_API_KEY` |
| Sintesi vocale (Piper) | **In locale** di default | |

Con Piper e faster-whisper, l'unica cosa che esce dal computer e' il **testo**
della conversazione.

---

## Primo avvio

### 1. Scegli il microfono

```bash
jarvis devices
```

Metti l'indice scelto in `config/local.yaml`:

```yaml
audio:
  input_device: 3
```

### 2. Arruola la tua voce

```bash
jarvis enroll
```

Ti fa leggere otto frasi (circa 40 secondi in tutto). Sono foneticamente varie e
contengono il gergo dell'asta, cosi' l'impronta regge sul vocabolario che userai
davvero.

**Fallo con lo stesso microfono e alla stessa distanza che userai poi.** Un
profilo registrato col portatile non funziona bene con l'auricolare, e viceversa.
Se cambi microfono, rifai l'arruolamento: dura un minuto.

### 3. Controlla e calibra

```bash
jarvis calibrate
```

Ti dice quante impronte hai, quanto sono coerenti fra loro e quali soglie usare.
Sotto 0.55 di coerenza qualcosa e' andato storto (rumore, o qualcun altro ha
letto una frase): rifai.

### 4. Verifica che senta davvero solo te

Questa e' la parte che decide se il progetto vale qualcosa, quindi ha due
strumenti distinti: uno per **guardare**, uno per **misurare**.

#### `jarvis diag` — guardare

```bash
jarvis diag --seconds 60
```

Ascolta e stampa, finestra per finestra, chi sta sentendo:

```
     t      io   altri   margine       dB  esito
----------------------------------------------------
   2.5   0.812   0.104     0.708    -18.3  SEI TU
   3.0   0.799   0.104     0.695    -19.1  SEI TU
   7.5   0.203   0.115     0.088    -34.7  altra voce
   8.0   0.187   0.402    -0.215    -33.9  altra voce
```

Serve a capire *cosa sta succedendo*: se i tuoi punteggi sono bassi, se il
rumore di fondo e' stimato bene, se un certo tipo di voce si avvicina alla
soglia. E' un monitor, non un giudizio.

#### `jarvis benchmark` — misurare

Guardare righe che scorrono non e' una misura. Il verdetto vero conta due
errori, che **non pesano uguale**:

| Errore | Cosa succede | Quanto e' grave |
|---|---|---|
| **Falso rifiuto** | Parli tu e non ti sente | Fastidioso: ripeti la frase |
| **Falso accesso** | Parla un altro e gli risponde | Grave: e' esattamente cio' che non deve succedere |

Quindi il criterio **non** e' "pochi errori in totale", ma **zero falsi accessi,
falsi rifiuti pochi**. Un sistema che ti fa ripetere una frase su dieci ma non
apre mai a un estraneo e' buono. Uno che non ti fa mai ripetere ma risponde a un
collega su venti e' inutilizzabile.

**Prepara il materiale** (bastano un paio di minuti a testa):

```bash
mkdir -p prova/mie prova/altri

# La tua voce, parlando normalmente di quello di cui parlerai davvero
jarvis record --out prova/mie/1.wav --seconds 60
jarvis record --out prova/mie/2.wav --seconds 60      # un'altra volta, altro momento

# Altre persone, una per file, nella stessa stanza e alla stessa distanza
jarvis record --out prova/altri/marco.wav --seconds 60
jarvis record --out prova/altri/luca.wav  --seconds 60
jarvis record --out prova/altri/anna.wav  --seconds 60
```

**Fai la misura:**

```bash
jarvis benchmark --mine prova/mie/*.wav --others prova/altri/*.wav
```

```
==============================================================
  BUONO: nessun estraneo e' passato, ogni tanto devi ripetere
==============================================================

  Falsi accessi (parla un altro, risponde) :   0.0%   <- deve essere 0%
  Falsi rifiuti (parli tu, non ti sente)   :   6.7%   <- sotto il 15% va bene

  Separazione fra te e gli altri           : +0.312   <- sopra 0.15 e' solida
  Equal Error Rate                         :   1.4%

  Tue registrazioni  :  28/30  turni riconosciuti  (punteggio mediano 0.781)
  Voci altrui        :   0/45  turni passati       (punteggio mediano 0.194)

  Soglia suggerita da queste registrazioni, per config/local.yaml:

    speaker:
      accept_threshold: 0.58

  Cosa fare adesso:
    - Per farti ripetere di meno abbassa accept_threshold di 0.03 alla volta
      e rifai questa prova: fermati appena un estraneo passa.
```

Esce con codice 1 se anche un solo estraneo passa, cosi' puoi metterlo in uno
script e rifarlo dopo ogni modifica alle soglie.

#### Le tre prove che contano davvero

Nell'ordine, dalla piu' facile alla piu' cattiva:

1. **Solo tu, stanza silenziosa.** Se qui i falsi rifiuti non sono sotto il 10%,
   il problema e' l'arruolamento o il microfono: non andare avanti, rifai
   `jarvis enroll`.
2. **Altre persone, stessa stanza, stessa distanza dal microfono.** E' la prova
   realistica. I falsi accessi devono essere zero.
3. **La prova cattiva.** Fai dire agli altri *le tue stesse frasi*, con il tuo
   tono, il piu' vicino possibile al microfono. Qualcuno che ti imita di
   proposito. Se regge questa, regge la sala d'asta.

Poi rifalla **nel posto vero**, con il rumore vero. Le soglie di default sono un
punto di partenza, non una promessa: l'unico numero che conta e' quello che
misuri tu, dove lo userai.

#### Due errori che falsano la misura

- **Non usare per la prova le stesse registrazioni con cui hai costruito la
  coorte.** Il sistema le conosce gia': i falsi accessi verrebbero zero per
  costruzione, e il numero mentirebbe.
- **Non registrare gli altri piu' lontano di come parlerebbero davvero.** Se li
  registri a due metri e loro poi si sporgono verso il microfono, hai misurato
  una situazione piu' facile di quella reale.


### 5. Carica il listone

Scarica le quotazioni ufficiali da
[fantacalcio.it](https://www.fantacalcio.it/quotazioni-fantacalcio), salvale in
CSV e mettile in `data/listone.csv`. Dettagli in [`data/README.md`](data/README.md).

Senza listone l'assistente funziona lo stesso, ma parla di strategia e criteri:
**non inventa quotazioni**, ti dice che non ce le ha.

### 6. Parla

```bash
jarvis run
```

---

## Comandi

```
jarvis enroll        registra la tua voce (il primo passo)
jarvis cohort        aggiunge le voci degli altri (opzionale, aiuta parecchio)
jarvis calibrate     controlla il profilo e propone le soglie
jarvis record        registra un file audio (per preparare la prova)
jarvis benchmark     LA PROVA: misura falsi accessi e falsi rifiuti
jarvis diag          monitor dal vivo: chi sto sentendo adesso
jarvis run           avvia la conversazione vocale
jarvis chat          stessa testa, da tastiera (per provare senza microfono)
jarvis devices       elenco dei dispositivi audio
jarvis plan          il piano d'asta: quanto spendere per ogni slot
jarvis lineup        formazione da riga di comando
```

Esempi:

```bash
jarvis plan --strategy modificatore
jarvis lineup Maignan Bastoni Dimarco Barella Pulisic "Lautaro Martinez" ...
jarvis chat "quanto vale Lookman in un'asta da 500?"
```

---

## Cosa sa fare, in asta e in formazione

L'assistente ha strumenti veri, non solo memoria del modello.

**In asta**

- `consiglio_offerta` — quanto puoi offrire *adesso*, tenendo conto di crediti
  residui, slot mancanti e piano di reparto. Il vincolo duro e' sempre lo stesso:
  crediti residui meno gli slot ancora da riempire. Non lo sfora mai.
- `registra_acquisto` / `annulla_acquisto` — gli detti gli acquisti a voce e da
  quel momento tutti i conti cambiano.
- `stato_asta` — crediti, slot, spesa per reparto, rosa.
- `piano_asta` — la ripartizione del budget, con quattro strategie pronte
  (equilibrata, modificatore di difesa, tre top in attacco, centrocampo forte).

**In formazione**

- `costruisci_formazione` — prova tutti i moduli e tiene il migliore. Il modulo
  si sceglie *dopo* aver visto chi gioca, non prima.
- `confronta_giocatori` — "chi schiero fra questi due", con la ragione della
  scelta e non una sensazione.
- `regolamento` — bonus, malus, modificatore di difesa, glossario.

Il punteggio atteso e' un modello a pesi espliciti — titolarita', avversario,
casa/trasferta, rigorista — quindi l'assistente puo' spiegare *perche'* preferisce
un giocatore a un altro. Se manca la fantamedia storica, la stima dalla
quotazione e **lo dichiara**.

### La ricerca dei nomi tollera la trascrizione

I cognomi si storpiano sempre. `vlahovich` trova Vlahovic, `di marco` trova
Dimarco, `calhanoglou` trova Calhanoglu. Se la corrispondenza non e' netta,
l'assistente chiede conferma invece di tirare a indovinare: in asta un nome
scambiato costa crediti veri.

---

## Regolazione fine

Tutto sta in `config/local.yaml`, che ha la precedenza su `config/default.yaml`.

**Non ti sente / devi ripetere**

```yaml
speaker:
  accept_threshold: 0.55      # da 0.62
  near_field:
    margin_db: 5.0            # da 8.0
```

**Passa qualche voce altrui**

```yaml
speaker:
  accept_threshold: 0.70
  reject_margin: 0.15         # piu' severo il confronto con gli altri
```

e soprattutto registra la coorte: `jarvis cohort --files altri_*.wav`.

**Stanza molto rumorosa (sala d'asta vera)**

```yaml
speaker:
  wake_word:
    enabled: true             # oltre alla voce, esige anche "jarvis"
vad:
  threshold: 0.7
```

**Ti taglia le frasi a meta'**

```yaml
vad:
  min_silence_ms: 900         # da 600: aspetta di piu' prima di chiudere il turno
```

**Risposte troppo lente**

```yaml
asr:
  model: small                # da medium
llm:
  max_tokens: 400             # risposte piu' corte = voce che parte prima
```

---

## Latenza

Sul percorso completo, con Whisper `medium` in locale su CPU moderna:

| Fase | Tempo tipico |
|---|---|
| Chiusura del turno (silenzio) | 600 ms (configurabile) |
| Verifica del parlante | gia' fatta durante il parlato |
| Trascrizione | 200-500 ms |
| Prima frase del modello | 400-800 ms |
| Sintesi della prima frase | 100-300 ms |
| **Prima parola udibile** | **circa 1,3-2,2 s** |

Il grosso non e' recuperabile senza cambiare approccio (ASR in streaming vero),
ma due cose lo rendono meno pesante: la biometria gira *durante* il parlato, e la
risposta viene detta **una frase alla volta** mentre il modello scrive ancora.

---

## Limiti, detti chiaramente

- **Un gemello o un'imitazione bravissima possono passare.** La verifica del
  parlante non e' un'autenticazione di sicurezza: e' un filtro conversazionale.
  Non usarlo per proteggere niente di importante.
- **Una registrazione della tua voce riprodotta da un altoparlante puo' passare**
  (non c'e' rilevamento di attacchi di riproduzione).
- **Se sei raffreddato o hai la voce rotta**, i punteggi calano. L'adattamento
  lento aiuta, ma in giornate cosi' potresti dover abbassare la soglia.
- **Se cambi microfono senza rifare l'arruolamento**, il riconoscimento peggiora
  molto.
- **L'assistente non ha notizie di giornata.** Non conosce infortuni, probabili
  formazioni o mercato aggiornato: te lo dice invece di inventare. Quelle
  informazioni gliele devi passare tu a voce.
- **Le quotazioni sono quelle del file che carichi**, non di un archivio interno.
- **I regolamenti cambiano da lega a lega.** L'assistente usa i valori standard e
  chiede conferma su assist, portiere imbattuto e modificatore di difesa.

---

## Privacy

Il profilo vocale e' un **dato biometrico**. Vive in `profiles/`, e' escluso da
git e non viene caricato da nessuna parte. Idem la coorte: contiene le impronte
di persone che non ti hanno dato nessun consenso, quindi resta locale e basta.

Con la configurazione di default (Piper + faster-whisper) l'unica cosa che esce
dal tuo computer e' il testo della conversazione, diretto all'API di Claude.

Se registri altre persone per costruire la coorte, diglielo.

---

## Struttura

```
src/jarvis/
  audio/        cattura, riproduzione, VAD, DSP (livelli, rumore, eco)
  speaker/      impronta vocale, profilo, coorte, verificatore   <- il cuore
  asr/          trascrizione (faster-whisper locale, o OpenAI)
  llm/          agente, istruzioni, strumenti di dominio
  tts/          sintesi vocale (Piper locale, ElevenLabs, OpenAI)
  fanta/        listone, motore d'asta, motore di formazione, regolamento
  session/      orchestratore full-duplex, parola di attivazione
```

I provider sono intercambiabili: ognuno e' dietro un'interfaccia minima, e
cambiarne uno e' una riga di configurazione.

## Sviluppo

```bash
pip install -e ".[dev]"
pytest -q
```

216 test, 81% di copertura, e nessuno di essi richiede microfono, modelli o
rete: le voci sintetiche e l'embedder controllato stanno in `tests/conftest.py`.

Il test che conta e' `test_session.py::test_stanza_affollata_una_sola_risposta`:
sette persone parlano a turno attraverso la catena completa, ne esce una sola
risposta. Accanto c'e'
`test_l_estraneo_viene_scartato_prima_della_fine_della_frase`, che verifica il
rifiuto precoce — un estraneo non arriva mai alla trascrizione.

// Chiamata a Claude direttamente dal telefono, senza server in mezzo.
//
// L'API accetta richieste dal browser solo con un header esplicito, che dice
// "so che sto esponendo la chiave nel codice del client". E' vero e non va
// nascosto: la chiave vive nella memoria del browser di questo telefono. Vedi
// l'avvertenza nella pagina e nel README - in breve: usa una chiave dedicata
// con un tetto di spesa, cosi' se il telefono va perso il danno e' limitato.

const ENDPOINT = 'https://api.anthropic.com/v1/messages';
const VERSIONE = '2023-06-01';
export const MODELLO = 'claude-opus-5';
const MAX_GIRI_STRUMENTI = 5;

export class ErroreLLM extends Error {
  constructor(messaggio, stato) { super(messaggio); this.stato = stato; }
}

/** Traduce gli errori dell'API in qualcosa che si possa leggere e risolvere. */
function spiegaErrore(stato, corpo) {
  const dettaglio = corpo?.error?.message || '';
  if (stato === 401) return 'La chiave API non e\' valida. Controllala nelle impostazioni.';
  if (stato === 403) return 'La chiave non ha i permessi necessari.';
  if (stato === 429) return 'Troppe richieste ravvicinate: aspetta qualche secondo.';
  if (stato === 400 && /credit|balance/i.test(dettaglio)) {
    return 'Credito esaurito sul tuo account Anthropic.';
  }
  if (stato >= 500) return 'L\'API di Claude ha un problema momentaneo: riprova fra poco.';
  return dettaglio || `Errore ${stato}`;
}

/**
 * Legge un flusso Server-Sent Events e restituisce gli eventi via callback.
 *
 * Si scrive a mano invece di usare l'SDK perche' la pagina non ha un passo di
 * compilazione: e' un file statico che il telefono apre e basta.
 */
async function* leggiSSE(risposta) {
  const reader = risposta.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocchi = buffer.split('\n\n');
    buffer = blocchi.pop() || '';
    for (const blocco of blocchi) {
      for (const riga of blocco.split('\n')) {
        if (riga.startsWith('data: ')) {
          const dati = riga.slice(6);
          if (dati === '[DONE]') return;
          try { yield JSON.parse(dati); } catch { /* frammento incompleto */ }
        }
      }
    }
  }
}

export class Agente {
  /**
   * @param apiKey     chiave Anthropic
   * @param system     istruzioni di sistema
   * @param tools      definizioni degli strumenti (schema JSON)
   * @param eseguiTool funzione (nome, argomenti) -> risultato serializzabile
   */
  constructor({ apiKey, system, tools = [], eseguiTool = null, maxTokens = 512,
                storicoTurni = 12 } = {}) {
    this.apiKey = apiKey;
    this.system = system;
    this.tools = tools;
    this.eseguiTool = eseguiTool;
    this.maxTokens = maxTokens;
    this.storicoTurni = storicoTurni;
    this.messaggi = [];
    this.ultimoUso = null;
  }

  reset() { this.messaggi = []; }

  _pota() {
    const limite = this.storicoTurni * 2;
    if (this.messaggi.length <= limite) return;
    // Non si taglia a meta' di uno scambio con strumenti: un tool_result senza
    // il suo tool_use fa rifiutare l'intera richiesta.
    let taglio = this.messaggi.length - limite;
    while (taglio < this.messaggi.length && this.messaggi[taglio].role !== 'user') taglio++;
    this.messaggi = this.messaggi.slice(taglio);
  }

  async _chiama(segnale) {
    const risposta = await fetch(ENDPOINT, {
      method: 'POST',
      signal: segnale,
      headers: {
        'content-type': 'application/json',
        'x-api-key': this.apiKey,
        'anthropic-version': VERSIONE,
        // Senza questo header il browser riceve un errore CORS.
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: MODELLO,
        max_tokens: this.maxTokens,
        system: this.system,
        messages: this.messaggi,
        ...(this.tools.length ? { tools: this.tools } : {}),
        // Effort basso: in una conversazione a voce la latenza conta piu' della
        // profondita'. Il ragionamento resta attivo (spegnerlo del tutto fa
        // scrivere le chiamate agli strumenti nel testo invece di eseguirle).
        output_config: { effort: 'low' },
        stream: true,
      }),
    });

    if (!risposta.ok) {
      let corpo = null;
      try { corpo = await risposta.json(); } catch { /* corpo non JSON */ }
      throw new ErroreLLM(spiegaErrore(risposta.status, corpo), risposta.status);
    }
    return risposta;
  }

  /**
   * Genera la risposta in streaming, eseguendo gli strumenti quando servono.
   *
   * Restituisce solo il testo destinato alla voce: il traffico degli strumenti
   * resta interno, cosi' l'assistente non legge ad alta voce i suoi conti.
   */
  async *rispondi(testoUtente, { segnale = null } = {}) {
    this.messaggi.push({ role: 'user', content: testoUtente });
    this._pota();

    for (let giro = 0; giro < MAX_GIRI_STRUMENTI; giro++) {
      const risposta = await this._chiama(segnale);

      const blocchi = [];
      let stopReason = null;
      let bloccoCorrente = null;
      let jsonParziale = '';

      for await (const evento of leggiSSE(risposta)) {
        switch (evento.type) {
          case 'content_block_start':
            bloccoCorrente = evento.content_block;
            jsonParziale = '';
            if (bloccoCorrente.type === 'text') bloccoCorrente.text = '';
            break;
          case 'content_block_delta':
            if (evento.delta.type === 'text_delta') {
              bloccoCorrente.text += evento.delta.text;
              yield evento.delta.text;          // la voce parte subito
            } else if (evento.delta.type === 'input_json_delta') {
              jsonParziale += evento.delta.partial_json;
            }
            break;
          case 'content_block_stop':
            if (bloccoCorrente?.type === 'tool_use') {
              try { bloccoCorrente.input = jsonParziale ? JSON.parse(jsonParziale) : {}; }
              catch { bloccoCorrente.input = {}; }
            }
            if (bloccoCorrente) blocchi.push(bloccoCorrente);
            bloccoCorrente = null;
            break;
          case 'message_delta':
            stopReason = evento.delta?.stop_reason ?? stopReason;
            if (evento.usage) this.ultimoUso = evento.usage;
            break;
          case 'error':
            throw new ErroreLLM(evento.error?.message || 'errore nel flusso');
        }
      }

      this.messaggi.push({ role: 'assistant', content: blocchi });

      const chiamate = blocchi.filter((b) => b.type === 'tool_use');
      if (!chiamate.length || stopReason !== 'tool_use' || !this.eseguiTool) return;

      const risultati = [];
      for (const c of chiamate) {
        let esito;
        try { esito = await this.eseguiTool(c.name, c.input); }
        catch (e) { esito = { errore: String(e?.message || e) }; }
        risultati.push({ type: 'tool_result', tool_use_id: c.id,
                         content: JSON.stringify(esito) });
      }
      this.messaggi.push({ role: 'user', content: risultati });
    }

    yield ' Sto girando a vuoto sugli strumenti, riformuliamo la domanda.';
  }

  /** Versione non incrementale, comoda per i test. */
  async rispondiTesto(testo, opzioni) {
    let out = '';
    for await (const pezzo of this.rispondi(testo, opzioni)) out += pezzo;
    return out;
  }
}

/**
 * Spezza il testo del modello in frasi mentre arriva.
 *
 * E' quello che rende la risposta "una telefonata": la prima frase parte verso
 * la voce mentre il modello sta ancora scrivendo la seconda.
 */
export function* frasi(testo, stato = { buffer: '' }, minChar = 12) {
  stato.buffer += testo;
  const fine = /(?<=[.!?:;])\s+|\n+/;
  while (true) {
    const m = fine.exec(stato.buffer);
    if (!m || m.index + m[0].length < minChar) break;
    const taglio = m.index + m[0].length;
    const frase = stato.buffer.slice(0, taglio).trim();
    stato.buffer = stato.buffer.slice(taglio);
    if (frase) yield frase;
  }
}

export function svuotaFrasi(stato) {
  const resto = stato.buffer.trim();
  stato.buffer = '';
  return resto ? [resto] : [];
}

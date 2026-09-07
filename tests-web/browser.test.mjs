// Prova end-to-end nel browser vero.
//
// Chromium riceve come microfono un file WAV con una voce sintetica, quindi la
// catena viene percorsa davvero: getUserMedia, AudioWorklet, ricampionamento,
// MFCC, profilo, verifica. E' l'unico modo per sapere se la pagina funziona
// invece di sperarlo.

import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import test from 'node:test';
import { chromium } from 'playwright';

// La versione di Playwright installata cerca un build piu' recente di quello
// presente: si punta direttamente al binario che c'e'.
const CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

const RADICE = new URL('../docs/', import.meta.url).pathname;
const WAV_IO = process.env.JARVIS_WAV_IO || '/tmp/jarvis-io.wav';
const WAV_ALTRO = process.env.JARVIS_WAV_ALTRO || '/tmp/jarvis-altro.wav';
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
               '.json': 'application/json' };

async function avviaServer() {
  const server = createServer(async (req, res) => {
    const percorso = join(RADICE, normalize(req.url.split('?')[0]).replace(/^(\.\.[/\\])+/, ''));
    const file = percorso.endsWith('/') ? join(percorso, 'index.html') : percorso;
    try {
      const dati = await readFile(file);
      res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream' });
      res.end(dati);
    } catch { res.writeHead(404).end('non trovato'); }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  return { server, porta: server.address().port };
}

// localhost e' un contesto sicuro anche in http: getUserMedia funziona.
async function apri(wav) {
  const browser = await chromium.launch({
    executablePath: CHROMIUM,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
           `--use-file-for-fake-audio-capture=${wav}%noloop`, '--no-sandbox'],
  });
  const contesto = await browser.newContext({ permissions: ['microphone'] });
  const pagina = await contesto.newPage();
  const errori = [];
  pagina.on('pageerror', (e) => errori.push(String(e)));
  pagina.on('console', (m) => { if (m.type() === 'error') errori.push(m.text()); });
  return { browser, pagina, errori };
}

test('la pagina si carica senza errori e mostra i passi da fare', async () => {
  const { server, porta } = await avviaServer();
  const { browser, pagina, errori } = await apri(WAV_IO);
  try {
    await pagina.goto(`http://127.0.0.1:${porta}/`, { waitUntil: 'networkidle' });
    assert.equal(await pagina.title(), 'JarvisEria');
    await pagina.waitForSelector('.passo', { timeout: 5000 });
    const passi = await pagina.$$eval('.passo-titolo', (n) => n.map((x) => x.textContent));
    assert.deepEqual(passi, ['Chiave di Claude', 'La tua voce', 'Listone (facoltativo)']);
    assert.deepEqual(errori, [], `errori in pagina: ${errori.join(' | ')}`);
  } finally { await browser.close(); server.close(); }
});

test('il microfono si apre e i moduli girano nel browser', async () => {
  const { server, porta } = await avviaServer();
  const { browser, pagina, errori } = await apri(WAV_IO);
  try {
    await pagina.goto(`http://127.0.0.1:${porta}/`, { waitUntil: 'networkidle' });
    const esito = await pagina.evaluate(async () => {
      const { Microfono, SR } = await import('./js/app.js');
      const raccolti = [];
      const mic = new Microfono((f) => raccolti.push(f));
      await mic.avvia();
      await new Promise((r) => setTimeout(r, 2500));
      mic.ferma();
      const totale = raccolti.reduce((n, f) => n + f.length, 0);
      return { blocchi: raccolti.length, secondi: totale / SR };
    });
    assert.ok(esito.blocchi > 0, 'il microfono non ha prodotto niente');
    assert.ok(esito.secondi > 1.5, `solo ${esito.secondi.toFixed(2)}s di audio catturato`);
    assert.deepEqual(errori, [], errori.join(' | '));
  } finally { await browser.close(); server.close(); }
});

test('arruolamento e riconoscimento dal microfono del browser', async () => {
  const { server, porta } = await avviaServer();
  const { browser, pagina, errori } = await apri(WAV_IO);
  try {
    await pagina.goto(`http://127.0.0.1:${porta}/`, { waitUntil: 'networkidle' });
    const esito = await pagina.evaluate(async () => {
      const { Microfono, SR } = await import('./js/app.js');
      const { calibrate, embedWindows, SpeakerVerifier, VoiceProfile } = await import('./js/verifier.js');

      // Registro dal "microfono" (che sta suonando la voce del proprietario).
      const registra = async (secondi) => {
        const pezzi = [];
        const mic = new Microfono((f) => pezzi.push(f));
        await mic.avvia();
        await new Promise((r) => setTimeout(r, secondi * 1000));
        mic.ferma();
        const n = pezzi.reduce((a, p) => a + p.length, 0);
        const audio = new Float32Array(n);
        let off = 0;
        for (const p of pezzi) { audio.set(p, off); off += p.length; }
        return audio;
      };

      const profilo = new VoiceProfile();
      for (let i = 0; i < 3; i++) {
        for (const v of embedWindows(await registra(3))) profilo.add(v);
      }
      const soglie = calibrate(profilo);
      const ver = new SpeakerVerifier(profilo, { ...soglie, nearFieldEnabled: false });
      const prova = await registra(4);
      return {
        impronte: profilo.size,
        soglia: soglie.acceptThreshold,
        decisione: ver.verify(prova).decision,
        punteggio: ver.verify(prova).score,
      };
    });

    assert.ok(esito.impronte >= 6, `solo ${esito.impronte} impronte`);
    assert.equal(esito.decisione, 'owner',
      `non si e' riconosciuto dal microfono (punteggio ${esito.punteggio})`);
    assert.deepEqual(errori, [], errori.join(' | '));
  } finally { await browser.close(); server.close(); }
});

test('una voce diversa dal microfono viene rifiutata', async () => {
  const { server, porta } = await avviaServer();
  // Il profilo si costruisce dalla voce sintetica calcolata in pagina, poi si
  // giudica cio' che arriva dal microfono, che qui e' un'ALTRA persona.
  const { browser, pagina, errori } = await apri(WAV_ALTRO);
  try {
    await pagina.goto(`http://127.0.0.1:${porta}/`, { waitUntil: 'networkidle' });
    await pagina.addScriptTag({ path: new URL('./voci-browser.js', import.meta.url).pathname,
                                type: 'module' });
    const esito = await pagina.evaluate(async () => {
      const { Microfono } = await import('./js/app.js');
      const { calibrate, embedWindows, SpeakerVerifier, VoiceProfile } = await import('./js/verifier.js');
      const { parla } = window.__voci;

      const profilo = new VoiceProfile();
      for (let i = 0; i < 6; i++) for (const v of embedWindows(parla(0, 3, i + 1))) profilo.add(v);
      const soglie = calibrate(profilo);
      const ver = new SpeakerVerifier(profilo, { ...soglie, nearFieldEnabled: false });

      const pezzi = [];
      const mic = new Microfono((f) => pezzi.push(f));
      await mic.avvia();
      await new Promise((r) => setTimeout(r, 4000));
      mic.ferma();
      const n = pezzi.reduce((a, p) => a + p.length, 0);
      const audio = new Float32Array(n);
      let off = 0;
      for (const p of pezzi) { audio.set(p, off); off += p.length; }

      const r = ver.verify(audio);
      return { decisione: r.decision, punteggio: r.score, soglia: soglie.acceptThreshold };
    });

    assert.notEqual(esito.decisione, 'owner',
      `una voce estranea dal microfono e' passata (punteggio ${esito.punteggio}, soglia ${esito.soglia})`);
    assert.deepEqual(errori, [], errori.join(' | '));
  } finally { await browser.close(); server.close(); }
});

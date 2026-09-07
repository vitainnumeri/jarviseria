// Scrive le voci sintetiche come file WAV, per darle in pasto a Chromium
// tramite --use-file-for-fake-audio-capture: cosi' il browser "sente" davvero
// una persona parlare e la catena viene provata dall'inizio alla fine.
import { writeFileSync } from 'node:fs';
import { parla, SR } from './voci.mjs';

export function scriviWav(percorso, audio, sampleRate = SR) {
  const n = audio.length;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVE', 8);
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(sampleRate, 24);
  buf.writeUInt32LE(sampleRate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    buf.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(audio[i] * 32767))), 44 + i * 2);
  }
  writeFileSync(percorso, buf);
  return percorso;
}

if (process.argv[2]) {
  const persona = Number(process.argv[3] ?? 0);
  const secondi = Number(process.argv[4] ?? 30);
  // Un file lungo: Chromium lo ripete in loop come ingresso del microfono.
  scriviWav(process.argv[2], parla(persona, secondi, 42));
  console.log(`scritto ${process.argv[2]} (persona ${persona}, ${secondi}s)`);
}

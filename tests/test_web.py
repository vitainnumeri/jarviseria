"""Test della modalita' telefono.

Il test che conta e' l'ultimo: apre un server vero, ci collega un client
WebSocket vero, gli spara dentro la voce sintetica del proprietario e verifica
che dall'altra parte esca una risposta con dell'audio. Tutta la catena, senza
microfono e senza modelli.
"""

from __future__ import annotations

import asyncio
import json
import threading

import numpy as np
import pytest

from conftest import FakeEmbedder, speech
from jarvis.config import Config
from jarvis.speaker.profile import Cohort, VoiceProfile
from jarvis.web.transport import (
    DOWNLINK_RATE,
    UPLINK_RATE,
    RemoteAudioSource,
    WebSocketSpeaker,
)

FRAME_MS = 20
FRAME_LEN = UPLINK_RATE * FRAME_MS // 1000


# --------------------------------------------------------- sorgente remota

def test_i_blocchi_dal_telefono_diventano_frame_di_durata_esatta():
    """Il browser manda blocchi di misura variabile: VAD e segmentatore no."""
    source = RemoteAudioSource(UPLINK_RATE, FRAME_MS)
    pcm = np.zeros(FRAME_LEN * 3 + 77, dtype="<i2").tobytes()   # misura "sporca"
    assert source.push_pcm(pcm) == 3
    for _ in range(3):
        frame = source.read(timeout=0.1)
        assert frame is not None and frame.size == FRAME_LEN


def test_il_resto_di_un_blocco_si_ricuce_col_successivo():
    source = RemoteAudioSource(UPLINK_RATE, FRAME_MS)
    meta = np.zeros(FRAME_LEN // 2, dtype="<i2").tobytes()
    assert source.push_pcm(meta) == 0        # non basta per un frame
    assert source.push_pcm(meta) == 1        # le due meta' fanno un frame


def test_la_conversione_da_interi_conserva_il_segnale():
    source = RemoteAudioSource(UPLINK_RATE, FRAME_MS)
    originale = (speech(0, 0.02) * 0.5).astype(np.float32)[:FRAME_LEN]
    pcm = (np.clip(originale, -1, 1) * 32767).astype("<i2").tobytes()
    source.push_pcm(pcm)
    assert np.allclose(source.read(timeout=0.1), originale, atol=1e-3)


def test_un_blocco_vuoto_non_produce_niente():
    assert RemoteAudioSource().push_pcm(b"") == 0


def test_se_il_server_resta_indietro_scarta_l_audio_vecchio():
    """Meglio un buco di 20 ms che secondi di ritardo in conversazione."""
    source = RemoteAudioSource(UPLINK_RATE, FRAME_MS, max_queue_frames=5)
    source.push_pcm(np.zeros(FRAME_LEN * 20, dtype="<i2").tobytes())
    assert source.dropped_frames > 0
    assert source._queue.qsize() <= 5


# ------------------------------------------------------- altoparlante remoto

def attendi(condizione, timeout: float = 2.0) -> bool:
    """I messaggi di controllo partono senza attesa: qui li aspetto io.

    E' proprio la proprieta' che si vuole nel codice — il ciclo audio non deve
    mai fermarsi per la rete — quindi il test si adegua invece di rallentarlo.
    """
    import time

    scadenza = time.monotonic() + timeout
    while time.monotonic() < scadenza:
        if condizione():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def speaker_remoto():
    inviati, controlli = [], []

    async def send_bytes(payload):
        inviati.append(payload)

    async def send_control(message):
        controlli.append(message)

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    speaker = WebSocketSpeaker(send_bytes, send_control, loop)
    yield speaker, inviati, controlli
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2.0)


def test_l_audio_parte_verso_il_telefono(speaker_remoto):
    speaker, inviati, _ = speaker_remoto
    assert speaker.play(np.zeros(DOWNLINK_RATE // 2, dtype=np.float32), DOWNLINK_RATE)
    assert inviati, "niente e' arrivato al telefono"
    assert sum(len(b) for b in inviati) == DOWNLINK_RATE  # mezzo secondo a 16 bit


def test_l_audio_viene_spezzato_in_blocchi_interrompibili(speaker_remoto):
    """Un solo blocco enorme renderebbe l'interruzione inutile."""
    speaker, inviati, _ = speaker_remoto
    speaker.play(np.zeros(DOWNLINK_RATE, dtype=np.float32), DOWNLINK_RATE)
    assert len(inviati) >= 6


def test_lo_stop_chiede_al_telefono_di_svuotare_la_coda(speaker_remoto):
    """Il telefono ha gia' dei blocchi in pancia: deve buttarli, non finirli."""
    speaker, _, controlli = speaker_remoto
    speaker._playing.set()
    speaker.stop()
    assert attendi(lambda: {"type": "flush"} in controlli)


def test_il_ducking_si_annuncia_una_volta_sola(speaker_remoto):
    """Il ciclo audio lo richiama a ogni frame: cinquanta messaggi al secondo, no."""
    speaker, _, controlli = speaker_remoto
    for _ in range(50):
        speaker.duck(-12.0)
    assert attendi(lambda: any(c["type"] == "duck" for c in controlli))
    assert sum(1 for c in controlli if c["type"] == "duck") == 1

    speaker.unduck()
    speaker.duck(-12.0)
    assert attendi(lambda: sum(1 for c in controlli if c["type"] == "duck") == 2)


def test_il_ricampionamento_verso_il_telefono(speaker_remoto):
    """La sintesi produce 22050 Hz, sul filo viaggiano 24000."""
    speaker, inviati, _ = speaker_remoto
    speaker.play(np.zeros(22050, dtype=np.float32), 22050)
    assert sum(len(b) for b in inviati) == pytest.approx(DOWNLINK_RATE * 2, rel=0.02)


# ------------------------------------------------------------------- TLS

def test_l_indirizzo_locale_e_un_ip():
    from jarvis.web.tls import local_ip

    parti = local_ip().split(".")
    assert len(parti) == 4 and all(p.isdigit() for p in parti)


def test_il_certificato_si_crea_una_volta_sola(tmp_path):
    from jarvis.web.tls import ensure_certificate

    cert, key = ensure_certificate(tmp_path, "192.168.1.50")
    assert cert.exists() and key.exists()
    impronta = cert.read_bytes()
    assert ensure_certificate(tmp_path, "192.168.1.50")[0].read_bytes() == impronta


def test_il_certificato_si_rigenera_se_cambio_rete(tmp_path):
    """Un certificato con l'IP sbagliato non viene accettato dal browser."""
    from jarvis.web.tls import ensure_certificate

    cert, _ = ensure_certificate(tmp_path, "192.168.1.50")
    prima = cert.read_bytes()
    assert ensure_certificate(tmp_path, "10.0.0.7")[0].read_bytes() != prima


def test_la_chiave_privata_non_e_leggibile_da_altri(tmp_path):
    from jarvis.web.tls import ensure_certificate

    _, key = ensure_certificate(tmp_path, "192.168.1.50")
    assert oct(key.stat().st_mode)[-3:] == "600"


# ------------------------------------------------ la pagina per il telefono

def test_la_pagina_disattiva_il_guadagno_automatico():
    """Con l'AGC acceso le voci lontane verrebbero amplificate fino alla mia,
    e il filtro di campo vicino diventerebbe inutile."""
    from jarvis.web.server import STATIC_DIR

    pagina = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "autoGainControl: false" in pagina
    assert "noiseSuppression: false" in pagina
    assert "echoCancellation: true" in pagina


def test_la_pagina_tiene_lo_schermo_acceso():
    """Schermo spento = collegamento chiuso = asta persa."""
    from jarvis.web.server import STATIC_DIR

    assert "wakeLock" in (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# -------------------------------------------------- catena completa in rete

class FakeTranscriber:
    def transcribe(self, audio, sample_rate=UPLINK_RATE):
        from jarvis.asr import Transcript

        return Transcript(text="quanto offro per Lautaro", duration=len(audio) / sample_rate)


class FakeAgent:
    def __init__(self):
        self.asked = []

    def respond(self, text):
        self.asked.append(text)
        for parola in ["Fino a ", "centottanta ", "crediti."]:
            yield parola

    def respond_text(self, text):
        return "".join(self.respond(text))

    def reset(self):
        self.asked.clear()


class FakeTTS:
    def synthesize(self, text):
        from jarvis.tts import Audio

        return Audio(np.zeros(DOWNLINK_RATE // 5, dtype=np.float32), DOWNLINK_RATE)


def build_test_server():
    from jarvis.web.server import PhoneServer

    embedder = FakeEmbedder()
    profile = VoiceProfile(name="io")
    for i in range(6):
        profile.add(embedder.embed(speech(0, 4.0 + i * 0.3)))

    cfg = Config({
        "audio": {"sample_rate": UPLINK_RATE, "frame_ms": FRAME_MS},
        "vad": {"provider": "energy", "min_speech_ms": 100, "min_silence_ms": 200,
                "pre_roll_ms": 100},
        "speaker": {"near_field": {"enabled": False}, "adaptation": {"enabled": False}},
        "session": {"barge_in": True, "echo_guard": False, "greeting": None},
        "log": {},
    })
    agent = FakeAgent()
    return PhoneServer(
        cfg, embedder=embedder, profile=profile, cohort=Cohort(),
        transcriber=FakeTranscriber(), agent=agent, synthesizer=FakeTTS(),
    ), agent


async def _dialogo(persona: int, timeout: float = 15.0) -> tuple[list, list, object]:
    """Collega un finto telefono, gli fa dire una frase e raccoglie cio' che torna."""
    import aiohttp
    from aiohttp import web as aioweb

    server, agent = build_test_server()
    runner = aioweb.AppRunner(server.app)
    await runner.setup()
    site = aioweb.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    eventi, audio_ricevuto = [], []
    try:
        async with aiohttp.ClientSession() as sessione:
            async with sessione.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                voce = speech(persona, 3.0)
                pcm = (np.clip(voce, -1, 1) * 32767).astype("<i2").tobytes()
                for start in range(0, len(pcm), FRAME_LEN * 2):
                    await ws.send_bytes(pcm[start : start + FRAME_LEN * 2])
                silenzio = np.zeros(FRAME_LEN, dtype="<i2").tobytes()
                for _ in range(30):
                    await ws.send_bytes(silenzio)

                async def raccogli():
                    async for messaggio in ws:
                        if messaggio.type is aiohttp.WSMsgType.TEXT:
                            evento = json.loads(messaggio.data)
                            eventi.append(evento)
                            if evento["type"] == "answer":
                                return
                        elif messaggio.type is aiohttp.WSMsgType.BINARY:
                            audio_ricevuto.append(messaggio.data)

                try:
                    await asyncio.wait_for(raccogli(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
    finally:
        await runner.cleanup()
    return eventi, audio_ricevuto, agent


def test_catena_completa_il_proprietario_riceve_una_risposta():
    """Telefono -> WebSocket -> VAD -> biometria -> ASR -> agente -> voce -> telefono."""
    eventi, audio, agent = asyncio.run(_dialogo(persona=0))
    tipi = [e["type"] for e in eventi]

    assert "ready" in tipi
    assert "transcript" in tipi, f"la frase non e' stata riconosciuta: {tipi}"
    assert "answer" in tipi, f"nessuna risposta: {tipi}"
    assert agent.asked == ["quanto offro per Lautaro"]
    assert audio, "la voce non e' tornata al telefono"


def test_catena_completa_un_estraneo_non_riceve_niente():
    """La prova che conta: la stessa catena, un'altra voce, silenzio assoluto."""
    eventi, audio, agent = asyncio.run(_dialogo(persona=3, timeout=6.0))
    tipi = [e["type"] for e in eventi]

    assert "transcript" not in tipi
    assert "answer" not in tipi
    assert agent.asked == [], "l'agente e' stato interpellato da un estraneo"
    assert audio == [], "il telefono ha ricevuto audio per una voce non autorizzata"
    assert "ignored" in tipi or "stranger" in tipi


def test_la_pagina_viene_servita():
    import aiohttp
    from aiohttp import web as aioweb

    async def scenario():
        server, _ = build_test_server()
        runner = aioweb.AppRunner(server.app)
        await runner.setup()
        site = aioweb.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as sessione:
                async with sessione.get(f"http://127.0.0.1:{port}/") as risposta:
                    return risposta.status, risposta.content_type, await risposta.text()
        finally:
            await runner.cleanup()

    status, tipo, corpo = asyncio.run(scenario())
    assert status == 200 and tipo == "text/html"
    assert "<title>JarvisEria</title>" in corpo


def test_un_secondo_telefono_viene_rifiutato_con_chiarezza():
    """Una sola rosa, un solo budget, un solo filo del discorso."""
    import aiohttp
    from aiohttp import web as aioweb

    async def scenario():
        server, _ = build_test_server()
        runner = aioweb.AppRunner(server.app)
        await runner.setup()
        site = aioweb.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as sessione:
                async with sessione.ws_connect(f"http://127.0.0.1:{port}/ws") as primo:
                    await asyncio.wait_for(primo.receive(), timeout=5)
                    async with sessione.ws_connect(f"http://127.0.0.1:{port}/ws") as secondo:
                        messaggio = await asyncio.wait_for(secondo.receive(), timeout=5)
                        return json.loads(messaggio.data)
        finally:
            await runner.cleanup()

    risposta = asyncio.run(scenario())
    assert risposta["type"] == "error"
    assert "gia' un telefono collegato" in risposta["text"]

"""Server che trasforma il telefono in microfono e altoparlante.

Il telefono apre una pagina, il PC fa tutto il lavoro. Nessuna app da
installare, funziona uguale su iOS e Android, e — dettaglio non secondario —
con gli auricolari il microfono ti sta a cinque centimetri dalla bocca, che e'
la condizione in cui il riconoscimento della tua voce funziona meglio.

Cosa vive dove:

    per sessione   la verifica del parlante (rumore di fondo e isteresi sono
                   dello specifico collegamento) e l'audio
    per server     modelli, listone, stato d'asta e conversazione

La seconda riga e' quella che conta all'asta: quando il telefono blocca lo
schermo il collegamento cade, ma i crediti spesi e la rosa restano. Riapri la
pagina e riprendi dalla frase dopo.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from aiohttp import WSMsgType, web

from ..session.orchestrator import VoiceSession
from ..utils.logging import get_logger
from .transport import UPLINK_RATE, RemoteAudioSource, WebSocketSpeaker

log = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class PhoneServer:
    """Un solo interlocutore alla volta, come una telefonata vera.

    Un secondo telefono viene rifiutato con un messaggio chiaro invece di
    entrare a meta' nella conversazione di un altro: l'assistente ha una sola
    rosa, un solo budget e un solo filo del discorso.
    """

    def __init__(self, cfg, *, embedder, profile, cohort, transcriber, agent, synthesizer):
        self.cfg = cfg
        self.embedder = embedder
        self.profile = profile
        self.cohort = cohort
        self.transcriber = transcriber
        self.agent = agent
        self.synthesizer = synthesizer

        self._busy = threading.Lock()
        self._session: VoiceSession | None = None
        self.app = web.Application()
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/ws", self._websocket)
        self.app.router.add_static("/static", STATIC_DIR)

    # ------------------------------------------------------------------ pagina
    async def _index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    # --------------------------------------------------------------- sessione
    def _build_session(self, ws: web.WebSocketResponse, loop) -> tuple[VoiceSession, RemoteAudioSource]:
        """Compone una sessione vocale che parla col telefono invece che con la scheda audio."""
        from ..audio.vad import build_vad
        from ..speaker.verifier import SpeakerVerifier, VerifierConfig

        async def send_bytes(payload: bytes) -> None:
            if not ws.closed:
                await ws.send_bytes(payload)

        async def send_control(message: dict) -> None:
            if not ws.closed:
                await ws.send_str(json.dumps(message, ensure_ascii=False))

        def on_event(event: dict) -> None:
            """Gli eventi nascono nei thread della sessione, il socket vive nel loop.

            Fire-and-forget: l'interfaccia non deve mai poter rallentare il ciclo
            audio, che gira ogni 20 ms.
            """
            try:
                asyncio.run_coroutine_threadsafe(send_control(event), loop)
            except RuntimeError:  # pragma: no cover - loop gia' chiuso
                pass

        source = RemoteAudioSource(UPLINK_RATE, int(self.cfg.get("audio.frame_ms", 20)))
        # Il rumore di fondo e l'isteresi appartengono a QUESTO collegamento:
        # un verificatore nuovo per ogni telefono, ma modelli e profilo condivisi.
        verifier = SpeakerVerifier(
            self.embedder, self.profile, VerifierConfig.from_config(self.cfg), self.cohort
        )
        session = VoiceSession(
            mic=source,
            vad=build_vad(self.cfg.get("vad.provider", "silero"), UPLINK_RATE,
                          float(self.cfg.get("vad.threshold", 0.55))),
            verifier=verifier,
            transcriber=self.transcriber,
            agent=self.agent,
            synthesizer=self.synthesizer,
            speaker=WebSocketSpeaker(send_bytes, send_control, loop),
            cfg=self.cfg,
            on_event=on_event,
        )
        # La cancellazione d'eco la fa il browser, ed e' un vero AEC hardware:
        # meglio della nostra correlazione, che qui non funzionerebbe comunque
        # perche' il ritardo di rete fra riproduzione e ritorno e' variabile.
        session.echo_guard = False
        return session, source

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)

        if not self._busy.acquire(blocking=False):
            await ws.send_str(json.dumps({
                "type": "error",
                "text": "C'e' gia' un telefono collegato. Chiudi l'altra pagina e riprova.",
            }))
            await ws.close()
            return ws

        peer = request.remote
        log.info("telefono collegato da %s", peer)
        session, source = self._build_session(ws, asyncio.get_running_loop())
        self._session = session
        worker = threading.Thread(
            target=session.run, kwargs={"greeting": self.cfg.get("session.greeting")}, daemon=True
        )

        try:
            await ws.send_str(json.dumps({
                "type": "ready",
                "sample_rate": UPLINK_RATE,
                "text": "Collegato. Parla pure.",
            }))
            worker.start()

            async for message in ws:
                if message.type is WSMsgType.BINARY:
                    source.push_pcm(message.data)
                elif message.type is WSMsgType.TEXT:
                    await self._handle_control(ws, session, message.data)
                elif message.type is WSMsgType.ERROR:  # pragma: no cover - rete
                    log.warning("errore sul socket: %s", ws.exception())
        finally:
            log.info("telefono scollegato (%s)", peer)
            session.stop()
            worker.join(timeout=3.0)
            self._session = None
            self._busy.release()
        return ws

    async def _handle_control(self, ws: web.WebSocketResponse, session: VoiceSession,
                              raw: str) -> None:
        """Messaggi di servizio dal telefono."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return

        kind = message.get("type")
        if kind == "stop":
            # L'utente ha toccato "zitto": interrompo come farebbe una barge-in.
            session.speaker.stop()
        elif kind == "reset":
            self.agent.reset()
            await ws.send_str(json.dumps({"type": "status", "text": "Conversazione azzerata."}))
        elif kind == "stats":
            await ws.send_str(json.dumps({"type": "stats", "text": session.stats.summary()}))


def build_server(cfg) -> PhoneServer:
    """Costruisce il server caricando una volta sola tutto cio' che e' costoso."""
    from ..asr import build_transcriber
    from ..fanta.auction import AuctionState
    from ..fanta.listone import load_listone
    from ..llm.agent import FantaAgent
    from ..llm.tools import FantaTools
    from ..speaker.embedder import build_embedder
    from ..speaker.profile import Cohort, VoiceProfile
    from ..tts import build_synthesizer

    listone = load_listone(cfg.get("fanta.listone_path"))
    auction = AuctionState(
        budget=int(cfg.get("fanta.budget", 500)),
        slots=dict(cfg.get("fanta.slots", {})),
        budget_split=dict(cfg.get("fanta.budget_split", {})),
    )
    tools = FantaTools(listone, auction)

    return PhoneServer(
        cfg,
        embedder=build_embedder(cfg.get("speaker.model"), "auto"),
        profile=VoiceProfile.load(cfg.resolve_path("speaker.profile_path")),
        cohort=Cohort.load(
            cfg.resolve_path("speaker.cohort.path", "profiles/cohort.npz"),
            max_size=int(cfg.get("speaker.cohort.max_size", 300)),
        ),
        transcriber=build_transcriber(cfg),
        agent=FantaAgent(tools, cfg),
        synthesizer=build_synthesizer(cfg),
    )

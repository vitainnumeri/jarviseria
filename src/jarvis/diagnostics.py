"""Controllo dei prerequisiti: cosa manca, e il comando esatto per rimediare.

Nato da un problema concreto: `jarvis serve` si fermava al primo pezzo mancante
e non diceva quanti altri ce n'erano dietro. Chi resta bloccato non ha bisogno
del primo errore, ha bisogno dell'elenco completo e di sapere a che punto e'.

Ogni controllo e' una funzione pura che restituisce un esito: si collauda senza
avere installato niente di cio' che sta controllando.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

OK = "ok"
MANCA = "manca"
AVVISO = "avviso"


@dataclass
class Check:
    """Esito di un singolo controllo."""

    nome: str
    stato: str
    dettaglio: str = ""
    rimedio: str = ""
    bloccante: bool = True

    @property
    def simbolo(self) -> str:
        return {OK: "[ok]  ", MANCA: "[NO]  ", AVVISO: "[!]   "}[self.stato]

    def to_dict(self) -> dict:
        return {"controllo": self.nome, "stato": self.stato, "dettaglio": self.dettaglio,
                "rimedio": self.rimedio}


def _modulo_presente(nome: str) -> bool:
    """Vero se il modulo e' importabile, senza importarlo davvero.

    Importare torch per sapere se c'e' costerebbe qualche secondo: qui basta
    sapere se esiste.
    """
    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError):
        return False


def check_python() -> Check:
    versione = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 10):
        return Check("Python 3.10+", MANCA, f"hai Python {versione}",
                     "Installa Python 3.10 o superiore da python.org")
    return Check("Python 3.10+", OK, versione)


def check_dipendenza(nome: str, modulo: str, extra: str, *, bloccante: bool = True) -> Check:
    if _modulo_presente(modulo):
        return Check(nome, OK)
    return Check(nome, MANCA if bloccante else AVVISO, "non installato",
                 f'pip install -e ".[{extra}]"', bloccante=bloccante)


def check_chiave_api() -> Check:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Check("Chiave Claude", OK, "ANTHROPIC_API_KEY impostata")
    return Check(
        "Chiave Claude", MANCA, "ANTHROPIC_API_KEY non impostata",
        "Copia .env.example in .env e mettici la chiave da console.anthropic.com",
    )


def check_profilo(path: Path) -> Check:
    if not path.exists():
        return Check("Profilo vocale", MANCA, f"{path} non esiste",
                     "jarvis enroll     (ti fa leggere 8 frasi, dura un minuto)")
    try:
        from .speaker.profile import VoiceProfile

        profilo = VoiceProfile.load(path)
        dettaglio = f"{len(profilo.embeddings)} impronte, {profilo.sample_seconds:.0f}s di voce"
        if profilo.sample_seconds < 20:
            return Check("Profilo vocale", AVVISO, dettaglio,
                         "Poca voce registrata: rifai  jarvis enroll", bloccante=False)
        return Check("Profilo vocale", OK, dettaglio)
    except Exception as exc:  # pragma: no cover - file corrotto
        return Check("Profilo vocale", MANCA, f"illeggibile: {exc}", "jarvis enroll")


def check_listone(path: Path | None) -> Check:
    """Il listone non blocca niente: senza, l'assistente parla di strategia."""
    if path and path.exists():
        return Check("Listone", OK, path.name, bloccante=False)
    return Check("Listone", AVVISO, "non caricato: niente quotazioni",
                 "Vedi data/README.md (l'assistente funziona lo stesso)", bloccante=False)


def check_openssl() -> Check:
    if shutil.which("openssl"):
        return Check("openssl", OK, "serve per il certificato https")
    return Check("openssl", MANCA, "non trovato",
                 "sudo apt install openssl   (macOS: brew install openssl)")


def check_voce_sintetica(cfg) -> Check:
    """La voce del bot: senza, ragiona ma non parla."""
    provider = str(cfg.get("tts.provider", "piper")).lower()
    if provider == "elevenlabs":
        ok = bool(os.environ.get("ELEVENLABS_API_KEY"))
        return Check("Voce (ElevenLabs)", OK if ok else MANCA,
                     "chiave presente" if ok else "ELEVENLABS_API_KEY non impostata",
                     "Mettila nel file .env")
    if provider == "openai":
        ok = bool(os.environ.get("OPENAI_API_KEY"))
        return Check("Voce (OpenAI)", OK if ok else MANCA,
                     "chiave presente" if ok else "OPENAI_API_KEY non impostata",
                     "Mettila nel file .env")

    voce = cfg.get("tts.voice", "it_IT-riccardo-x_low")
    try:
        cartella = cfg.resolve_path("tts.model_dir", "models/piper")
    except KeyError:  # pragma: no cover - configurazione monca
        cartella = Path("models/piper")
    if (cartella / f"{voce}.onnx").exists():
        return Check("Voce (Piper)", OK, voce)
    return Check(
        "Voce (Piper)", MANCA, f"{cartella / (voce + '.onnx')} non c'e'",
        f"Scarica {voce}.onnx e {voce}.onnx.json da github.com/rhasspy/piper/releases\n"
        f"e mettili in {cartella}",
    )


def check_porta(porta: int) -> Check:
    """Una porta gia' occupata e' un classico: due server avviati per sbaglio."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", porta))
        return Check(f"Porta {porta}", OK, "libera")
    except OSError:
        return Check(f"Porta {porta}", MANCA, "gia' occupata",
                     f"Chiudi l'altro server, oppure:  jarvis serve --port {porta + 1}")
    finally:
        sock.close()


def check_rete(porta: int) -> Check:
    """L'indirizzo da digitare sul telefono, piu' il controllo che sia una rete vera."""
    from .web.tls import local_ip

    ip = local_ip()
    if ip.startswith("127."):
        return Check("Rete locale", MANCA, "nessuna rete rilevata",
                     "Collega il PC al Wi-Fi (lo STESSO del telefono)")
    return Check("Rete locale", OK, f"https://{ip}:{porta}  <- questo sul telefono")


def check_microfono() -> Check:
    if not _modulo_presente("sounddevice"):
        return Check("Microfono", MANCA, "sounddevice non installato",
                     'pip install -e ".[audio]"')
    try:
        import sounddevice as sd

        ingressi = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if not ingressi:
            return Check("Microfono", MANCA, "nessun dispositivo di ingresso",
                         "Collega un microfono, oppure usa  jarvis serve  dal telefono")
        return Check("Microfono", OK, f"{len(ingressi)} dispositivi")
    except Exception as exc:
        return Check("Microfono", AVVISO, f"non interrogabile: {exc}",
                     "Non serve in modalita' telefono", bloccante=False)


def run_checks(cfg, *, porta: int = 8765, modalita: str = "telefono") -> list[Check]:
    """Esegue i controlli utili per la modalita' scelta, nell'ordine dei passi."""
    checks = [
        check_python(),
        check_dipendenza("Calcolo (numpy)", "numpy", "audio"),
        check_dipendenza("Riconoscimento voce (speechbrain)", "speechbrain", "audio"),
        check_dipendenza("Rilevamento parlato (silero-vad)", "silero_vad", "audio"),
        check_dipendenza("Trascrizione (faster-whisper)", "faster_whisper", "asr-local"),
        check_dipendenza("Modello (anthropic)", "anthropic", "llm"),
        check_chiave_api(),
        check_voce_sintetica(cfg),
    ]

    try:
        profilo = cfg.resolve_path("speaker.profile_path")
    except KeyError:  # pragma: no cover - configurazione monca
        profilo = Path("profiles/owner.npz")
    checks.append(check_profilo(profilo))

    listone_raw = cfg.get("fanta.listone_path")
    checks.append(check_listone(cfg.resolve_path("fanta.listone_path") if listone_raw else None))

    if modalita == "telefono":
        checks += [
            check_dipendenza("Server web (aiohttp)", "aiohttp", "phone"),
            check_openssl(),
            check_porta(porta),
            check_rete(porta),
        ]
    else:
        checks.append(check_microfono())
    return checks


PIP_PREFIX = 'pip install -e ".['


def _passi(bloccanti: list[Check]) -> list[tuple[str, list[str]]]:
    """Trasforma i rimedi in passi da eseguire, senza ripetizioni.

    Quattro pacchetti mancanti sono UN comando, non quattro: elencarli
    separatamente farebbe installare tre volte la stessa cosa e sembrare il
    problema piu' grande di quello che e'.
    """
    extra: list[str] = []
    passi: list[tuple[str, list[str]]] = []
    for check in bloccanti:
        if check.rimedio.startswith(PIP_PREFIX):
            nome = check.rimedio[len(PIP_PREFIX) : check.rimedio.index("]")]
            for pezzo in nome.split(","):
                if pezzo and pezzo not in extra:
                    extra.append(pezzo)
        else:
            passi.append((check.rimedio, [check.nome]))

    if extra:
        quanti = sum(1 for c in bloccanti if c.rimedio.startswith(PIP_PREFIX))
        etichetta = f"Dipendenze Python ({quanti} pacchetti)"
        passi.insert(0, (f'pip install -e ".[{",".join(extra)}]"', [etichetta]))

    # Rimedi identici richiesti da controlli diversi: un passo solo.
    uniti: list[tuple[str, list[str]]] = []
    for rimedio, nomi in passi:
        for i, (gia_visto, altri) in enumerate(uniti):
            if gia_visto == rimedio:
                uniti[i] = (gia_visto, altri + nomi)
                break
        else:
            uniti.append((rimedio, list(nomi)))
    return uniti


def format_report(checks: list[Check], modalita: str) -> str:
    """Il referto: prima cosa funziona, poi cosa fare, in ordine."""
    larghezza = max(len(c.nome) for c in checks) + 2
    righe = ["", f"  Controllo prerequisiti — modalita' {modalita}", "  " + "-" * 56]
    for c in checks:
        riga = f"  {c.simbolo}{c.nome.ljust(larghezza)}  {c.dettaglio}"
        righe.append(riga.rstrip())

    bloccanti = [c for c in checks if c.stato == MANCA and c.bloccante]
    avvisi = [c for c in checks if c.stato == AVVISO or (c.stato == MANCA and not c.bloccante)]

    if bloccanti:
        passi = _passi(bloccanti)
        plurale = "passo" if len(passi) == 1 else "passi"
        righe += ["", f"  Ti mancano {len(passi)} {plurale}:", ""]
        for i, (rimedio, nomi) in enumerate(passi, start=1):
            righe.append(f"  {i}. {', '.join(nomi)}")
            for linea in rimedio.split("\n"):
                righe.append(f"       {linea}")
            righe.append("")
    else:
        righe += ["", "  Tutto a posto: puoi lanciare  jarvis serve", ""]

    if avvisi:
        righe.append("  Non bloccanti:")
        for c in avvisi:
            righe.append(f"    - {c.nome}: {c.dettaglio}")
            if c.rimedio:
                righe.append(f"      {c.rimedio}")
        righe.append("")
    return "\n".join(righe)


def exit_code(checks: list[Check]) -> int:
    """0 se si puo' partire, 1 se manca qualcosa di bloccante."""
    return 1 if any(c.stato == MANCA and c.bloccante for c in checks) else 0

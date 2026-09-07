"""Interfaccia a riga di comando.

    jarvis doctor        controlla cosa manca per partire (se sei bloccato, parti da qui)
    jarvis enroll        insegna al sistema la tua voce (da fare per primo)
    jarvis cohort        aggiunge le voci degli ALTRI (opzionale, ma aiuta molto)
    jarvis calibrate     controlla il profilo e propone le soglie
    jarvis record        registra un file audio (per preparare la prova)
    jarvis benchmark     LA PROVA: misura quante volte sbaglia, e in che direzione
    jarvis diag          ascolta N secondi e dice, secondo per secondo, se sente te
    jarvis run           avvia la conversazione vocale (microfono del PC)
    jarvis serve         avvia la modalita' telefono: il telefono fa da microfono
    jarvis chat          stessa testa, da tastiera (per provare senza microfono)
    jarvis devices       elenco dei dispositivi audio
    jarvis plan          piano d'asta
    jarvis lineup        formazione da riga di comando
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .utils.logging import get_logger, setup_logging

log = get_logger(__name__)


# --------------------------------------------------------------- costruttori
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _build_domain(cfg):
    """Listone + stato d'asta + strumenti + agente."""
    from .fanta.auction import AuctionState
    from .fanta.listone import load_listone
    from .llm.agent import FantaAgent
    from .llm.tools import FantaTools

    listone = load_listone(cfg.get("fanta.listone_path"))
    auction = AuctionState(
        budget=int(cfg.get("fanta.budget", 500)),
        slots=dict(cfg.get("fanta.slots", {})),
        budget_split=dict(cfg.get("fanta.budget_split", {})),
    )
    tools = FantaTools(listone, auction)
    return listone, auction, tools, FantaAgent(tools, cfg)


def _build_verifier(cfg, *, require_profile: bool = True):
    from .speaker.embedder import build_embedder
    from .speaker.profile import Cohort, VoiceProfile
    from .speaker.verifier import SpeakerVerifier, VerifierConfig

    embedder = build_embedder(cfg.get("speaker.model"), "auto")
    profile_path = cfg.resolve_path("speaker.profile_path")
    profile = VoiceProfile.load(profile_path) if require_profile else VoiceProfile()
    cohort = Cohort.load(
        cfg.resolve_path("speaker.cohort.path", "profiles/cohort.npz"),
        max_size=int(cfg.get("speaker.cohort.max_size", 300)),
    )
    return embedder, SpeakerVerifier(embedder, profile, VerifierConfig.from_config(cfg), cohort)


# ------------------------------------------------------------------- comandi
def _prerequisiti_ok(cfg, *, modalita: str, porta: int = 8765) -> bool:
    """Controlla i prerequisiti prima di avviare, e in caso spiega tutto.

    Senza questo, il primo pezzo mancante fa uscire con un errore solo e chi e'
    bloccato non sa quanti altri ce ne siano dietro.
    """
    from .diagnostics import exit_code, format_report, run_checks

    checks = run_checks(cfg, porta=porta, modalita=modalita)
    if exit_code(checks) == 0:
        return True
    print(format_report(checks, modalita), file=sys.stderr)
    print("  Quando hai sistemato, rilancia. Per ricontrollare:  jarvis doctor\n",
          file=sys.stderr)
    return False


def cmd_doctor(args, cfg) -> int:
    """Controlla tutti i prerequisiti in una volta e dice cosa fare.

    Esiste perche' i comandi si fermano al primo pezzo mancante, e chi e'
    bloccato ha bisogno dell'elenco completo, non del primo errore.
    """
    import json as _json

    from .diagnostics import exit_code, format_report, run_checks

    checks = run_checks(cfg, porta=args.port, modalita=args.mode)
    if args.json:
        print(_json.dumps([c.to_dict() for c in checks], ensure_ascii=False, indent=2))
    else:
        print(format_report(checks, args.mode))
    return exit_code(checks)


def cmd_enroll(args, cfg) -> int:
    from .speaker.embedder import build_embedder
    from .speaker.enroll import enroll_from_files, enroll_interactive

    embedder = build_embedder(cfg.get("speaker.model"), "auto")
    path = cfg.resolve_path("speaker.profile_path")
    sample_rate = int(cfg.get("audio.sample_rate", 16000))

    if args.files:
        profile = enroll_from_files(embedder, args.files, path, sample_rate=sample_rate)
        print(f"Profilo creato da {len(args.files)} file: {path}")
    else:
        profile = enroll_interactive(
            embedder, path, sample_rate=sample_rate,
            phrase_seconds=args.seconds, device=cfg.get("audio.input_device"),
        )
    print(f"{len(profile.embeddings)} impronte, {profile.sample_seconds:.0f}s di voce.")
    print("\nProssimo passo consigliato:  jarvis calibrate")
    return 0


def cmd_cohort(args, cfg) -> int:
    from .speaker.embedder import build_embedder
    from .speaker.enroll import build_cohort_from_files

    embedder = build_embedder(cfg.get("speaker.model"), "auto")
    cohort = build_cohort_from_files(
        embedder, args.files, cfg.resolve_path("speaker.cohort.path", "profiles/cohort.npz")
    )
    print(f"Coorte: {cohort.size} impronte di altre voci.")
    print("Con la coorte popolata il sistema diventa piu' severo verso chi ti somiglia.")
    return 0


def cmd_calibrate(args, cfg) -> int:
    """Controlla la qualita' del profilo e propone le soglie."""
    from .speaker.enroll import profile_consistency, suggest_threshold
    from .speaker.profile import Cohort, VoiceProfile

    profile = VoiceProfile.load(cfg.resolve_path("speaker.profile_path"))
    cohort = Cohort.load(cfg.resolve_path("speaker.cohort.path", "profiles/cohort.npz"))

    consistency = profile_consistency(profile)
    print(f"Impronte nel profilo : {len(profile.embeddings)}")
    print(f"Voce registrata      : {profile.sample_seconds:.0f}s")
    print(f"Coerenza interna     : {consistency:.3f}  (sopra 0.70 e' buono)")
    print(f"Voci estranee note   : {cohort.size}")

    if consistency < 0.55:
        print("\nCoerenza bassa: le registrazioni sono disomogenee (rumore, microfoni")
        print("diversi, o qualcun altro ha letto una frase). Conviene rifare l'arruolamento.")

    suggestion = suggest_threshold(profile, cohort)
    print("\nSoglie suggerite per config/local.yaml:\n")
    print("speaker:")
    print(f"  accept_threshold: {suggestion['accept_threshold']}")
    print(f"  continue_threshold: {suggestion['continue_threshold']}")
    if "separation" in suggestion:
        print(f"\nSeparazione io/altri: {suggestion['separation']:+.3f}")
    print(f"Nota: {suggestion['note']}")
    return 0


def cmd_record(args, cfg) -> int:
    """Registra un file audio: serve a preparare il materiale per `benchmark`."""
    import soundfile as sf

    from .audio.capture import MicrophoneStream

    sample_rate = int(cfg.get("audio.sample_rate", 16000))
    mic = MicrophoneStream(sample_rate, int(cfg.get("audio.frame_ms", 20)), cfg.get("audio.input_device"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    input(f"Premi INVIO e parla per {args.seconds:.0f} secondi (Ctrl-C per fermarti prima)... ")
    frames, collected = [], 0.0
    mic.start()
    try:
        while collected < args.seconds:
            frame = mic.read(timeout=0.5)
            if frame is None:
                continue
            frames.append(frame)
            collected += frame.size / sample_rate
            print(f"\r  {collected:5.1f}s / {args.seconds:.0f}s", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()

    if not frames:
        print("\nNessun audio registrato.", file=sys.stderr)
        return 1

    import numpy as np

    audio = np.concatenate(frames)
    sf.write(str(out), audio, sample_rate)
    print(f"\n\nSalvato: {out}  ({audio.size / sample_rate:.1f}s)")

    from .speaker.enroll import _quality_warning

    avviso = _quality_warning(audio)
    if avviso:
        print(f"Attenzione: {avviso}")
    return 0


def cmd_benchmark(args, cfg) -> int:
    """La prova vera: quante volte sbaglia, e in che direzione.

    Non basta "sembra funzionare": servono due numeri, e uno dei due (i falsi
    accessi) deve essere zero.
    """
    import json as _json

    from .speaker.benchmark import format_report, run_benchmark

    _, verifier = _build_verifier(cfg)
    print(f"Valuto {len(args.mine)} registrazioni tue e {len(args.others)} di altri...")
    print(f"Configurazione: soglia {verifier.cfg.accept_threshold}, "
          f"margine {verifier.cfg.reject_margin}, coorte {verifier.cohort.size} voci\n")

    result = run_benchmark(verifier, args.mine, args.others, turn_seconds=args.turn_seconds)
    if args.json:
        print(_json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    # Esce con 1 se un estraneo e' passato: cosi' si puo' usare in uno script.
    return 0 if result.far <= 0.0 else 1


def cmd_diag(args, cfg) -> int:
    """Ascolta per N secondi e riporta, finestra per finestra, chi sente.

    E' il comando da usare NELLA STANZA vera prima di fidarsi: mostra i
    punteggi reali con il rumore, le distanze e le voci di quel posto.
    """
    import time

    import numpy as np

    from .audio.capture import MicrophoneStream
    from .audio.vad import build_vad

    _, verifier = _build_verifier(cfg)
    sample_rate = int(cfg.get("audio.sample_rate", 16000))
    vad = build_vad(cfg.get("vad.provider", "silero"), sample_rate, float(cfg.get("vad.threshold", 0.55)))

    mic = MicrophoneStream(sample_rate, int(cfg.get("audio.frame_ms", 20)), cfg.get("audio.input_device"))
    print(f"Ascolto per {args.seconds} secondi. Parla, e fai parlare anche gli altri.\n")
    print(f"{'t':>6}  {'io':>6}  {'altri':>6}  {'margine':>8}  {'dB':>7}  esito")
    print("-" * 52)

    mic.start()
    raccolte: list = []
    buffer = np.zeros(0, dtype=np.float32)
    window = int(verifier.cfg.window_sec * sample_rate)
    hop = int(verifier.cfg.hop_sec * sample_rate)
    index = 0
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < args.seconds:
            frame = mic.read(timeout=0.5)
            if frame is None:
                continue
            if not vad.is_speech(frame):
                verifier.observe_noise(frame)
                continue
            buffer = np.concatenate([buffer, frame])
            while buffer.size >= window:
                score = verifier.score_window(buffer[:window], index)
                raccolte.append(score)
                buffer = buffer[hop:]
                index += 1
                esito = {"owner": "SEI TU", "stranger": "altra voce", "uncertain": "incerto"}[
                    score.decision.value
                ]
                print(
                    f"{time.perf_counter() - started:6.1f}  {score.owner_score:6.3f}  "
                    f"{score.cohort_score:6.3f}  {score.margin:8.3f}  {score.level_db:7.1f}  {esito}"
                )
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()

    tue = [s for s in raccolte if s.decision.value == "owner"]
    altre = [s for s in raccolte if s.decision.value == "stranger"]
    print("\n" + "-" * 52)
    print(f"Finestre analizzate    : {len(raccolte)}")
    print(f"  attribuite a te      : {len(tue)}")
    print(f"  attribuite ad altri  : {len(altre)}")
    if tue:
        print(f"Punteggio mediano tuo  : {float(np.median([s.owner_score for s in tue])):.3f}")
    if altre:
        print(f"Punteggio mediano altri: {float(np.median([s.owner_score for s in altre])):.3f}")
    print(f"Rumore di fondo stimato: {verifier.noise.value_db:.1f} dB")
    print(f"Soglia in uso          : {verifier.cfg.accept_threshold} "
          f"(margine {verifier.cfg.reject_margin})")

    print("\nQuesto e' un monitor, non una misura: dice cosa sta succedendo adesso,")
    print("non quante volte sbaglia. Per il verdetto con i numeri:")
    print("\n  jarvis record --out mie/1.wav --seconds 60      (tu che parli)")
    print("  jarvis record --out altri/1.wav --seconds 60    (un'altra persona)")
    print("  jarvis benchmark --mine mie/*.wav --others altri/*.wav")
    return 0


def cmd_run(args, cfg) -> int:
    """Avvia la sessione vocale."""
    from .asr import build_transcriber
    from .audio.capture import MicrophoneStream
    from .audio.playback import Speaker
    from .audio.vad import build_vad
    from .session.orchestrator import VoiceSession
    from .tts import build_synthesizer

    if not _prerequisiti_ok(cfg, modalita="pc"):
        return 1

    _, verifier = _build_verifier(cfg)
    listone, _, _, agent = _build_domain(cfg)
    sample_rate = int(cfg.get("audio.sample_rate", 16000))

    mic = MicrophoneStream(sample_rate, int(cfg.get("audio.frame_ms", 20)), cfg.get("audio.input_device"))
    session = VoiceSession(
        mic=mic,
        vad=build_vad(cfg.get("vad.provider", "silero"), sample_rate, float(cfg.get("vad.threshold", 0.55))),
        verifier=verifier,
        transcriber=build_transcriber(cfg),
        agent=agent,
        synthesizer=build_synthesizer(cfg),
        speaker=Speaker(device=cfg.get("audio.output_device")),
        cfg=cfg,
    )

    print("JarvisEria in ascolto. Rispondo solo a te. Ctrl-C per chiudere.")
    if not listone:
        print("Nota: listone non caricato, posso parlare di strategia ma non di quotazioni.")
    stats = session.run(greeting=cfg.get("session.greeting"))

    # La coorte imparata in questa stanza serve anche la prossima volta.
    if cfg.get("speaker.cohort.auto_learn", True) and verifier.cohort.size:
        verifier.cohort.save(cfg.resolve_path("speaker.cohort.path", "profiles/cohort.npz"))
    if cfg.get("speaker.adaptation.enabled", True):
        verifier.profile.save(cfg.resolve_path("speaker.profile_path"))
    print("\n" + stats.summary())
    return 0


def cmd_serve(args, cfg) -> int:
    """Modalita' telefono: il telefono fa da microfono, il PC fa il lavoro.

    Serve https e non e' un vezzo: senza contesto sicuro il browser del telefono
    non concede il microfono, ne' su iOS ne' su Android.
    """
    from aiohttp import web as aioweb

    from .web.server import build_server
    from .web.tls import build_ssl_context, local_ip

    if not _prerequisiti_ok(cfg, modalita="telefono", porta=args.port):
        return 1

    server = build_server(cfg)
    ip = args.host if args.host not in (None, "0.0.0.0") else local_ip()
    ssl_context = None
    if not args.insecure:
        ssl_context = build_ssl_context(cfg.resolve_path("web.cert_dir", "profiles/tls"), ip)

    schema = "http" if args.insecure else "https"
    url = f"{schema}://{ip}:{args.port}"

    print("\n" + "=" * 58)
    print("  Dal telefono, sulla STESSA rete Wi-Fi del PC, apri:")
    print(f"\n      {url}\n")
    if not args.insecure:
        print("  Il certificato e' autofirmato, quindi la prima volta il browser")
        print("  mostra un avviso di sicurezza: e' atteso. Apri i dettagli e")
        print("  scegli di procedere (iOS: 'Mostra dettagli' -> 'Visita il sito').")
    else:
        print("  ATTENZIONE: --insecure serve solo per provare da questo stesso PC.")
        print("  Da telefono il microfono NON funzionera' senza https.")
    print("\n  Poi tocca 'Collega' e concedi il microfono.")
    print("  Usa gli auricolari: e' anche la condizione migliore per")
    print("  farsi riconoscere in mezzo ad altre voci.")
    print("=" * 58 + "\n")

    aioweb.run_app(
        server.app, host=args.host or "0.0.0.0", port=args.port,
        ssl_context=ssl_context, print=None,
    )
    return 0


def cmd_chat(args, cfg) -> int:
    from .session.orchestrator import TextSession

    listone, _, _, agent = _build_domain(cfg)
    if not listone:
        print("Nota: listone non caricato (vedi data/README.md).\n")
    session = TextSession(agent, cfg.get("log.transcript"))
    if args.message:
        print(session.ask(" ".join(args.message)))
        return 0
    session.run()
    return 0


def cmd_devices(args, cfg) -> int:
    from .audio.capture import list_devices

    print(list_devices())
    print("\nImposta il dispositivo scelto in config/local.yaml (audio.input_device).")
    return 0


def cmd_plan(args, cfg) -> int:
    _, auction, _, _ = _build_domain(cfg)
    if args.strategy:
        auction.apply_strategy(args.strategy)
    plan = auction.plan()
    print(f"Budget {auction.budget} crediti — strategia: {args.strategy or 'equilibrata'}\n")
    for role, detail in plan.items():
        prezzi = ", ".join(str(p) for p in detail["prezzi_obiettivo"])
        print(f"{role}: {detail['budget_reparto']:>4} crediti su {detail['slot']} slot   -> {prezzi}")
    print("\nI prezzi obiettivo sono il punto di partenza: in asta contano i crediti residui.")
    return 0


def cmd_lineup(args, cfg) -> int:
    from .fanta.formation import best_formation, build_formation
    from .fanta.listone import load_listone

    listone = load_listone(cfg.get("fanta.listone_path"))
    if not listone:
        print("Serve il listone caricato: vedi data/README.md", file=sys.stderr)
        return 1

    players, missing = [], []
    for name in args.players:
        found = listone.search(name, limit=1)
        (players.append(found[0][0]) if found else missing.append(name))
    if missing:
        print(f"Non trovati: {', '.join(missing)}", file=sys.stderr)
    if not players:
        return 1

    formation = build_formation(players, args.module) if args.module else best_formation(players)
    if args.json:
        print(json.dumps(formation.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"Modulo {formation.module} — totale atteso {formation.total:.1f}\n")
    for score in formation.starters:
        print(f"  {score.player.role}  {score.player.name:<22} {score.expected:5.2f}")
    if formation.bench:
        print("\nPanchina (in ordine):")
        for score in formation.bench[:6]:
            print(f"  {score.player.role}  {score.player.name:<22} {score.expected:5.2f}")
    for warning in formation.warnings:
        print(f"\n! {warning}")
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Assistente vocale di fantacalcio che risponde solo alla tua voce.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", type=Path, help="file di configurazione aggiuntivo")
    parser.add_argument("--verbose", "-v", action="store_true", help="log di debug")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="controlla cosa manca per partire")
    p.add_argument("--mode", choices=["telefono", "pc"], default="telefono",
                   help="quale modalita' vuoi usare (default: telefono)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("enroll", help="registra la tua voce")
    p.add_argument("--seconds", type=float, default=5.0, help="durata di ogni frase")
    p.add_argument("--files", nargs="+", help="usa file audio invece del microfono")
    p.set_defaults(func=cmd_enroll)

    p = sub.add_parser("cohort", help="registra le voci degli altri")
    p.add_argument("--files", nargs="+", required=True, help="registrazioni di altre persone")
    p.set_defaults(func=cmd_cohort)

    p = sub.add_parser("calibrate", help="controlla il profilo e proponi le soglie")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("record", help="registra un file audio per la prova")
    p.add_argument("--out", required=True, help="file WAV da creare")
    p.add_argument("--seconds", type=float, default=60.0)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("benchmark", help="LA PROVA: misura falsi accessi e falsi rifiuti")
    p.add_argument("--mine", nargs="+", required=True, help="registrazioni della TUA voce")
    p.add_argument("--others", nargs="+", required=True, help="registrazioni di ALTRE persone")
    p.add_argument("--turn-seconds", type=float, default=4.0, help="durata di un turno simulato")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("diag", help="monitor dal vivo: chi sto sentendo adesso")
    p.add_argument("--seconds", type=float, default=30.0)
    p.set_defaults(func=cmd_diag)

    p = sub.add_parser("run", help="avvia la conversazione vocale")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("serve", help="modalita' telefono: il telefono fa da microfono")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", help="interfaccia su cui ascoltare (default: tutte)")
    p.add_argument("--insecure", action="store_true",
                   help="http invece di https: solo per prove da questo PC")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("chat", help="conversazione da tastiera")
    p.add_argument("message", nargs="*", help="domanda singola; senza, entra in interattivo")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("devices", help="elenco dei dispositivi audio")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("plan", help="piano d'asta")
    p.add_argument("--strategy", help="equilibrata | modificatore | tre_top_attacco | centrocampo_forte")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("lineup", help="formazione")
    p.add_argument("players", nargs="+", help="nomi dei giocatori disponibili")
    p.add_argument("--module", help="forza un modulo, es. 3-4-3")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lineup)

    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    setup_logging("DEBUG" if args.verbose else cfg.get("log.level", "INFO"), cfg.get("log.file"))
    try:
        return args.func(args, cfg)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"\nErrore: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

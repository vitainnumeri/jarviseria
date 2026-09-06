"""Certificato TLS locale.

Vincolo del browser, non nostro: `getUserMedia` funziona solo in un "contesto
sicuro". Da `http://192.168.1.20:8765` il telefono NON dara' mai accesso al
microfono, ne' su iOS ne' su Android, e non c'e' impostazione che lo cambi.

Quindi il server parla https. Il certificato e' autofirmato e generato in
locale: la prima volta il browser mostra un avviso da accettare a mano. E'
seccante ma e' l'unica strada che non richiede un dominio pubblico o un tunnel
che faccia passare la tua voce da un servizio terzo.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
from pathlib import Path

from ..utils.logging import get_logger

log = get_logger(__name__)

CERT_VALIDITY_DAYS = 825  # limite accettato dai browser per i certificati


def local_ip() -> str:
    """Indirizzo del PC sulla rete locale, quello da digitare sul telefono.

    Si apre un socket UDP verso un indirizzo esterno senza inviare nulla: serve
    solo a farsi dire dal sistema operativo quale interfaccia userebbe. Molto
    piu' affidabile di `gethostbyname(gethostname())`, che su Linux spesso
    risponde 127.0.0.1.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def generate_certificate(cert_path: Path, key_path: Path, ip: str) -> None:
    """Genera un certificato autofirmato valido per l'IP locale.

    L'IP finisce nel SubjectAltName: senza, i browser moderni rifiutano il
    certificato ancora prima di mostrare l'avviso, e non c'e' modo di procedere.
    """
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
        "-days", str(CERT_VALIDITY_DAYS), "-nodes",
        "-keyout", str(key_path), "-out", str(cert_path),
        "-subj", "/CN=jarviseria",
        "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=60)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "openssl non trovato: serve per creare il certificato locale.\n"
            "  Debian/Ubuntu:  sudo apt install openssl\n"
            "  macOS:          gia' presente, oppure  brew install openssl"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"creazione del certificato fallita:\n{exc.stderr.decode(errors='replace')}"
        ) from exc
    key_path.chmod(0o600)
    log.info("certificato creato per %s (valido %d giorni)", ip, CERT_VALIDITY_DAYS)


def ensure_certificate(directory: Path, ip: str) -> tuple[Path, Path]:
    """Restituisce (certificato, chiave), creandoli se mancano.

    Il certificato viene rigenerato quando cambia l'IP del PC: capita a ogni
    cambio di rete, e un certificato con l'IP sbagliato non funziona.
    """
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    marker = directory / "cert.ip"

    if cert_path.exists() and key_path.exists() and marker.exists():
        if marker.read_text(encoding="utf-8").strip() == ip:
            return cert_path, key_path
        log.info("l'indirizzo del PC e' cambiato: rigenero il certificato")

    generate_certificate(cert_path, key_path, ip)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(ip, encoding="utf-8")
    return cert_path, key_path


def build_ssl_context(directory: Path, ip: str) -> ssl.SSLContext:
    """Contesto TLS pronto per il server."""
    cert_path, key_path = ensure_certificate(directory, ip)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context

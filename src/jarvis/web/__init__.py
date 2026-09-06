"""Modalita' telefono: il telefono fa da microfono e altoparlante, il PC lavora.

E' anche la configurazione migliore dal punto di vista del riconoscimento: con
gli auricolari il microfono sta a pochi centimetri dalla bocca, e il vantaggio
di livello sulle altre voci della stanza e' cosi' grande che nessun parametro
software puo' pareggiarlo.
"""

from .transport import DOWNLINK_RATE, UPLINK_RATE, RemoteAudioSource, WebSocketSpeaker

__all__ = ["RemoteAudioSource", "WebSocketSpeaker", "UPLINK_RATE", "DOWNLINK_RATE"]

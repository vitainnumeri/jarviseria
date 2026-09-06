"""JarvisEria: assistente vocale full-duplex che risponde solo al proprietario.

Il pacchetto e' organizzato in strati indipendenti e sostituibili:

    audio/    cattura, riproduzione, VAD, DSP
    speaker/  identificazione biometrica del parlante (il cuore del progetto)
    asr/      trascrizione
    llm/      agente conversazionale e strumenti
    tts/      sintesi vocale
    fanta/    dominio fantacalcio (listone, asta, formazione)
    session/  orchestratore full-duplex
"""

__version__ = "0.1.0"

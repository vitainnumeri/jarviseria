"""Test dell'agente: ciclo degli strumenti, streaming e potatura della storia.

Il client Anthropic e' sostituito da un finto che riproduce la forma dell'API
(streaming di testo + blocchi tool_use), cosi' la logica del ciclo si collauda
senza rete e senza chiave.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jarvis.config import Config, PROJECT_ROOT
from jarvis.fanta.auction import AuctionState
from jarvis.fanta.listone import Listone
from jarvis.llm.agent import Conversation, FantaAgent
from jarvis.llm.prompts import system_prompt
from jarvis.llm.tools import FantaTools

ESEMPIO = PROJECT_ROOT / "data" / "esempio_listone_PLACEHOLDER.csv"


# --------------------------------------------------- finto client Anthropic
@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUse:
    name: str
    input: dict
    id: str = "tool_1"
    type: str = "tool_use"


@dataclass
class FakeMessage:
    content: list


class FakeStream:
    def __init__(self, message: FakeMessage):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for block in self._message.content:
            if block.type == "text":
                for word in block.text.split(" "):
                    yield word + " "

    def get_final_message(self) -> FakeMessage:
        return self._message


class FakeMessages:
    def __init__(self, scripted: list[FakeMessage]):
        self.scripted = list(scripted)
        self.requests: list[dict] = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        message = self.scripted.pop(0) if self.scripted else FakeMessage([FakeTextBlock("Ok.")])
        return FakeStream(message)


@dataclass
class FakeClient:
    scripted: list = field(default_factory=list)

    def __post_init__(self):
        self.messages = FakeMessages(self.scripted)


@pytest.fixture
def cfg() -> Config:
    return Config({
        "llm": {"model": "claude-opus-5", "max_tokens": 256, "history_turns": 3},
        "fanta": {"mode": "classic", "budget": 500, "slots": {"P": 3, "D": 8, "C": 8, "A": 6}},
    })


@pytest.fixture
def tools() -> FantaTools:
    return FantaTools(Listone.from_csv(ESEMPIO), AuctionState(budget=500))


def build_agent(tools, cfg, scripted) -> FantaAgent:
    return FantaAgent(tools, cfg, client=FakeClient(scripted))


# ------------------------------------------------------------- streaming

def test_la_risposta_arriva_a_pezzi(tools, cfg):
    agent = build_agent(tools, cfg, [FakeMessage([FakeTextBlock("Fino a centottanta crediti.")])])
    pezzi = list(agent.respond("quanto offro per Lautaro?"))
    assert len(pezzi) > 1                     # streaming vero, non una stringa unica
    assert "".join(pezzi).strip() == "Fino a centottanta crediti."


def test_la_conversazione_conserva_lo_scambio(tools, cfg):
    agent = build_agent(tools, cfg, [FakeMessage([FakeTextBlock("Ok.")])])
    agent.respond_text("ciao")
    assert agent.conversation.messages[0]["role"] == "user"
    assert agent.conversation.messages[-1]["role"] == "assistant"


# --------------------------------------------------------- ciclo strumenti

def test_lo_strumento_viene_eseguito_e_il_risultato_torna_al_modello(tools, cfg):
    agent = build_agent(tools, cfg, [
        FakeMessage([FakeToolUse("consiglio_offerta", {"nome": "Lautaro Martinez"})]),
        FakeMessage([FakeTextBlock("Puoi arrivare a novantuno.")]),
    ])
    risposta = agent.respond_text("quanto offro per Lautaro?")

    assert "novantuno" in risposta
    ultimo = agent.conversation.messages[-1]
    assert ultimo["role"] == "assistant"
    # Fra i messaggi deve esserci il risultato dello strumento.
    assert any(
        isinstance(m["content"], list) and m["content"] and m["content"][0].get("type") == "tool_result"
        for m in agent.conversation.messages
    )


def test_lo_strumento_cambia_davvero_lo_stato_dell_asta(tools, cfg):
    agent = build_agent(tools, cfg, [
        FakeMessage([FakeToolUse("registra_acquisto", {"nome": "Lautaro Martinez", "prezzo": 180})]),
        FakeMessage([FakeTextBlock("Registrato.")]),
    ])
    agent.respond_text("preso Lautaro a centottanta")
    assert tools.auction.credits_left == 320
    assert tools.auction.roster.count("A") == 1


def test_un_errore_dello_strumento_torna_al_modello_invece_di_esplodere(tools, cfg):
    agent = build_agent(tools, cfg, [
        FakeMessage([FakeToolUse("registra_acquisto", {"nome": "Lautaro Martinez", "prezzo": 9999})]),
        FakeMessage([FakeTextBlock("Non hai abbastanza crediti.")]),
    ])
    assert "crediti" in agent.respond_text("preso Lautaro a novemilanovecento")


def test_il_ciclo_degli_strumenti_ha_un_tetto(tools, cfg):
    """Se il modello continuasse a chiamare strumenti, la telefonata non deve bloccarsi."""
    infinito = [FakeMessage([FakeToolUse("stato_asta", {})]) for _ in range(20)]
    agent = build_agent(tools, cfg, infinito)
    assert "girando a vuoto" in agent.respond_text("come va l'asta?")


# ------------------------------------------------------------ storia

def test_la_storia_viene_potata_ma_resta_coerente(cfg, tools):
    """Un tool_result orfano farebbe rifiutare la richiesta dall'API."""
    conversation = Conversation(max_turns=2)
    for i in range(10):
        conversation.add("user", f"domanda {i}")
        conversation.add("assistant", [{"type": "text", "text": f"risposta {i}"}])
    assert len(conversation.messages) <= 4
    assert conversation.messages[0]["role"] == "user"


def test_reset_azzera_la_conversazione(tools, cfg):
    agent = build_agent(tools, cfg, [FakeMessage([FakeTextBlock("Ok.")])])
    agent.respond_text("ciao")
    agent.reset()
    assert agent.conversation.messages == []


# ------------------------------------------------------------- istruzioni

def test_le_istruzioni_dicono_di_parlare_come_al_telefono():
    prompt = system_prompt(listone_loaded=True, listone_size=500)
    assert "telefono" in prompt
    assert "markdown" in prompt


def test_senza_listone_le_istruzioni_vietano_di_inventare_prezzi():
    prompt = system_prompt(listone_loaded=False)
    assert "NON e' caricato" in prompt
    assert "non hai quotazioni" in prompt.lower()


def test_le_istruzioni_riportano_le_regole_della_lega():
    prompt = system_prompt(mode="mantra", budget=1000, slots={"P": 3, "D": 8, "C": 8, "A": 6})
    assert "mantra" in prompt
    assert "1000 crediti" in prompt


def test_l_agente_costruisce_le_istruzioni_dalla_configurazione(tools, cfg):
    agent = build_agent(tools, cfg, [])
    assert "500 crediti" in agent.system
    assert f"{len(tools.listone)} giocatori" in agent.system

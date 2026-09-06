"""L'agente conversazionale.

Genera in streaming perche' la latenza percepita e' tutto: la prima frase deve
partire verso la sintesi vocale mentre il modello sta ancora scrivendo la
seconda. Il ciclo degli strumenti e' esplicito (chiama, esegui, rimanda) e ha un
tetto di iterazioni, cosi' una telefonata non si blocca mai.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterator

from ..config import require_env
from ..utils.logging import get_logger
from .prompts import system_prompt
from .tools import TOOL_SCHEMAS, FantaTools

log = get_logger(__name__)

MAX_TOOL_ROUNDS = 5


@dataclass
class Turn:
    role: str
    content: str


@dataclass
class Conversation:
    """Storia della conversazione, potata per non far crescere il contesto."""

    max_turns: int = 12
    messages: list[dict] = field(default_factory=list)

    def add(self, role: str, content) -> None:
        self.messages.append({"role": role, "content": content})
        self._prune()

    def _prune(self) -> None:
        limit = self.max_turns * 2
        if len(self.messages) <= limit:
            return
        # Taglio dall'inizio, ma mai a meta' di uno scambio con strumenti:
        # un `tool_result` orfano fa rifiutare la richiesta dall'API.
        cut = len(self.messages) - limit
        while cut < len(self.messages) and self.messages[cut]["role"] != "user":
            cut += 1
        self.messages = self.messages[cut:]

    def clear(self) -> None:
        self.messages = []


class FantaAgent:
    """Assistente di fantacalcio basato su Claude, con strumenti di dominio."""

    def __init__(self, tools: FantaTools, cfg, *, client=None):
        self.tools = tools
        self.cfg = cfg
        self.model = cfg.get("llm.model", "claude-opus-5")
        self.max_tokens = int(cfg.get("llm.max_tokens", 1024))
        self.temperature = float(cfg.get("llm.temperature", 0.3))
        self.conversation = Conversation(max_turns=int(cfg.get("llm.history_turns", 12)))
        self._client = client
        self.system = system_prompt(
            mode=cfg.get("fanta.mode", "classic"),
            budget=int(cfg.get("fanta.budget", 500)),
            slots=cfg.get("fanta.slots", {}),
            listone_loaded=bool(tools.listone),
            listone_size=len(tools.listone),
        )

    # ---------------------------------------------------------------- client
    def _ensure_client(self):
        if self._client is None:  # pragma: no cover - rete
            import anthropic

            require_env("ANTHROPIC_API_KEY", hint="Serve per far ragionare l'assistente.")
            self._client = anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------- streaming
    def respond(self, user_text: str) -> Iterator[str]:
        """Genera la risposta in streaming, eseguendo gli strumenti necessari.

        Restituisce solo il testo destinato alla voce: il traffico degli
        strumenti resta interno.
        """
        self.conversation.add("user", user_text)
        client = self._ensure_client()

        for round_index in range(MAX_TOOL_ROUNDS):
            blocks: list[dict] = []
            text_parts: list[str] = []

            with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system,
                tools=TOOL_SCHEMAS,
                messages=self.conversation.messages,
            ) as stream:
                for event in stream.text_stream:
                    text_parts.append(event)
                    yield event
                final = stream.get_final_message()

            for block in final.content:
                if block.type == "text":
                    blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )

            self.conversation.add("assistant", blocks)
            tool_uses = [b for b in blocks if b["type"] == "tool_use"]
            if not tool_uses:
                return

            results = []
            for call in tool_uses:
                log.info("strumento %s(%s)", call["name"], json.dumps(call["input"], ensure_ascii=False))
                output = self.tools.dispatch(call["name"], call["input"])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(output, ensure_ascii=False, default=str),
                })
            self.conversation.add("user", results)

        # Tetto raggiunto: meglio dirlo che restare muti.
        yield " Sto girando a vuoto sugli strumenti, riformuliamo la domanda."

    def respond_text(self, user_text: str) -> str:
        """Versione non incrementale, comoda per i test e la modalita' testuale."""
        return "".join(self.respond(user_text))

    def reset(self) -> None:
        self.conversation.clear()

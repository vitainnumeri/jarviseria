"""Conoscenza di dominio del fantacalcio.

I regolamenti cambiano da lega a lega: qui stanno i valori PREDEFINITI piu'
diffusi (impostazioni standard Fantacalcio.it). L'agente e' istruito a
verificare sempre le regole della lega dell'utente prima di dare numeri, invece
di dare per scontato questo schema.
"""

from __future__ import annotations

# ------------------------------------------------------------------- ruoli
RUOLI_CLASSIC = {
    "P": "Portiere",
    "D": "Difensore",
    "C": "Centrocampista",
    "A": "Attaccante",
}

RUOLI_MANTRA = {
    "Por": "Portiere",
    "Dc": "Difensore centrale",
    "Dd": "Difensore destro",
    "Ds": "Difensore sinistro",
    "E": "Esterno basso",
    "M": "Mediano",
    "C": "Centrale di centrocampo",
    "W": "Ala",
    "T": "Trequartista",
    "A": "Attaccante",
    "Pc": "Punta centrale",
}

ROSA_STANDARD = {"P": 3, "D": 8, "C": 8, "A": 6}  # 25 giocatori

# ------------------------------------------------------- bonus e malus base
BONUS_MALUS = {
    "gol_segnato": 3.0,
    "gol_subito_portiere": -1.0,
    "rigore_segnato": 3.0,
    "rigore_sbagliato": -3.0,
    "rigore_parato": 3.0,
    "autogol": -2.0,
    "assist": 1.0,          # opzionale: molte leghe lo attivano
    "ammonizione": -0.5,
    "espulsione": -1.0,
    "portiere_imbattuto": 1.0,  # opzionale
}

# Modificatore di difesa: media voto di portiere + 3 migliori difensori.
MODIFICATORE_DIFESA = [
    (6.00, 6.24, 1), (6.25, 6.49, 2), (6.50, 6.74, 3),
    (6.75, 6.99, 4), (7.00, 7.24, 5), (7.25, 99.0, 6),
]

# --------------------------------------------------- ripartizione del budget
# Percentuali di riferimento per un'asta classica a 500 crediti.
# Non sono dogmi: sono il punto di partenza da cui il motore d'asta lavora.
BUDGET_SPLIT_DEFAULT = {"P": 0.07, "D": 0.15, "C": 0.30, "A": 0.48}

BUDGET_SPLIT_STRATEGIE = {
    "equilibrata": {"P": 0.07, "D": 0.15, "C": 0.30, "A": 0.48},
    "modificatore": {"P": 0.10, "D": 0.24, "C": 0.28, "A": 0.38},   # punta sul modificatore di difesa
    "tre_top_attacco": {"P": 0.05, "D": 0.12, "C": 0.25, "A": 0.58},
    "centrocampo_forte": {"P": 0.06, "D": 0.14, "C": 0.40, "A": 0.40},
}

# Quanta parte del budget di un reparto va sul giocatore migliore di quel reparto.
PIANO_FASCE = {
    "P": [0.70, 0.20, 0.10],
    "D": [0.28, 0.20, 0.14, 0.12, 0.10, 0.07, 0.05, 0.04],
    "C": [0.30, 0.22, 0.16, 0.11, 0.08, 0.06, 0.04, 0.03],
    "A": [0.38, 0.26, 0.16, 0.10, 0.06, 0.04],
}

MODULI_CLASSIC = {
    "3-4-3": (3, 4, 3), "3-5-2": (3, 5, 2), "4-3-3": (4, 3, 3),
    "4-4-2": (4, 4, 2), "4-5-1": (4, 5, 1), "5-3-2": (5, 3, 2),
    "5-4-1": (5, 4, 1), "3-4-1-2": (3, 5, 2), "4-2-3-1": (4, 5, 1),
}

PRINCIPI_ASTA = """\
Principi d'asta che l'assistente applica:

1. I crediti non spesi valgono zero. A fine asta si deve arrivare con 1-2 crediti
   per slot residuo, non con 60 crediti "risparmiati" e una rosa mediocre.
2. Non esiste il prezzo giusto in assoluto: esiste il prezzo giusto RISPETTO alla
   stanza. Se in quella lega i portieri vanno via a 40, il valore teorico di 25
   e' irrilevante.
3. Il vincolo duro e' sempre lo stesso: crediti residui meno il numero di slot
   ancora da riempire. Non si offre mai oltre quella cifra.
4. Meglio un titolare noioso da 6 fisso che una scommessa da 4 presenze.
   La continuita' batte il picco: la fantamedia si costruisce in 38 giornate.
5. I rigoristi valgono un sovrapprezzo reale (circa 4-6 rigori a stagione sono
   12-18 punti bonus). Vanno pagati, ma solo se sono anche titolari.
6. Difensori: contano i bonus (gol/assist) e la squadra che subisce poco. Con il
   modificatore di difesa attivo cambiano completamente le priorita'.
7. Nei primi slot chiamati si paga il "premio di apertura": conviene lasciare che
   i primi due o tre nomi vadano fuori mercato e inserirsi subito dopo.
8. Il finale d'asta e' dove si vince: chi arriva con crediti e slot liberi
   prende i titolari rimasti a prezzo di saldo."""

PRINCIPI_FORMAZIONE = """\
Principi di formazione che l'assistente applica:

1. Prima di tutto la certezza di scendere in campo: un titolare da 6 vale piu' di
   un fuoriclasse in panchina. Si controllano probabili formazioni, infortuni,
   squalifiche e diffidati.
2. Il calendario pesa: casa/trasferta e la solidita' dell'avversario spostano la
   fantamedia attesa piu' di quanto la gente creda.
3. I bonus sono concentrati: rigoristi, tiratori di punizioni e di calci d'angolo
   valgono un posto in piu' rispetto al solo voto.
4. Il modulo si sceglie DOPO aver visto chi gioca, non prima. Si sceglie quello
   che massimizza i titolari con bonus, non quello "preferito".
5. La panchina va ordinata pensando alle sostituzioni automatiche: primo cambio
   il piu' probabile titolare fra i non schierati.
6. Con il modificatore di difesa attivo conviene il reparto completo di una sola
   squadra solida: i voti si muovono insieme."""

GLOSSARIO = {
    "fantamedia": "media voto piu' bonus e malus, divisa per le presenze",
    "quotazione": "prezzo di riferimento del giocatore nel listone",
    "FVM": "Fanta Valore di Mercato: indice di valore piu' dinamico della quotazione",
    "slot": "posto libero in rosa da riempire",
    "modificatore di difesa": "bonus ai punti in base alla media voto del reparto difensivo",
    "asta di riparazione": "sessione di mercato infrastagionale",
    "svincolati": "giocatori non assegnati, prendibili a stagione in corso",
    "sniping": "aggiudicarsi un giocatore quando gli altri hanno finito i crediti",
}


def modificatore_difesa(media_reparto: float) -> int:
    """Punti bonus dal modificatore di difesa data la media del reparto."""
    for low, high, bonus in MODIFICATORE_DIFESA:
        if low <= media_reparto <= high:
            return bonus
    return 0

"""
Module: services.perf_dataset.textgen

Deterministic, varied-length prose for generated records.

Responsibilities:
- Produce titles, reasoning, clarification and description text whose length varies from a few words to several
  paragraphs, because search, report layout and payload size all depend on text length and uniform filler would
  give false results.

Design decisions:
- Words come from a fixed vocabulary and every choice from the caller's `random.Random`, so the same seed yields
  the same text on every host. The vocabulary is engineering prose with no real names, emails or tenant data.

Dependencies: standard library only.
"""

from __future__ import annotations

import random

_NOUNS = (
    "controller sensor actuator gateway interface payload telemetry firmware module bus protocol buffer queue scheduler "
    "latency throughput budget margin threshold operator supervisor session credential audit record archive report "
    "console display panel harness connector enclosure battery charger regulator clock timer watchdog bootloader image "
    "partition volume cluster replica shard index cache backup restore policy certificate token gateway router switch "
    "adapter driver kernel service endpoint request response schema migration release baseline variant configuration "
    "diagnostic fault alarm notification dashboard workflow approval review stakeholder contract supplier component"
).split()
_VERBS = (
    "shall provide support record validate reject retry recover isolate encrypt authenticate authorise report archive "
    "synchronise transmit receive buffer throttle degrade restore log monitor schedule expose limit enforce detect"
).split()
_ADJECTIVES = (
    "reliable secure bounded redundant deterministic configurable auditable idempotent atomic asynchronous resilient "
    "compatible portable measurable traceable least-privilege fault-tolerant real-time backward-compatible"
).split()
_QUALIFIERS = (
    "under normal load",
    "during start-up",
    "after a power loss",
    "within the stated budget",
    "for every tenant",
    "without operator action",
    "across a restart",
    "when the link is degraded",
    "at the specified temperature",
    "within two seconds",
    "for the life of the product",
    "on first use",
    "when storage is nearly full",
)


def _sentence(rng: random.Random) -> str:
    """One sentence built from the vocabulary."""
    shape = rng.randrange(4)
    noun, other = rng.choice(_NOUNS), rng.choice(_NOUNS)
    if shape == 0:
        text = f"The {rng.choice(_ADJECTIVES)} {noun} {rng.choice(_VERBS)} the {other} {rng.choice(_QUALIFIERS)}"
    elif shape == 1:
        text = f"Each {noun} must {rng.choice(_VERBS)} its {rng.choice(_ADJECTIVES)} {other} {rng.choice(_QUALIFIERS)}"
    elif shape == 2:
        text = f"A {rng.choice(_ADJECTIVES)} {noun} is needed so the {other} can {rng.choice(_VERBS)} {rng.choice(_QUALIFIERS)}"
    else:
        text = f"{noun.capitalize()} and {other} {rng.choice(_VERBS)} {rng.choice(_QUALIFIERS)}"
    return text[0].upper() + text[1:] + "."


def sentences(rng: random.Random, count: int) -> str:
    """`count` sentences joined by spaces."""
    return " ".join(_sentence(rng) for _ in range(count))


def title(rng: random.Random) -> str:
    """A short requirement-style title, 20 to ~120 characters."""
    base = f"The {rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)} shall {rng.choice(_VERBS)} the {rng.choice(_NOUNS)}"
    if rng.random() < 0.5:
        base += f" {rng.choice(_QUALIFIERS)}"
    return base[:240]


def paragraphs(rng: random.Random, *, empty_chance: float, short_max: int = 3, long_chance: float = 0.1) -> str:
    """Free text of varied length: empty, a couple of sentences, or (rarely) several paragraphs.

    Args:
        rng: The caller's seeded generator.
        empty_chance: Probability of returning an empty string.
        short_max: Most sentences in the usual short case.
        long_chance: Probability of a multi-paragraph body.
    """
    roll = rng.random()
    if roll < empty_chance:
        return ""
    if roll > 1 - long_chance:
        return "\n\n".join(sentences(rng, rng.randint(3, 6)) for _ in range(rng.randint(3, 6)))
    return sentences(rng, rng.randint(1, short_max))

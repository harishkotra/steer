"""Console state: the document, the attention boxes, the steer vectors."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field, asdict

_ids = itertools.count(1)


def new_id(prefix: str) -> str:
    return f"{prefix}{next(_ids)}"


@dataclass
class AttentionBox:
    """A span of the document the next continuation is forced to attend to."""

    text: str
    start: int
    end: int
    weight: float = 0.6
    id: str = field(default_factory=lambda: new_id("b"))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SteerVector:
    """A live-generated direction with a signed magnitude.

    ``magnitude`` runs -1..1: positive pulls toward ``plus``, negative toward
    ``minus``, and 0 is inert.  ``_delta`` is the activation vector when a
    local model is attached (see providers/mlx_provider.py).
    """

    label: str
    plus: str
    minus: str
    magnitude: float = 0.0
    target: float | None = None
    id: str = field(default_factory=lambda: new_id("v"))
    delta: object | None = None

    @property
    def pole(self) -> str:
        return self.plus if self.magnitude >= 0 else self.minus

    @property
    def strength(self) -> float:
        return min(1.0, abs(self.magnitude))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "plus": self.plus,
            "minus": self.minus,
            "magnitude": round(self.magnitude, 3),
            "target": self.target,
            "pole": self.pole,
            "strength": round(self.strength, 3),
            "live": self.delta is not None,
        }


@dataclass
class Console:
    doc: str = ""
    boxes: list[AttentionBox] = field(default_factory=list)
    vectors: list[SteerVector] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    anchor: int | None = None          # where generation resumes
    version: int = 0                   # bumps on every steer change
    tokens: int = 0
    started: float = field(default_factory=time.time)
    elapsed: float = 0.0
    gen_ms: float = 0.0
    provider: str = "mock"
    model: str = ""
    paused: bool = False

    # ---- mutations -----------------------------------------------------
    def touch(self) -> None:
        self.version += 1

    def add_box(self, text: str, start: int, end: int, weight: float = 0.6) -> AttentionBox:
        box = AttentionBox(text=text, start=start, end=end, weight=weight)
        self.boxes.append(box)
        self.touch()
        return box

    def set_box_weight(self, box_id: str, weight: float) -> None:
        for b in self.boxes:
            if b.id == box_id:
                b.weight = max(0.0, min(1.5, weight))
                self.touch()
                return

    def remove_box(self, box_id: str) -> None:
        self.boxes = [b for b in self.boxes if b.id != box_id]
        self.touch()

    def add_vector(self, label: str, plus: str, minus: str, magnitude: float = 0.0) -> SteerVector:
        v = SteerVector(label=label, plus=plus, minus=minus, magnitude=magnitude)
        self.vectors.append(v)
        self.touch()
        return v

    def set_vector(self, vec_id: str, magnitude: float | None = None) -> None:
        for v in self.vectors:
            if v.id == vec_id:
                if magnitude is not None:
                    v.magnitude = max(-1.0, min(1.0, magnitude))
                self.touch()
                return

    def remove_vector(self, vec_id: str) -> None:
        self.vectors = [v for v in self.vectors if v.id != vec_id]
        self.touch()

    def toggle_pin(self, vec_id: str) -> None:
        for v in self.vectors:
            if v.id == vec_id:
                if v.id in self.pins:
                    self.pins.remove(v.id)
                else:
                    self.pins.append(v.id)
                self.touch()
                return

    @property
    def active(self) -> list[SteerVector]:
        return [v for v in self.vectors if abs(v.magnitude) > 0.01]

    def counters(self) -> dict:
        return {
            "box": len(self.boxes),
            "steer": len(self.active),
            "pin": len(self.pins),
        }

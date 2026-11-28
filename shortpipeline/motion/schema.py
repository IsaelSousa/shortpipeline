"""Schema versionado do JSON de composição dos vídeos animados (motion graphics 2D/2.5D).

A IA escolhe e configura componentes por este schema; a engine (motion-canvas/engine) desenha. Unidades:
posições em metros (`x` para a direita, `height` para cima a partir do chão), tempos em segundos a partir do
início da cena, posições de tela em frações (0–1). Qualquer tempo pode ser trocado por `at_word`, a palavra da
narração da cena em que a ação começa (resolvida pelos tempos da narração antes do render).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError, model_validator

SCHEMA_VERSION = 1

ASSETS = ("air_conditioner", "bracket", "crate", "ball", "flower_pot", "phone", "car", "rock", "coin")
ENVIRONMENTS = ("city", "street", "nature", "room", "studio")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Timed(_M):
    start: float = Field(0, ge=0)
    end: float | None = Field(None, ge=0)
    at_word: str | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.end is not None and self.end < self.start:
            raise ValueError(f"end ({self.end}) antes de start ({self.start})")
        return self


class Look(_M):
    skin: str = "#E8B48F"
    hair: str = "#3B2A20"
    hair_style: Literal["short", "long", "curly", "bun", "bald", "cap"] = "short"
    shirt: str = "#3B82F6"
    pants: str = "#1F2937"
    shoes: str = "#111827"
    build: Literal["slim", "regular", "broad"] = "regular"
    height: float = Field(1.75, ge=0.9, le=2.2)
    accessories: list[Literal["glasses", "cap", "headphones", "backpack"]] = []
    cap: str | None = None
    backpack: str | None = None


class CharacterDecl(_M):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    description: str = ""
    voice: Literal["narrator", "female", "male"] = "narrator"
    look: Look = Look()


class CharAction(Timed):
    type: Literal["walk", "run", "idle", "reaction", "look_up", "use_phone", "point", "talk", "shrug", "expression"]
    to_x: float | None = None
    style: Literal["surprised", "jump_back", "cover"] | None = None
    expression: Literal["neutral", "smile", "surprised", "scared", "worried"] | None = None
    up: bool | None = None
    facing: Literal[-1, 1] | None = None
    hold: bool | None = None


class SceneCharacter(_M):
    ref: str
    x: float = 0
    height: float = 0
    scale: float = Field(1, gt=0, le=4)
    facing: Literal[-1, 1] = 1
    z: int = 0
    expression: Literal["neutral", "smile", "surprised", "scared", "worried"] | None = None
    actions: list[CharAction] = []


class ObjAction(Timed):
    type: Literal["appear", "vanish", "fall", "move", "rotate", "wobble", "shake"]
    dur: float | None = Field(None, gt=0)
    style: Literal["pop", "fade", "drop"] | None = None
    to_x: float | None = None
    to_height: float | None = None
    ground: float | None = None
    bounce: float | None = Field(None, ge=0, le=0.8)
    spin: float | None = None
    breaks: bool | None = None
    turns: float | None = None
    amplitude: float | None = Field(None, ge=0, le=1)
    period: float | None = Field(None, gt=0)
    intensity: float | None = Field(None, ge=0, le=1)
    ease: Literal["linear", "in", "out", "inOut", "back", "elastic"] | None = None
    hold: bool | None = None


class SceneObject(_M):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    asset: Literal[ASSETS]  # type: ignore[valid-type]
    x: float = 0
    height: float = Field(0, ge=-1)
    scale: float = Field(1, gt=0, le=10)
    size: tuple[float, float] | None = None
    color: str | None = None
    pivot: Literal["center", "top"] = "center"
    z: int = 0
    shadow: bool = True
    important: bool = False
    visible: bool = True
    actions: list[ObjAction] = []


class CameraPoint(_M):
    x: float | None = None
    height: float | None = None
    zoom: float | None = Field(None, gt=0.2, le=6)


class CameraMove(Timed):
    type: Literal["cut", "pan", "zoom", "focus", "follow", "shake", "roll"]
    dur: float | None = Field(None, gt=0)
    x: float | None = None
    height: float | None = None
    zoom: float | None = Field(None, gt=0.2, le=6)
    target: str | None = None
    frame_y: float | None = Field(None, ge=0.1, le=0.9)
    offset_x: float | None = None
    offset_y: float | None = None
    intensity: float | None = Field(None, ge=0, le=80)
    angle: float | None = None
    ease: Literal["linear", "in", "out", "inOut", "back", "elastic"] | None = None

    @model_validator(mode="after")
    def _target(self):
        if self.type in ("follow", "focus") and not self.target:
            raise ValueError(f"câmera {self.type} precisa de target")
        return self


class Camera(_M):
    start: CameraPoint = CameraPoint()
    moves: list[CameraMove] = []


class ArrowEnd(_M):
    target: str | None = None
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)


class BarItem(_M):
    label: str = Field(max_length=28)
    value: float
    color: str | None = None
    decimals: int | None = Field(None, ge=0, le=3)


class Overlay(Timed):
    type: Literal["speed", "distance", "timer", "counter", "callout", "highlight", "arrow", "title", "bars"]
    target: str | None = None
    text: str | None = Field(None, max_length=90)
    label: str | None = Field(None, max_length=40)
    unit: str | None = Field(None, max_length=8)
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)
    side: Literal["left", "right"] | None = None
    color: str | None = None
    from_: float | ArrowEnd | None = Field(None, alias="from")
    to: float | ArrowEnd | None = None
    dur: float | None = Field(None, gt=0)
    decimals: int | None = Field(None, ge=0, le=3)
    prefix: str | None = Field(None, max_length=6)
    suffix: str | None = Field(None, max_length=10)
    size: int | None = Field(None, ge=24, le=200)
    stop_at: float | None = None
    since: float | None = None
    radius: float | None = None
    items: list[BarItem] | None = Field(None, max_length=5)

    @model_validator(mode="after")
    def _needs(self):
        need = {"speed": "target", "distance": "target", "highlight": "target", "callout": "text", "title": "text",
                "bars": "items"}.get(self.type)
        if need and not getattr(self, need):
            raise ValueError(f"informativo {self.type} precisa de {need}")
        if self.type == "counter" and (not isinstance(self.to, (int, float))):
            raise ValueError("counter precisa de to numérico (e from opcional)")
        return self


class Effect(_M):
    type: Literal["impact", "dust", "smoke", "speed_lines", "light", "flash", "wind", "rain"]
    at: float | None = Field(None, ge=0)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, ge=0)
    at_word: str | None = None
    target: str | None = None
    x: float | None = None
    height: float | None = None
    size: float | None = Field(None, gt=0, le=5)
    color: str | None = None


class HeroBuilding(_M):
    x: float = 0
    floors: int = Field(10, ge=1, le=60)


class Environment(_M):
    type: Literal[ENVIRONMENTS] = "city"  # type: ignore[valid-type]
    time_of_day: Literal["day", "sunset", "night", "overcast"] = "day"
    hero_building: HeroBuilding | None = None
    lamps: list[float] | None = None
    trees: list[float] | None = None
    foreground: bool = False
    foreground_x: list[float] | None = None
    color: str | None = None
    wall: str | None = None
    floor: str | None = None
    window_x: float | None = None
    seed: str | None = None


class Enter(_M):
    type: Literal["cut", "fade", "whip", "zoom", "slide"] = "cut"
    dur: float = Field(0.35, gt=0, le=1.5)
    dir: Literal[-1, 1] = 1


class TimeWarp(_M):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    rate: float = Field(gt=0.05, le=1)


class Reveal3D(_M):
    start: float = Field(0, ge=0)
    dur: float = Field(0.45, gt=0, le=5)
    at_word: str | None = None


class Shape3D(_M):
    shape: Literal["box", "sphere", "cylinder", "cone", "torus"]
    color: str = Field("#38BDF8", pattern=r"^#[0-9a-fA-F]{6}$")
    position: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0, 0, 0)
    scale: float = Field(1, ge=0.1, le=4)
    rotation: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0, 0, 0)
    spin: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0, 0, 0)
    reveal: Reveal3D | None = None


class Layer3D(_M):
    objects: list[Shape3D] = Field(min_length=1, max_length=8)
    orbit: float = Field(0, ge=-120, le=120)
    view_height: float = Field(7, ge=3, le=16)


class Scene(_M):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    narration: str = ""
    enter: Enter = Enter()
    environment: Environment = Environment()
    characters: list[SceneCharacter] = []
    objects: list[SceneObject] = []
    layer_3d: Layer3D | None = None
    camera: Camera = Camera()
    overlays: list[Overlay] = Field([], max_length=6)
    effects: list[Effect] = Field([], max_length=8)
    time_warp: list[TimeWarp] = []

    @model_validator(mode="after")
    def _refs(self):
        ids = [o.id for o in self.objects] + [c.ref for c in self.characters]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"ids repetidos na cena {self.id}: {sorted(dup)}")
        known = set(ids)
        targets = [m.target for m in self.camera.moves] + [o.target for o in self.overlays] + \
                  [e.target for e in self.effects] + \
                  [end.target for o in self.overlays for end in (o.from_, o.to) if isinstance(end, ArrowEnd)]
        missing = sorted({t for t in targets if t and t not in known})
        if missing:
            raise ValueError(f"cena {self.id} aponta para alvos que não existem nela: {missing}")
        return self


class Fact(_M):
    claim: str
    kind: Literal["verified", "calculation", "estimate", "illustrative"]
    formula: str | None = None
    assumptions: str | None = None
    value: float | None = None
    source: str | None = None


class Word(_M):
    text: str
    start: float
    end: float


class Captions(_M):
    enabled: bool = True
    max_words: int = Field(3, ge=1, le=6)
    emphasis: list[str] = []
    words: list[Word] = []
    size: int | None = Field(None, ge=48, le=160)
    y: float | None = Field(None, ge=0.15, le=0.8)
    fixed_position: bool = False
    uppercase: bool = True
    highlight: str | None = None


class Theme(_M):
    accent: str = "#F97316"
    accent2: str = "#FDE047"
    locale: str = "pt-BR"


class Video(_M):
    schema_version: Literal[1] = SCHEMA_VERSION
    title: str = ""
    width: int = 1080
    height: int = 1920
    fps: int = Field(30, ge=12, le=60)
    upm: float = Field(200, ge=40, le=800)
    theme: Theme = Theme()
    facts: list[Fact] = []
    characters: list[CharacterDecl] = []
    captions: Captions = Captions()
    cover_time: float | None = None
    fonts: dict[str, str] | None = None
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _global(self):
        decl = {c.id for c in self.characters}
        for sc in self.scenes:
            unknown = sorted({c.ref for c in sc.characters} - decl)
            if unknown:
                raise ValueError(f"cena {sc.id} usa personagens não declarados em characters: {unknown}")
        ids = [s.id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("ids de cena repetidos")
        for a, b in zip(self.scenes, self.scenes[1:]):
            if abs(a.end - b.start) > 0.02:
                raise ValueError(f"cenas {a.id} e {b.id} não são contínuas ({a.end} → {b.start})")
        return self


_POSITIVE = {"dur", "rate", "period", "size", "zoom", "radius", "scale"}
_LIMITS = {"overlays": 6, "effects": 8}


def clean(data):
    """Tira o ruído comum da IA antes de validar: campos nulos, zeros em campos que precisam ser positivos
    (dur, rate, zoom…), `end` antes de `start` e listas acima do limite. Não inventa nada."""
    if isinstance(data, list):
        return [clean(x) for x in data]
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        if v is None:
            continue
        if k in _POSITIVE and isinstance(v, (int, float)) and not isinstance(v, bool) and v <= 0:
            continue
        v = clean(v)
        if k in _LIMITS and isinstance(v, list):
            v = v[:_LIMITS[k]]
        if k == "time_warp" and isinstance(v, list):
            v = [w for w in v if isinstance(w, dict) and "rate" in w and w.get("end", 0) > w.get("start", 0)]
        out[k] = v
    if isinstance(out.get("start"), (int, float)) and isinstance(out.get("end"), (int, float)) and out["end"] < out["start"]:
        out.pop("end")
    return out


def validate(data: dict) -> Video:
    return Video.model_validate(clean(data))


def errors_text(exc: ValidationError, limit: int = 12) -> str:
    """Erros de validação curtos, com o caminho do campo, para devolver à IA."""
    lines = []
    for err in exc.errors()[:limit]:
        path = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {path or '(raiz)'}: {err['msg']}")
    more = len(exc.errors()) - limit
    return "\n".join(lines) + (f"\n- (+{more} erros)" if more > 0 else "")


def field_guide() -> str:
    """Campos permitidos de cada parte do JSON, uma linha por modelo (gerado do schema: nunca fica desatualizado).
    Vai no prompt do storyboard para a IA não adivinhar nomes de campo."""
    models = {"character (declaração)": CharacterDecl, "look": Look, "scene": Scene, "environment": Environment,
              "enter": Enter, "scene.characters[]": SceneCharacter, "character action": CharAction,
              "scene.objects[]": SceneObject, "object action": ObjAction, "camera.start": CameraPoint,
              "camera move": CameraMove, "overlay": Overlay, "bars item": BarItem, "effect": Effect,
              "time_warp": TimeWarp, "scene.layer_3d": Layer3D, "layer_3d.objects[]": Shape3D,
              "layer_3d.objects[].reveal": Reveal3D}
    lines = []
    for name, model in models.items():
        fields = [(f.alias or k) for k, f in model.model_fields.items()]
        lines.append(f"- {name}: {', '.join(fields)}")
    return "\n".join(lines)


def json_schema() -> dict:
    return Video.model_json_schema(by_alias=True)

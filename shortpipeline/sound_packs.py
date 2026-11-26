"""Biblioteca de sons CC0: baixa, organiza e nivela pacotes gratuitos para `data/sound-packs/`.

    shortpipeline-sounds              # baixa tudo e monta os pacotes
    shortpipeline-sounds --list       # mostra as fontes e licenças, sem baixar

Só entram fontes CC0 (domínio público: uso comercial livre, sem crédito obrigatório). Cada som ganha um nome que a
biblioteca do pipeline entende (`glass-break-3.ogg`, `ambience-traffic-1.ogg`), volume nivelado e entra num pacote
por tema com `pack.json` (estilos e palavras-chave em português e inglês) e `CREDITS.md` (origem de cada arquivo).
Os arquivos ficam fora do git, como o resto de `data/`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import config

UA = "Mozilla/5.0 (X11; Linux x86_64) ShortPipeline sound library"
AUDIO = {".ogg", ".wav", ".mp3", ".flac"}
OGA = "https://opengameart.org/sites/default/files/"

KENNEY = [("impact-sounds", "Impact Sounds"), ("interface-sounds", "Interface Sounds"), ("ui-audio", "UI Audio"),
          ("rpg-audio", "RPG Audio"), ("sci-fi-sounds", "Sci-fi Sounds"), ("digital-audio", "Digital Audio"),
          ("casino-audio", "Casino Audio"), ("music-jingles", "Music Jingles")]

SOURCES = [
    *({"id": f"kenney-{slug}", "kenney": slug, "title": title, "author": "Kenney",
       "page": f"https://kenney.nl/assets/{slug}"} for slug, title in KENNEY),
    *({"id": f"oga-{slug}", "files": [OGA + f for f in files], "title": title, "author": author,
       "page": f"https://opengameart.org/content/{slug}"} for slug, title, author, files in [
        ("100-cc0-sfx", "100 CC0 SFX", "rubberduck", ["100-CC0-SFX_0.zip"]),
        ("100-cc0-sfx-2", "100 CC0 SFX #2", "rubberduck", ["sfx_100_v2.zip"]),
        ("75-cc0-breaking-falling-hit-sfx", "75 CC0 breaking/falling/hit sfx", "rubberduck",
         ["sfx_breaking_and_falling.zip"]),
        ("80-cc0-creature-sfx", "80 CC0 creature SFX", "rubberduck", ["80-CC0-creature-SFX_0.zip"]),
        ("50-cc0-sci-fi-sfx", "50 CC0 Sci-Fi SFX", "rubberduck", ["sci-fi-sfx.zip"]),
        ("40-cc0-water-splash-slime-sfx", "40 CC0 water/splash/slime SFX", "rubberduck",
         ["water-splash-slime-sfx.zip"]),
        ("25-cc0-bang-firework-sfx", "25 CC0 bang/firework SFX", "rubberduck", ["25-CC0-bang-sfx.zip"]),
        ("80-cc0-rpg-sfx", "80 CC0 RPG SFX", "rubberduck", ["80-CC0-RPG-SFX_0.zip"]),
        ("100-cc0-metal-and-wood-sfx", "100 CC0 metal and wood SFX", "rubberduck", ["100-CC0-wood-metal-SFX.zip"]),
        ("30-cc0-sfx-loops", "30 CC0 SFX loops", "rubberduck", ["sfx_loops.zip"]),
        ("dark-ambiences", "Dark Ambiences", "ogrebane", ["dark_ambiences.zip"]),
        ("4-atmospheric-ghostly-loops", "4 Atmospheric Ghostly Loops", "qubodup", ["at.mp3"]),
        ("crickets-ambient-noise-loopable", "Crickets Ambient Noise Loopable", "wolfgang", ["crickets_1.mp3"]),
        ("high-traffic-road-sounds", "High Traffic Road Sounds", "ignasd",
         ["gatve%20Varniu_2.ogg", "gatve%20Varniu_3.ogg"]),
        ("crowd-shoutingspeaking-ambience", "Crowd shouting/speaking ambience", "starninjas", ["crowd_shouting.ogg"]),
        ("applause-in-a-large-hall-or-church", "Applause in a large hall", "expl0it3r",
         ["applause-clapping-church-crowd-immersive.wav"]),
        ("fireplace-sound-loop", "Fireplace sound loop", "pagdev", ["fire.wav"]),
        ("boiling-water-loops", "Boiling water loops", "tinyworlds",
         ["cooking_with_cover_01.ogg", "cooking_without_cover_01.ogg"]),
        ("ambient-bird-sounds", "Ambient Bird Sounds", "isaiah658", ["birds-isaiah658.ogg"]),
        ("dripping-water-loop", "Dripping water loop", "qubodup", ["atmo.mp3"]),
        ("glass-break", "Glass Break", "tinyworlds", ["glass_breaking.wav"]),
        ("cardoorsfx", "Car door SFX", "looneybits", ["door_closing.wav", "door_opening.wav"]),
        ("car-engine-start-01", "Car engine start", "looneybits",
         ["generic_car_startengine.wav", "generic_car_startengine_1.wav"]),
    ]),
]

# regras por fonte vêm antes das gerais (o mesmo nome significa coisas diferentes em pacotes diferentes)
SOURCE_RULES = {
    "kenney-music-jingles": [(r".", "sting")],
    "oga-30-cc0-sfx-loops": [(r"machine|pump", "ambience-machine"), (r"water_flowing", "ambience-water"),
                             (r"water_boiling", "ambience-boiling"), (r"rain", "ambience-rain"),
                             (r"alarm", "ambience-alarm"), (r"weird|ambient", "ambience-eerie"),
                             (r"noise", "ambience-noise"), (r".", None)],
    "oga-dark-ambiences": [(r"ambience", "ambience-dark")],
    "oga-4-atmospheric-ghostly-loops": [(r".", "ambience-ghostly")],
    "oga-crickets-ambient-noise-loopable": [(r".", "ambience-crickets")],
    "oga-high-traffic-road-sounds": [(r".", "ambience-traffic")],
    "oga-crowd-shoutingspeaking-ambience": [(r".", "ambience-crowd")],
    "oga-applause-in-a-large-hall-or-church": [(r".", "applause")],
    "oga-fireplace-sound-loop": [(r".", "ambience-fire")],
    "oga-boiling-water-loops": [(r".", "ambience-boiling")],
    "oga-ambient-bird-sounds": [(r".", "ambience-birds")],
    "oga-dripping-water-loop": [(r".", "ambience-drip")],
    "oga-car-engine-start-01": [(r".", "car-engine")],
    "oga-50-cc0-sci-fi-sfx": [(r"loop_ambient", "ambience-scifi"), (r"loop_machine", "ambience-machine")],
    "oga-100-cc0-sfx-2": [(r"loop_ambient", "ambience-eerie"), (r"loop_machine", "ambience-machine"),
                          (r"loop_water", "ambience-water")],
    "oga-40-cc0-water-splash-slime-sfx": [(r"loop_rain", "ambience-rain"), (r"loop_bubbles", "ambience-bubbles"),
                                          (r"loop_water", "ambience-water")],
}

RULES = [
    (r"item_", "item"),
    (r"glass.*(break|shatter)", "glass-break"), (r"wood.*(break|crack)", "wood-break"),
    (r"(rock|stone).*break|bfh1_breaking", "break"), (r"rock_falling|(^|_)stones?(_|$)", "rock-fall"),
    (r"glass_falling|glass_hit|impactglass|(^|_)glass", "glass-tap"),
    (r"metal_falling", "metal-fall"), (r"wood_falling", "wood-fall"), (r"(^|_)falling", "fall"),
    (r"impactpunch|punch", "punch"), (r"impactsoft|thud", "thud"), (r"footstep", "footsteps"),
    (r"door.?open", "door-open"), (r"door.?clos", "door-close"), (r"(^|_)door", "door"),
    (r"slam", "slam"),
    (r"impactwood|impactplank|wood_hit|wood_hammer|(^|_)wood", "impact-wood"),
    (r"impactmetal|impactplate|impacttin|metal_hit|metal_sheet|(^|_)metal", "impact-metal"),
    (r"impactbell|(^|_)bell|bong", "bell"), (r"impactmining", "pickaxe"),
    (r"impactgeneric|(^|_)hit", "hit"), (r"cannon|bang|(^|_)shot", "bang"), (r"(^|_)fw", "firework"),
    (r"explosion", "explosion"), (r"creak|squeak", "creak"), (r"(^|_)keys?(_|$)", "keys"), (r"lock", "lock"),
    (r"paper|book", "paper"), (r"cloth|belt|leather", "cloth"), (r"dishes|metalpot|cookware", "dishes"),
    (r"knife", "knife"), (r"card", "cards"), (r"chip", "casino-chips"), (r"dice|die-", "dice"),
    (r"coin", "cash"), (r"tools|hammer|(^|_)saw", "tools"), (r"spring", "spring"),
    (r"splash", "splash"), (r"bubble", "bubbles"), (r"slime|spit", "slime"), (r"scream", "scream"),
    (r"roar|growl|troll|monster", "monster"), (r"alien", "alien"), (r"hurt|grunt|cough", "grunt"),
    (r"cute", "cute"), (r"(^|_)bug", "bug"), (r"(^|_)eat", "eat"), (r"spell_fire", "fire"),
    (r"spell|magic", "magic"), (r"powerup|phaserup", "power-up"), (r"phaserdown|powerdown", "power-down"),
    (r"laser|phaser|shoot", "laser"), (r"zap|tone|pepsound|spacetrash", "zap"),
    (r"teleport|forcefield|phasejump", "teleport"),
    (r"thruster|spaceengine|enginecircular|rocket|(^|_)engine", "engine"),
    (r"computernoise|terminal|beep", "beep"), (r"alarm", "alarm"),
    (r"click|mouseclick|mouserelease|tick", "click"), (r"switch|toggle", "switch"),
    (r"rollover|select|confirmation|pluck", "select"), (r"error|back_", "error"), (r"question", "question"),
    (r"drop", "drop"), (r"scroll|scratch", "scroll"), (r"glitch", "glitch"),
    (r"maximize|minimize|(^|_)open|(^|_)close", "swish"), (r"(^|_)pop", "pop"),
]
SKIP = re.compile(r"preview|(^|/)\._|license|readme", re.I)

ALL = None
PACKS = {
    "cc0-impactos": (ALL, ["glass-break", "wood-break", "break", "rock-fall", "glass-tap", "metal-fall", "wood-fall",
                           "fall", "punch", "thud", "impact-wood", "impact-metal", "pickaxe", "hit", "slam", "bang",
                           "firework", "explosion"]),
    "cc0-cotidiano": (ALL, ["footsteps", "door-open", "door-close", "door", "creak", "keys", "lock", "paper", "cloth",
                            "dishes", "knife", "cards", "casino-chips", "dice", "cash", "car-engine", "tools",
                            "spring", "bell", "splash", "bubbles", "applause", "item"]),
    "cc0-interface": (["neutro", "tech"], ["click", "switch", "select", "error", "question", "drop", "scroll",
                                           "glitch", "swish", "pop", "beep"]),
    "cc0-scifi": (["tech", "neutro"], ["power-up", "power-down", "laser", "zap", "teleport", "engine", "alarm"]),
    "cc0-criaturas": (["terror", "neutro"], ["scream", "monster", "alien", "grunt", "cute", "bug", "slime", "eat",
                                             "magic", "fire"]),
    "cc0-vinhetas": (ALL, ["sting"]),
    "cc0-ambientes-sombrios": (["terror"], ["ambience-dark", "ambience-ghostly", "ambience-eerie"]),
    "cc0-ambientes": (ALL, ["ambience-traffic", "ambience-crowd", "ambience-crickets", "ambience-birds",
                            "ambience-fire", "ambience-boiling", "ambience-water", "ambience-rain", "ambience-bubbles",
                            "ambience-drip", "ambience-machine", "ambience-alarm", "ambience-scifi",
                            "ambience-noise"]),
}

TAGS = {
    "glass-break": ["vidro", "quebrando", "shatter", "shattering", "estilhaço"],
    "wood-break": ["madeira", "quebrando", "crack", "snap"], "break": ["quebra", "quebrando", "breaking", "smash"],
    "rock-fall": ["pedra", "pedras", "rocks", "stones", "desmoronamento", "avalanche"],
    "glass-tap": ["vidro", "taça", "copo"], "metal-fall": ["metal", "caindo", "queda"],
    "wood-fall": ["madeira", "caindo", "queda"], "fall": ["caindo", "queda", "falling", "tombo"],
    "punch": ["soco", "murro", "golpe"], "thud": ["baque", "pancada", "thump"],
    "impact-wood": ["madeira", "wooden", "batida"], "impact-metal": ["metal", "metálico", "clang", "lata"],
    "pickaxe": ["picareta", "mineração", "mining"], "hit": ["batida", "golpe", "pancada"],
    "slam": ["batendo", "batida", "bate"], "bang": ["tiro", "disparo", "gunshot", "canhão", "estouro"],
    "firework": ["fogos", "rojão", "fireworks"], "explosion": ["explosão", "explode", "boom", "blast"],
    "footsteps": ["passos", "andando", "caminhando", "steps", "walking", "footstep"],
    "door-open": ["porta", "abrindo", "abre"], "door-close": ["porta", "fechando", "fecha"], "door": ["porta"],
    "creak": ["rangido", "rangendo", "range"], "keys": ["chaves", "chaveiro"],
    "lock": ["fechadura", "tranca", "cadeado"], "paper": ["papel", "folha", "livro", "página", "book"],
    "cloth": ["roupa", "tecido", "pano"], "dishes": ["pratos", "louça", "panela", "cozinha", "kitchen"],
    "knife": ["faca", "cortando", "slice"], "cards": ["cartas", "baralho", "card"],
    "casino-chips": ["fichas", "cassino", "aposta"], "dice": ["dado", "dados"],
    "cash": ["moedas", "dinheiro", "coins", "troco"], "car-engine": ["motor", "carro", "ligando", "partida"],
    "tools": ["ferramenta", "martelo", "serra", "obra"], "spring": ["mola", "boing"], "bell": ["sino", "sineta"],
    "splash": ["água", "respingo", "mergulho", "espirro"], "bubbles": ["bolhas", "borbulhando"],
    "applause": ["aplausos", "palmas", "plateia"], "item": ["pegar", "coletar", "pickup"],
    "click": ["clique", "toque", "tap"], "switch": ["interruptor", "liga", "desliga"],
    "select": ["confirmação", "seleção", "escolha"], "error": ["erro", "errado", "negado"],
    "question": ["pergunta", "dúvida"], "drop": ["soltar", "solta"], "scroll": ["rolagem", "deslizar"],
    "glitch": ["falha", "pane"], "swish": ["swoosh", "vupt", "transição"], "pop": ["estouro", "bolha"],
    "beep": ["bip", "apito", "computador"], "power-up": ["energia", "carregando", "upgrade"],
    "power-down": ["desligando", "descarregando"], "laser": ["raio", "disparo"],
    "zap": ["choque", "elétrico", "eletricidade"], "teleport": ["teletransporte", "portal"],
    "engine": ["nave", "foguete", "propulsor", "rocket"], "alarm": ["alarme", "sirene", "alerta"],
    "scream": ["grito", "gritando"], "monster": ["monstro", "rugido", "rosnado", "growl", "roar"],
    "alien": ["alienígena", "extraterrestre"], "grunt": ["gemido", "dor", "tosse"], "cute": ["fofo", "bichinho"],
    "bug": ["inseto", "barata", "zumbido"], "slime": ["gosma", "nojento"], "eat": ["comendo", "mastigando"],
    "magic": ["mágica", "feitiço", "encanto"], "fire": ["fogo", "chamas"],
    "sting": ["vinheta", "jingle", "revelação", "final"],
    "ambience-traffic": ["trânsito", "rua", "carros", "cidade", "city", "street"],
    "ambience-crowd": ["multidão", "pessoas", "gente", "público"],
    "ambience-crickets": ["grilos", "noite", "night", "campo"],
    "ambience-birds": ["pássaros", "manhã", "parque", "natureza", "nature", "forest"],
    "ambience-fire": ["fogueira", "lareira", "fogo", "fireplace"],
    "ambience-boiling": ["fervendo", "panela", "cozinha", "kitchen"],
    "ambience-water": ["água", "rio", "river", "córrego"], "ambience-rain": ["chuva"],
    "ambience-bubbles": ["bolhas", "aquário"], "ambience-drip": ["gotejando", "porão", "goteira", "cave", "caverna"],
    "ambience-machine": ["máquina", "fábrica", "industrial", "factory"],
    "ambience-alarm": ["alarme", "emergência"], "ambience-scifi": ["nave", "espaço", "laboratório", "space"],
    "ambience-noise": ["ruído", "estática"], "ambience-dark": ["sombrio", "tenso", "terror", "dark"],
    "ambience-ghostly": ["fantasma", "assombrado", "sobrenatural"],
    "ambience-eerie": ["estranho", "misterioso", "eerie"],
}


def category(source_id: str, rel: str) -> str | None:
    """Categoria do som pelo nome original (None = descartado)."""
    stem = re.sub(r"[ -]", "_", Path(rel).stem.lower())
    for pattern, cat in SOURCE_RULES.get(source_id, []) + RULES:
        if re.search(pattern, stem):
            return cat
    return None


def _kenney_urls(client: httpx.Client, slug: str) -> list[str]:
    page = f"https://kenney.nl/assets/{slug}"
    client.get(page)  # o link assinado exige o cookie da página
    res = client.get(f"https://kenney.nl/download-link/{f'assets/{slug}'.encode().hex()}",
                     headers={"Referer": page, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"})
    url = res.json().get("url") if res.status_code == 200 else None
    if not url:
        raise RuntimeError(f"Kenney não devolveu o link de {slug} ({res.status_code}). Baixe em {page}")
    return [url]


def download(src: dict, cache: Path) -> list[Path]:
    folder = cache / src["id"]
    done = folder / ".ok"
    if done.is_file():
        return [p for p in folder.iterdir() if p.is_file() and p.name != ".ok"]
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=120) as client:
        urls = _kenney_urls(client, src["kenney"]) if src.get("kenney") else src["files"]
        out = []
        for i, url in enumerate(urls):
            name = f"{src['id']}.zip" if src.get("kenney") else Path(url.split("?")[0]).name.replace("%20", "_")
            dest = folder / name
            with client.stream("GET", url, headers={"Referer": src["page"]}) as res:
                res.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in res.iter_bytes():
                        fh.write(chunk)
            out.append(dest)
    done.write_text("ok")
    return out


def audio_files(archives: list[Path], work: Path) -> list[tuple[str, Path]]:
    """(nome original, arquivo) de cada áudio, extraindo os zips com segurança (sem sair da pasta)."""
    found = []
    for a in archives:
        if a.suffix.lower() == ".zip":
            target = work / a.stem
            with zipfile.ZipFile(a) as z:
                for info in z.infolist():
                    rel = info.filename
                    if info.is_dir() or SKIP.search(rel) or Path(rel).suffix.lower() not in AUDIO:
                        continue
                    path = (target / rel).resolve()
                    if target.resolve() not in path.parents:
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append((rel, path))
        elif a.suffix.lower() in AUDIO and not SKIP.search(a.name):
            found.append((a.name, a))
    return sorted(found)


def convert(src: Path, dest: Path) -> bool:
    """OGG 44,1 kHz com o pico em -3 dB (o ambiente ainda é nivelado na mixagem)."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "volumedetect", "-f", "null",
                            "-"], capture_output=True, text=True)
    m = re.search(r"max_volume: (-?[\d.]+) dB", probe.stderr)
    if not m:
        return False
    gain = max(-20.0, min(20.0, -3.0 - float(m.group(1))))
    res = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(src), "-map", "0:a:0",
                          "-af", f"volume={gain:.2f}dB,aformat=channel_layouts=mono|stereo", "-ar", "44100",
                          "-c:a", "libvorbis", "-q:a", "5", str(dest)], capture_output=True, text=True)
    return res.returncode == 0 and dest.is_file()


def build(dest: Path, log=print, keep_downloads: bool = False) -> dict[str, int]:
    cache = dest / ".downloads"
    work = cache / "_extract"
    pack_of = {cat: pack for pack, (_, cats) in PACKS.items() for cat in cats}
    items: list[tuple[str, str, dict, str, Path]] = []  # pacote, categoria, fonte, nome original, arquivo
    for src in SOURCES:
        try:
            archives = download(src, cache)
        except Exception as e:  # uma fonte fora do ar não derruba as outras
            log(f"! {src['title']}: {e}")
            continue
        n = 0
        for rel, path in audio_files(archives, work / src["id"]):
            cat = category(src["id"], rel)
            if cat and cat in pack_of:
                items.append((pack_of[cat], cat, src, rel, path))
                n += 1
        log(f"  {src['title']} ({src['author']}): {n} sons")
    counters: dict[str, int] = {}
    jobs = []
    credits: dict[str, list[str]] = {}
    for pack, cat, src, rel, path in items:
        counters[cat] = counters.get(cat, 0) + 1
        name = f"{cat}-{counters[cat]}.ogg"
        jobs.append((path, dest / pack / name))
        credits.setdefault(pack, []).append(f"| `{name}` | `{rel}` | {src['author']} | [{src['title']}]({src['page']}) |")
    for pack in {p for p, *_ in items}:
        out = dest / pack
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = list(pool.map(lambda j: convert(*j), jobs))
    totals: dict[str, int] = {}
    for (_, target), good in zip(jobs, ok):
        if good:
            totals[target.parent.name] = totals.get(target.parent.name, 0) + 1
    license_file = config.ASSETS_DIR / "sound-packs" / "LICENSE-CC0.txt"
    for pack, (styles, cats) in PACKS.items():
        out = dest / pack
        if not out.is_dir():
            continue
        meta = {"license": "CC0 1.0 (domínio público)", "source": "shortpipeline-sounds",
                "tags": {c: TAGS[c] for c in cats if c in TAGS and any(out.glob(f"{c}-*.ogg"))}}
        if styles:
            meta["styles"] = styles
        (out / "pack.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "CREDITS.md").write_text(
            f"# {pack}\n\nTodos os sons são CC0 1.0 (domínio público). Créditos por cortesia.\n\n"
            "| Arquivo | Original | Autor | Fonte |\n|---|---|---|---|\n" + "\n".join(credits.get(pack, [])) + "\n",
            encoding="utf-8")
        if license_file.is_file():
            shutil.copy(license_file, out / "LICENSE-CC0.txt")
    shutil.rmtree(work if keep_downloads else cache, ignore_errors=True)
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shortpipeline-sounds", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", type=Path, default=config.DATA_DIR / "sound-packs",
                    help="pasta dos pacotes (padrão: data/sound-packs)")
    ap.add_argument("--list", action="store_true", help="só lista as fontes")
    ap.add_argument("--keep-downloads", action="store_true", help="guarda os arquivos baixados em .downloads")
    args = ap.parse_args(argv)
    if args.list:
        for s in SOURCES:
            print(f"{s['title']:<38} {s['author']:<12} CC0  {s['page']}")
        return 0
    if not shutil.which("ffmpeg"):
        print("Precisa do ffmpeg instalado.", file=sys.stderr)
        return 1
    print(f"Baixando {len(SOURCES)} fontes CC0 para {args.dest}…")
    totals = build(args.dest, keep_downloads=args.keep_downloads)
    for pack, n in sorted(totals.items()):
        print(f"{pack:<26} {n:>4} sons")
    print(f"Total: {sum(totals.values())} sons. Não precisa reiniciar: a biblioteca lê a pasta a cada vídeo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

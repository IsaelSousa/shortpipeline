# ShortPipeline sound packs

These audio files are distributed under [CC0 1.0 Universal](LICENSE-CC0.txt).

| Included file | Original | Creator and source |
| --- | --- | --- |
| `kenney-interface/blip.ogg` | `confirmation_001.ogg` | Kenney, [Interface Sounds](https://opengameart.org/content/interface-sounds) |
| `kenney-interface/impact.ogg` | `drop_001.ogg` | Kenney, [Interface Sounds](https://opengameart.org/content/interface-sounds) |
| `kenney-interface/sfx.ogg` | `click_001.ogg` | Kenney, [Interface Sounds](https://opengameart.org/content/interface-sounds) |
| `kenney-interface/whoosh.ogg` | `minimize_001.ogg` | Kenney, [Interface Sounds](https://opengameart.org/content/interface-sounds) |
| `opengameart-ambience/ambience-rain.wav` | `rain_on_window_loop.wav` | alxl, [Rain on Window Loop](https://opengameart.org/content/rain-on-window-loop) |
| `opengameart-ambience/ambience-cave.ogg` | `dungeon_ambient_1.ogg` | JaggedStone, [Loopable Dungeon Ambience](https://opengameart.org/content/loopable-dungeon-ambience) |

The [original Kenney license notice](kenney-interface/LICENSE.txt) is included.

## Adding another pack

For sounds you can't redistribute, use `data/sound-packs/` instead: it's outside git and takes priority over these packs. See "Your own sounds and music" in the main README.


Create a subfolder in `assets/sound-packs/` and include the license and source attribution for its audio files. Supported extensions are `.mp3`, `.ogg` and `.wav`. Use these base names to map files to existing presets:

- `whoosh`, `impact`, `riser`, `blip` or `sfx` for timeline effects.
- `ambience-rain` or `ambience-cave` for fallback loops matched to scene descriptions.

If more than one pack provides the same preset, the first matching folder in alphabetical order wins. Restarting the app is unnecessary when adding files to this directory.

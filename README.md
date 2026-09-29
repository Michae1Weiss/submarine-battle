# Submarine Battle
Low-poly U-boat shooting PoC made with [Bevy](https://bevy.org) 0.19. Sink the golden boats.

**Play in the browser: https://michae1weiss.github.io/submarine-battle/**

## Controls
| Key | Action |
|---|---|
| `W` / `S` | engine: reverse, stop, slow, mid, full |
| `A` / `D` | rudder (stays where you leave it), `C` centres it |
| Arrows | turn and elevate the gun (red disc = where the shell lands) |
| `Space` | shell (3 hits kill, surfaced only) |
| `T` | torpedo (1 hit kills, also when dived) |
| `F` | dive to periscope depth / surface |
| `R` | restart |

Click the game window once so it gets keyboard focus.

## Run
```bash
cargo run
```

## Build for web
**Pre-requirement**: [bevy_cli](https://github.com/TheBevyFlock/bevy_cli) and `rustup target add wasm32-unknown-unknown`.
```bash
bevy build --yes --release web --bundle
# Test locally
python3 -m http.server 8000 --directory target/bevy_web/web-release/submarine-battle
```

## Deploy to GitHub Pages
The site is served from the `gh-pages` branch (root, with a `.nojekyll` file).
```bash
# once: check out gh-pages next to this repo
git worktree add ../submarine-battle-gh-pages gh-pages
# every deploy
SRC=target/bevy_web/web-release/submarine-battle
DEST=../submarine-battle-gh-pages
rm -rf "$DEST"/build "$DEST"/assets && cp -r "$SRC"/. "$DEST"/
( cd "$DEST" && git add -A && git commit -m "ops: deploy web build" && git push )
```

## Models
Blender scripts live in `art/blender` (needs [Blender](https://www.blender.org)); they write to `assets/models`.
```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --python art/blender/uboat.py
/Applications/Blender.app/Contents/MacOS/Blender --background --python art/blender/weapons.py
```

# 配色方案：像素风

- 类 PICO-8 的受限调色板（16–32 色），天空用抖动渐变
- 3–4 层视差（天空、远山、中景森林 / 城市、近景地砖），按整像素移动
- 调色板轮换做昼夜（白天→黄昏）
- 站点主题色：#4FB0FF

## 原片创意中的配色描述（英文原文）

「像素冒险 PIXEL QUEST」A retro side-scroller title/attract sequence.
- Internal 320×180, ×6 nearest-neighbour; limited palette (PICO-8-like 16–32 colours) with dithered sky gradient; 3–4 parallax layers (sky, far mountains, mid forest/city, near ground tiles) moving by whole pixels.
- Hero sprite (hand-authored 16×16–24×24, 6–8 frame run cycle at ~10–12 fps) runs, jumps, collects coins (sparkle), bops a slime; the palette shifts day → sunset; a treasure chest opens with a light burst.
- Dialogue box with pixel CJK font typing 「欢迎来到像素世界！」; chunky pixel logo "PIXEL QUEST" drops in with shine sweep; optional CRT pass (scanlines, slight barrel, phosphor glow) that doesn't blur pixels into mush.
- Strictly: nearest-neighbour, integer pixel positions, stepped timing (no smooth easing on sprites).
Sound: chiptune (pulse lead, triangle bass, noise drums) + jump/coin/chest SFX.

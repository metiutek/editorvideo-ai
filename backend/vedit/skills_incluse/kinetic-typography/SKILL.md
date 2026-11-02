---
name: kinetic-typography
description: Animated text - headline reveals, split by line, word or letter, lyric and caption-style pieces, variable-font weight animation. Use when the user wants an animated title, a kinetic type piece, text that reveals or staggers, or a punchy typographic moment in a vedit video.
source: Adapted from the iart.ai kinetic-typography skill (MIT). See NOTICE.md.
---

# Kinetic typography

Motion cannot rescue bad type. Lock the static typography first, then animate.

## 1. Static typography

- Line-height 1.1-1.2 for display headlines, 1.4-1.6 for body.
- Tighten display tracking by -1% to -3% (`letter-spacing: -0.02em`).
- Fix alignment and weight before any motion.

## 2. Pick the split

| Split | Feel | Use |
|---|---|---|
| Line | calmest, most premium | multi-line statements, elegant headlines |
| Word | energetic | taglines, lyric hits |
| Character | most kinetic, playful | short strings only; busy on long copy |

## 3. Pick the reveal

- **Mask / clip reveal** (most robust): each line in `overflow: hidden`, the child goes `translateY(110%)` to 0. GPU-cheap, no blur artefacts, the standard headline reveal.
- **Blur-in**: `blur(12px)` to 0 with opacity 0 to 1. Soft, "focus-pull". Keep the radius modest and the duration short.
- **Clip-path wipe**: `clip-path: inset(0 100% 0 0)` to `inset(0 0 0 0)` reveals without moving glyphs.
- **Character stagger**: split to characters, fade and translate each with a small offset.

## 4. Timing

- Ease: `cubic-bezier(0.16, 1, 0.3, 1)`.
- Fragment 400-600 ms. Stagger: lines 60-100 ms, words 40-70 ms, characters 20-40 ms.
- Cap the whole reveal near 800 ms; for long strings reduce the offset or move up a granularity (character to word to line).

## In vedit

First check the ready blocks: `kinetic_words` (words pop in, `*star*` highlights one), `typewriter`, `sticker_text`, `title`, `quote`. For anything else write an `add_html` clip, on a track above the footage, with a transparent background.

Mask reveal, copy-paste (the clip clock drives CSS animations, so delays are plain seconds):

```html
<h1 class="reveal"><span class="line"><span>Designed</span></span>
<span class="line"><span style="animation-delay:.08s">for motion</span></span></h1>
<style>
.reveal{margin:0;font:900 7vw/1.1 system-ui;letter-spacing:-.02em;color:#fff;text-align:center}
.reveal .line{display:block;overflow:hidden}
.reveal .line>span{display:inline-block;transform:translateY(110%);
 animation:rise .6s cubic-bezier(.16,1,.3,1) forwards}
@keyframes rise{to{transform:none}}
</style>
```

Variable fonts: animate `font-variation-settings: "wght" 200` to `"wght" 800`, not `font-weight`, to hit any value and interpolate smoothly. Check the loaded font really is variable and what the axis range is.

## Rules for video

- Use fonts that exist on the machine, or put the font file in the folder you pass as `base` and load it with `@font-face`. A font fetched from the network may not be there at render time, and the render silently uses another face.
- Size widths in `vw`/`vh` so the same graphic works in 16:9 and 9:16.
- Hold a read line long enough (0.5 s + 0.3 s per word), and do not let it move after it lands (see `motion-craft`).
- Check the longest string with `preview_frame` at the end of the reveal: nothing cut off by the mask.

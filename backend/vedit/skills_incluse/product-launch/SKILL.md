---
name: product-launch
description: Premium 15-60 second launch films, trailers, hype reels and product promos cut to music - the hook/tease/reveal/montage/end-card arc and how to keep it cinematic. Use when the user wants a product drop, a feature announcement, a promo, a sizzle or beat-synced reveal in vedit.
source: Adapted from the iart.ai launch-video skill (MIT) and the principles of video-shotcraft (Vincentwei1021/video-shotcraft, Apache-2.0). See NOTICE.md.
---

# Product launch films

## The arc

| Beat | Job | Share of 30 s |
|---|---|---|
| Hook | a striking frame or motion that stops the scroll | 0-3 s |
| Tease | hint the product, build curiosity, on the beat | 3-9 s |
| Reveal | product or logo hits on the music drop | 9-13 s |
| Feature montage | fast, kinetic, one benefit per shot | 13-25 s |
| End card | logo, tagline, CTA, a clean hold | 25-30 s |

Scale the proportions for 15 s (tighter) or 60 s (a longer montage, never a longer hook).

## Two rules that decide the result

1. **Sound leads picture.** Lock the track first, mark the beats and the drop, then cut to those marks. Never score a finished cut: the reveal lands *on* the drop, not near it. vedit: `music_beats(every=1|4)` gives the BPM, the offset and the exact grid and the energy profile; put the reveal on the first beat of the drop section.
2. **Quality over quantity.** A few flawless shots beat many mediocre ones. Cut any shot that is not premium.

## Principles that make it feel cinematic

- **Cinema comes from camera, light, rhythm and sound**, not from showy animation.
- **One effect per shot**, and after the key information lands, let it breathe.
- **Strong-beat tracks: every transition and effect lands on the beat.**
- **Use real screenshots** to show an existing product's UI; fake UI only where nothing exists to capture.
- **The visual language grows from the product** (its colours, type, shapes), not from a borrowed template.
- **Deterministic**: nothing random or clock-based in the graphics, so the preview equals the render.

## In vedit

```
music_beats -> add_clips on the grid -> apply_style -> blocks and punch-ins -> preview_grid -> review_edit
```

- Hook: `kinetic_words`, `glitch_title` or `countdown` at `start=0`, a `camera_move` `punch_in` on the first beat.
- Tease: `highlight_box` or `circle_highlight` on one detail; short clips on the beat.
- Reveal: `flash_frame` or `color_wipe` exactly on the drop, then the product shot and `title`.
- Montage: one benefit per shot, `stat_card`, `counter`, `steps`, `comparison`, `price_tag`, `rating_stars`, `checklist`; `beat_pulse` on the hero shot; each shot gets motion (`spinta` or `punch` in `apply_style`).
- End card: `logo_shine` or `end_card` (logo text, `handle` as the CTA), music out with a keyframed gain.
- The music must move too: automate its gain (rise into the drop, duck for the voice).
- Do not export unless asked.

## Variants

- **Testimonial**: a `quote` block on a darkened frame, the person's name in a `lower_third`, one idea per quote.
- **Ad creative for several formats**: build once in 16:9, then `project_settings(format=...)` for 9:16 and 1:1 and re-check every graphic (the blocks are in `vw`/`vh`, so they follow).

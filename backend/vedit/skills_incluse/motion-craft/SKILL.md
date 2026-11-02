---
name: motion-craft
description: Timing, easing, stagger, springs, title holds and transitions that make animation look designed and not generated. Use when animating anything in a vedit project (add_block, add_html graphics, set_transform keyframes, set_transition), and when the user says it feels like slides, too fast, too slow, robotic or cheap.
source: Adapted from the HyperFrames motion skill (heygen-com/hyperframes, Apache-2.0) and the iart.ai animation-principles skill (MIT). See NOTICE.md.
---

# Motion craft

Defaults measured on real finished films. A reference the user gave, or a beat that does otherwise on purpose, wins over any number here.

## Ease by role

- **Arrivals** land on a long tail: keyframe `ease_out_cubic`, CSS `cubic-bezier(0.16, 1, 0.3, 1)`. Landing takes longer than leaving.
- **Camera moves and colour floods** ease both ways: `ease_in_out_cubic`.
- **Exits and zoom-throughs** accelerate: `ease_in_cubic`. An exit is one smooth motion, never slide, stop, then leave.
- Never linear, except a steady clock or time axis (a year counter).

## Time

| What | Value |
|---|---|
| Fast move | 0.3-0.6 s |
| One text fragment reveal | 0.4-0.6 s |
| Exit | 40-50% shorter than the entrance |
| Overlap | next element starts when the previous is 30-50% done |
| Stagger | lines 60-100 ms, words 40-120 ms, letters 20-40 ms; cap the whole reveal near 0.8 s |
| Hold a line to be read | 0.5 s + 0.3 s per word; the last line of the film at least 2 s |

Fully sequential looks robotic, all at once looks cheap.

## Springs

Name them by damping: 1.0 never bounces, 0.7-0.85 reads premium, 0.4-0.6 playful, under 0.3 cartoon. Position and size may bounce; opacity and colour never do.

## Titles

- A landed title is **dead still**. The motion moves to the next element, the camera or the world behind it.
- Vary entrances within a film, never fade-and-slide-up for each: per word blur 6 px to 0 (0.13 s each, 0.067 s apart); per word light grey to ink; the whole line blurring in; per letter for a name; one word rolling through options.
- Size: 4-9% of the frame height, one or two lines. Quiet lines at 2.5-4% against hero words that fill 60-90% of the width. One word in the accent colour, and it must carry meaning.
- vedit: `add_block` `title`, `kinetic_words`, `typewriter`, `sticker_text`; custom in `add_html`.

## Camera

`camera_move(clip, move)` writes the keyframes for you with the edges always covered; `list_moves` describes all 16. Pick by what the shot says: `push_in` / `pull_out` for attention and aftermath, `slow_push` to keep a long hold alive, `pan_left` / `pan_right` / `tilt_up` / `tilt_down` to follow or reveal, `drift` (Ken Burns) for stills and maps, `punch_in` on a beat, `zoom_burst` into a cut, `impact_shake` on a hit, `beat_pulse` with the BPM from `music_beats`, `handheld` for raw footage, `sway` for dreamy, `dutch_tilt` when something is wrong. One move per shot with a reason; a different move on every clip is noise, like a transition without a cause.

## Rhythm

Contrast speeds. Montages cut every 0.13-0.8 s; a demo holds one framing 7-10 s while the UI acts; shots average 1.8-3 s with motion inside them. Hold 0.3-0.75 s before the payoff.

## Transitions need a cause

Use 3-5 kinds in a film, each caused by something on screen. Hard cuts belong inside a scene (punch-ins); at most a third of the seams between beats are hard cuts; worlds never crossfade into each other.

| Idea | In vedit |
|---|---|
| Colour flood (the ground changes colour in ~0.4 s) | `add_block` `color_wipe`, or a flat `add_color` with fades |
| Whip (smear 0.13-0.3 s, arrives blurred, sharpens in 0.13 s) | `set_transition` `slide_*` short, plus `add_effect` blur with keyframes |
| Iris from the click | `set_transition` `iris` |
| Dip cut (outgoing frame darkens ~40% for 3 frames before a hard cut) | `add_block` `flash_frame` in black, or `add_effect` brightness keyframes |
| Blur swap on one stage (out: 8 px blur + fade in 0.13-0.2 s) | `add_effect` blur + `set_fades` |
| Impact | `flash_frame` white, short |

## What looks generated (avoid)

- Breathing, floating or pulsing loops standing in for motion on titles and UI.
- Titles that keep sliding or scaling after they land; a slow creeping scale late in a scene.
- The same entrance on every element.

## Cut on the beat

Frames per beat = fps x 60 / BPM. Compute each beat from its index and round it; never add a rounded beat repeatedly (it drifts). In vedit that is `music_beats(every=1|4|8)`: use its `griglia`. Cut at the fastest frame of a move, with matching direction and speed on both sides.

## When the user says

| They say | Do |
|---|---|
| "too fast" | slow every zoom and pan to 0.7x, nothing else |
| "speed this up" | speed the content and shorten the beat by the same amount; later beats move up |
| "the titles move" | land them, then hold them still until they leave |
| "it feels like slides" | enter the next scene through an object already on screen; cut a move mid-flight |

## Verify

Look at the key instants, not the whole: `preview_frame(t=[...])` at the entrance, the hold and the exit. Everything in an `add_html` clip must be a function of the clip time (no `Math.random`, no `Date.now`: use a seeded hash), otherwise the preview and the render differ.

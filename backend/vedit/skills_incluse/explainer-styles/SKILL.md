---
name: explainer-styles
description: Narrated explainer videos of 30-90 seconds - the story arc, script-first method, one analogy, pacing per beat - and the whiteboard draw-on look. Use when the user wants an explainer, a how-it-works video, an onboarding video, an animated concept video or a doodle/scribe look in vedit.
source: Adapted from the iart.ai explainer-video and whiteboard-animation skills (MIT). See NOTICE.md.
---

# Explainer videos

An explainer is an argument, not a feature tour. Lock the story before any building.

## Story

- **One core idea**: a sentence the viewer can repeat afterwards. If you cannot say it in one line, cut scope.
- **Script first.** The voice is the spine; visuals illustrate the line being spoken and never lead it. It is far cheaper to cut a sentence than a scene.
- **Earn the "how" with stakes.** Make the viewer feel what the problem costs before showing the mechanism.

| Stage | Job | The viewer thinks |
|---|---|---|
| Problem | name the pain in their words | "That's me." |
| Stakes | what it costs (time, money, risk) | "I need this fixed." |
| Solution | the product or idea as the fix, in one line | "Oh, that solves it." |
| How it works | the mechanism in 1-3 concrete steps | "I get how." |
| Payoff / CTA | the after-state and one next action | "I want that." |

## One analogy

Map the abstract to something the viewer already knows (a queue, a thermostat, an assembly line) and keep it for the whole video, in the visuals and in the words. Switching analogies resets comprehension. If the analogy needs its own explanation it is the wrong one.

## Pacing per beat

| Beat | Feel | Cuts |
|---|---|---|
| Problem / Stakes | brisk, a little tense | faster, short holds |
| Solution | a beat of relief | one clear hold |
| How it works | deliberate, one step at a time | slowest: hold each step so it can be read |
| Payoff / CTA | confident, open | hold the end card, one CTA |

## In vedit

The voice-first method is vedit's own and it is mandatory here: script, then `generate_voice`, then build on the **measured** times of the voice (`speech_times`), one `add_html` clip per chapter, no `set_speed` on the voice, `duck_music` under it.

- Structure on screen: `section_label` for the stage, `steps` for the mechanism, `comparison` for before/after, `stat_card` and `counter` for the stakes, `end_card` for the CTA, `chapter_card` between chapters.
- Captions for muted viewing: `transcribe` then `make_captions`, or `caption_pill` for the key phrase only.
- Style from a reference: `learn_style` on a video you like, then `apply_style`.

## Whiteboard draw-on look

A hand draws illustrations and handwriting stroke by stroke while the voice explains. The mechanism is an SVG path that draws itself: set `pathLength="1"`, `stroke-dasharray: 1`, and animate `stroke-dashoffset` from 1 to 0. With a CSS animation the clip clock drives it, so it is frame-exact in the preview and the render:

```html
<svg viewBox="0 0 100 60"><path d="M5 40 C 25 5, 45 55, 65 20 S 95 30, 95 30" pathLength="1"
 fill="none" stroke="#1b1b22" stroke-width="1.6" stroke-linecap="round"
 stroke-dasharray="1" stroke-dashoffset="1" style="animation:draw 1.4s ease-in-out .3s forwards"/></svg>
<style>@keyframes draw{to{stroke-dashoffset:0}} body{background:#f6f3ea}</style>
```

- Draw in the order a person would: outline, then detail, then text. Time each stroke to the word it illustrates (`speech_times`).
- Put the board colour in the clip (a light background) or use `add_color` under a transparent clip.
- The hand: a separate image that follows the tip of the stroke; if it is not exact at the tip the illusion breaks, so check with `preview_frame(t=[...])` mid-stroke.

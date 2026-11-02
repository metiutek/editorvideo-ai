---
name: talking-head-edit
description: Editing raw talking-head, interview and tutorial footage - cutting filler and dead air, choosing takes, cut padding, audio fades, captions, self-checking the result. Use when the user hands over raw takes to edit, wants filler words and silences removed, or asks for a clean cut of a spoken video in vedit.
source: Adapted from the browser-use/video-use skill (MIT). See NOTICE.md.
---

# Talking-head editing

The model never watches the video: it *reads* it. Audio is primary and visuals follow.

## Read it first

1. `transcribe(media=["*"], with_words=True)` once for all the takes. Word-level and verbatim: never phrase-level (it loses sub-second gaps) and never with fillers normalised away (they are editorial signal). Transcripts are cached per source; do not redo them unless the file changed.
2. `inspect_footage` / `preview_media` only at the decision points: an ambiguous pause, two retakes to compare, a cut point to sanity-check. Do not dump frames.

## Hard rules (correctness, not taste)

1. **Never cut inside a word.** Snap every cut edge to a word boundary.
2. **Pad every cut edge** 30-200 ms. ASR timestamps drift 50-100 ms and the padding absorbs it. Tighter for fast pace, looser for cinematic.
3. **Audio fades at every cut** (about 30 ms) or each join pops. vedit: `smooth_cuts`.
4. **Captions go last**, above every overlay, with times in the *output* timeline (not the source): `make_captions(clip=...)` reports them against the clip.
5. **Confirm the strategy before touching the cut**: say the plan in plain words and `ask_user` (keep which takes, how tight, captions or not). Never cut first and explain after.
6. **Verify before showing**: `check_cuts`, `verify_edit`, `preview_grid`. Fix and re-check; if you would not ship it, do not present it.

Everything else is taste: invent freely (split screen, L-cuts and J-cuts, speed ramps, freeze frames, crossfades, lower-third cards) when the material calls for it.

## Workflow

```
inventory -> propose plan -> ask_user -> tighten_speech -> pick takes -> graphics -> captions -> check_cuts -> render only if asked
```

- **Dead air and fillers**: `tighten_speech(clip, min_silence=0.5, pad=0.12, fillers=True)`; lower `min_silence` for a faster pace.
- **Retakes**: keep the last complete take unless the earlier one is better; say which you chose.
- **Overlays**: `add_block` `lower_third` for who is speaking, `kinetic_words` or `caption_pill` for a key line, `highlight_box` to point at something on screen.
- **Colour**: `match_color` so the takes match each other before any look is applied.
- **Memory**: `remember` the user's preferences (pace, caption style) so the next session starts from them.

See `short-form-video` for caption grouping and placement.

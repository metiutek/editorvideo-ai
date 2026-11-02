---
name: short-form-video
description: Vertical 9:16 shorts for Reels, TikTok and YouTube Shorts - the retention arc, hooks, pattern interrupts, caption grouping and placement. Use when the user wants a short, a reel, a vertical video, better retention, or burned-in captions on a talking-head clip in vedit.
source: Adapted from the iart.ai short-form-video skill (MIT), the HyperFrames captions reference (Apache-2.0) and the browser-use/video-use subtitle styles (MIT). See NOTICE.md.
---

# Short-form video

A retention machine, not a small launch film. Retention beats production value: about 87% of viewers decide in the first 3 seconds, and distribution favours videos holding 70%+ average view-through.

## Story

- **One idea per video.** A second idea splits attention; make it a second video.
- **Open a loop in the first ~3 s and close it last.** The hook poses a question or gap; never answer it early.
- **No dead air.** Every beat advances the idea or resets attention. "Hey guys, in this video..." is where they swipe.

## The arc (a 20 s short)

| Beat | Job | Time |
|---|---|---|
| Hook | one frame and one line that open the loop | 0-1 s |
| Setup | why watch: promise, stakes or the gap | 1-4 s |
| Body | value in beats, one idea per beat | 4-17 s |
| Payoff / loop | close the loop, or feed back to frame 0 | 17-20 s |

Scale the body, never the hook: a 60 s short has a longer body and the same 1 s hook.

## Hook

Pick one pattern and commit: open loop ("The reason your X keeps Y..."), direct promise ("3 ways to ... in 30 seconds"), pattern interrupt (snap zoom, whip pan, a visual mismatch in frame 1), negation ("Stop doing ...").

- The hook line is **on screen as text by frame 1** (most people watch muted). vedit: `add_block` `kinetic_words`, `mask_reveal_title`, `glitch_title` or `sticker_text` at `start=0`.
- The most striking visual is also the first frame. No slow ramp-in, no fade up from black.

## Pattern interrupts

Any change that resets attention: a hard cut, a zoom punch, a b-roll insert, a sound effect, a caption pop, an angle change. Aim for a visual change every 2-4 s. In vedit: `add_clips` on the beat grid, `set_transform` keyframes for punch-ins (`ease_out_cubic`), `add_block` `flash_frame`, `apply_style` with a punchy style. Interrupts must be varied: the same one repeated stops working.

## Captions

Get word timings: `transcribe(with_words=True)`; never phrase-level. Then `make_captions(format="ass", karaoke=True, ...)`.

- **Grouping**: 2-3 words for high energy, 3-5 conversational, 4-6 calm. Break at a sentence end, a pause of 150 ms or more, or the word limit. Do not flash a cue under 0.35 s: grow it to 3 words instead.
- **One group visible at a time.** A group opens at or before its first word and closes at or after its last. Not at exactly 0 s (it looks pre-existing): start 0.1-0.3 s in.
- **Styles**: fast social = about 2 words, UPPERCASE (`uppercase=True`, bold, outline); narrative or educational = 4-7 words in sentence case, larger, more margin.
- **Place**: inside the 80% title-safe box, never over the speaker's face. In 1080x1920 roughly a third of the height from the bottom (`margin_v`); in 16:9 80-120 px from the bottom.
- Captions go on top of everything: check with `preview_frame` that no graphic covers them.

## Cutting speech

Never cut inside a word: snap to word boundaries. Pad each cut edge 30-200 ms (ASR timestamps drift 50-100 ms). `tighten_speech` removes silences and fillers; `smooth_cuts` softens the audio at the joins; `check_cuts` verifies them.

## Loop and ask

End by feeding back to frame 0, or with one clear ask, never both. The ask is `subscribe_button`, `handle_tag` or `end_card`. For a story told in messages use `chat_messages` or `notification_toast`; to underline the one word that matters, `marker_highlight`. Export only when the user asks.

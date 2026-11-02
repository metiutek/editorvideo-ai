---
name: vedit
description: Edit video with vedit, a non-linear editor driven through MCP tools. Use when the user wants to cut, assemble, caption, color, add motion graphics or voice-over to video, make a short or a narrated explainer, cut to music, or edit "like this reference video". Covers the tool workflow, the editing rules that make a video not look flat, and what must be confirmed with the user (export, publish, generating media).
---

# Editing with vedit

vedit is a timeline editor. The project is one JSON document; the render is a pure
function of it (one ffmpeg `filter_complex`). Every change goes through the same
operations whether it comes from the web UI, the in-app chat or this MCP server.

## Set up

Needs the `vedit` MCP server (`claude mcp add vedit -- uvx vedit-mcp`, already wired if you
installed this as a plugin) and ffmpeg. If ffmpeg is missing: `install_ffmpeg`.
Call `open_ui` if the user wants to watch the edit live in the browser; both share one project.

## Workflow

```
project_create -> import_media -> preview_media (look at the footage first)
-> plan_edit (pick the material) -> add_clips -> apply_style -> your own refinements
-> preview_grid / preview_frame (LOOK) -> review_edit -> render_video (only if asked)
```

- Times are in seconds. Animatable parameters take `{"kf":[{"t":0,"v":0},{"t":2,"v":1}]}`.
- `project_info` shows the timeline with ids. Call it when you do not already know the state.
- Many cuts: `add_clips` (atomic, one call). Many other changes: `batch` (atomic, one undo).
  One call per cut is slow, floods undo history and leaves a half-built timeline if it fails.
- `preview_frame` returns the real image. Look at it instead of assuming.
- Cutting to music: `music_beats` gives BPM, bar offset and the energy profile. Do not guess the tempo.

## Rules that stop a video looking flat

1. The music must move: automate its gain with keyframes, pick the section with `music_beats`.
2. Not all hard cuts. A cut is the default, not the only choice; every transition needs a reason.
3. Never show the same shot twice. If the footage is not enough, make the video shorter.
4. After ten seconds the viewer needs new information; cutting faster on the same images does not help.
5. "Cinematic" is a choice, not a filter: one strong moment held for three seconds beats ten half-seconds.

`review_edit` counts the choices in the timeline and flags cut-only edits. Until it stops warning, the edit is not finished.

## Motion graphics: use blocks first

`list_blocks` then `add_block` puts a ready, tuned animation on a track above the footage.
52 blocks in six families: titles (`lower_third`, `title`, `mask_reveal_title`, `glitch_title`,
`word_cycle`, `countdown`, `logo_shine`, `chapter_card`, `end_card`), text (`caption_pill`,
`kinetic_words`, `typewriter`, `chat_messages`, `notification_toast`, `location_pin`, `ticker`,
`quote`...), data (`counter`, `bar_chart`, `donut_chart`, `line_chart`, `timeline`, `rating_stars`,
`price_tag`, `checklist`, `stat_card`, `steps`, `comparison`...), emphasis (`highlight_box`,
`circle_highlight`, `arrow_pointer`, `marker_highlight`, `subscribe_button`, `alert_banner`),
transitions (`color_wipe`, `flash_frame`, `iris_wipe`, `blinds_wipe`) and style (`letterbox`,
`vignette`, `film_grain`, `light_leak`, `scanlines`, `viewfinder`). One call, no CSS; `list_blocks(block=...)` gives the parameters. Only when no block fits
write HTML with `add_html` (transparent background; the page clock is the clip clock, so preview and
render match). Particles: `add_particles`. Highlighting a moving subject: `track_mask`, `highlight_subject`.

## Camera moves

`camera_move(clip, move)` (`list_moves`): `push_in`, `pull_out`, `slow_push`, `pan_left`, `pan_right`,
`tilt_up`, `tilt_down`, `drift`, `punch_in`, `zoom_burst`, `whip_pan`, `impact_shake`, `beat_pulse`
(needs the BPM from `music_beats`), `handheld`, `sway`, `dutch_tilt`. The edges stay covered, one undo.
Pick one for what the shot says; a different move on every clip is noise.

## Plan before building

For more than a handful of clips, or anything that generates images or video (it costs), call
`propose_plan` first: scenes with what, seconds, source and an estimated cost. The user sees times and
totals and approves or asks for changes; only then build. An approved plan is saved next to the project.

## Narrated videos (voice first)

Write the script, generate the voice first (`generate_voice`), then edit on the *measured* times of the
voice (`speech_times`), never on estimated ones. One html clip per chapter, no `set_speed` on the voice,
duck the music under it (`duck_music`).

## Match a reference video

`learn_style` measures how a video is edited (cut rhythm, transitions, camera moves, voice-over and where
cuts fall on its pauses, palette, colour cards) and saves a style. It returns two contact sheets: look at
them and add what cannot be measured (characters, on-screen text, graphics) with `create_style(style=<id>,
guide=...)`, rewriting the whole guide. Then `apply_style` after the clips are in.

## Generating media

`generate_media` (image or video, from a prompt, optionally starting from an image) needs a service set up
by the user (`generation_services` says which is ready). It costs the user's credits, so it asks the user;
never loop on it.

## Never do on your own

- **Export** (`render_video`) and **publish** (`publish_video`): only when the user asks. The editor asks them to confirm.
- **Generate media**, **install a skill**: they ask for confirmation too.
- When a choice is the user's (style, length, format, which version to keep): `ask_user` with 2-4 options,
  the recommended one first, instead of deciding at random.

If something is wrong, awkward or missing in the tool itself, `report_issue` and keep working.

---
name: external-engines
description: Which popular animation engines and skills to use for styles vedit does not render itself - math animation (Manim), 3D and shaders (Three.js, GLSL), React video (Remotion), HTML-to-video (HyperFrames), film styles in code - and how to bring their output into a vedit project. Use when the user asks for a style that html graphics and blocks cannot do, or names one of these tools.
source: Catalogue compiled from the repositories named below (stars and licences as of 2026-11-02). See NOTICE.md.
---

# Styles that need another engine

vedit renders video, audio, effects, particles and HTML/CSS/JS clips. It does **not** run Manim, Remotion, Three.js scenes or After Effects. For those styles: make the animation with the right tool, export a video file, then `import_media` it and edit it in vedit like any footage. Use the same frame size and fps as the project, and check durations after the import.

## Pick by style

| Style | Popular source (stars, licence) | Notes |
|---|---|---|
| Math and science animation | Manim CE (42k, MIT); `adithya-s-k/manim_skill` (1.2k, MIT); `iart-ai/manim-skills` (MIT) | Render to mp4, import. Narration over it: `generate_voice`, then `speech_times`. |
| 3D, WebGL, shaders, particle systems | `iart-ai/webgl-animation-skills` (MIT): Three.js, GLSL, particles | Simple particles are native: `add_particles`. For a 3D scene, render externally. |
| React / programmatic video | Remotion (70k); skill `npx skills add remotion`; `haidrrrry/claude-remotion-skill` (774, MIT) | Remotion's own licence asks larger companies for a company licence. |
| HTML to video, product films | HyperFrames (77k, Apache-2.0): about 450 ready blocks; `npx skills add heygen-com/hyperframes` | Closest to vedit's own HTML clips: its craft notes are folded into `motion-craft`. |
| Product promos with shot recipes | `Vincentwei1021/video-shotcraft` (16k, Apache-2.0): 124 recipe cards in Remotion | Principles are in `product-launch`. |
| Film styles drawn in code | `lemomo-ai/lemo-opuscar` (11k, MIT): 66 styles | Tuned for one model; treat as style prompts. |
| Editing real footage | `browser-use/video-use` (30k, MIT) | Folded into `talking-head-edit`. |
| Whole videos from a prompt | MoneyPrinterTurbo (137k, MIT); Pixelle-Video (30k, Apache-2.0); OpenMontage (75k, **AGPL-3.0**) | Separate tools. Do not copy AGPL code into this project. |

## How to bring it in

1. Render with the external tool at the project's size and fps (`project_info` gives them).
2. `import_media(paths=[...])`, then `add_clip`. If the render has an alpha channel, check with `preview_frame` that it composites; if not, put it on a track above and `set_clip(blend="screen")` for light-on-black elements.
3. Everything else (cuts, music, captions, voice, grading) stays in vedit.

## Installing someone else's skill

`install_skill(source=...)` accepts a GitHub link, a folder, a `.zip` or a `.md`. It always asks the user first: a skill is instructions the model will follow. After installing, read its craft sections and **ignore its delivery sections** (they describe another engine's render commands, which cannot run here).

## Be honest with the user

When a request needs one of these engines, say so plainly: what vedit will do (editing, audio, captions, voice, native graphics) and what has to be made elsewhere. Do not fake a 3D scene or a math animation with CSS.

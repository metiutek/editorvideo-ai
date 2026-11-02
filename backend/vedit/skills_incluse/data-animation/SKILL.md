---
name: data-animation
description: Charts, counters, rankings and infographics that move with intent - count-ups, bar growth, bar chart races, progress rings, step diagrams. Use when the user wants numbers or data animated in a vedit video, a stat on screen, a chart reveal, or a ranking over time.
source: Adapted from the iart.ai chart-animation and animated-infographic skills (MIT). See NOTICE.md.
---

# Data animation

Map numbers to pixels every frame, ease the *value* and not only the opacity, and pace the reveal so the viewer can read it.

## The one rule that prevents most bugs

**Every value is a function of the clip time.** Never of wall-clock time, and never of a charting library's own animation loop (Chart.js `animation`, D3 `.transition()`). The preview and the render must show the same frame. In an `add_html` clip that means `window.veditRender = (t) => {...}` (t in seconds of the clip) or CSS animations with fixed durations. D3 is still fine for scales and shapes.

## Value to pixels

A chart is two functions kept apart: a value scale (data units to pixels) and a time interpolator (clip time to eased progress 0 to 1). Then format the number a human reads.

## Ease the value

- Count-ups and bars growing in: ease-out cubic (`1 - (1-t)^3`) reads as "settling on a number".
- Rank changes: a spring, so a bar that overtakes another has a little life.
- Never interpolate linearly a number the viewer reads, unless it is a steady time axis (a clock, a year).

## Counters

- **Round before formatting** (no `1287.4013`).
- **Fix the digit box**: `font-variant-numeric: tabular-nums; line-height: 1;` so the layout does not wiggle as digits change.
- Format with `Intl.NumberFormat` for thousands separators, currency, percent.

## Bar chart race

Real data is sparse (one row per year). A smooth race needs keyframes interpolated between the rows, a rank computed from the *interpolated* value, and bars that slide to their new rank with an ease, not jump.

## In vedit

Ready blocks first: `counter` (counts from one value to another), `bar_chart` (labels and values, grows in sequence), `progress_ring` (a percentage), `stat_card` (a figure with a label and a delta chip), `steps` (numbered stages), `comparison` (two panels with VS), `list_reveal` (bullets one by one).

When none fits (line charts, races, maps of numbers) write an `add_html` clip with SVG and `veditRender`. Put it on a track above the footage; for a chart on its own full-frame, put an `add_color` behind it.

## Design

- One chart, one message: state it in the title.
- Keep to ten bars or fewer; label the bars directly.
- Hold the final state at least 1.5 s so it can be read; the numbers are the point, not the motion.
- Contrast first: text over a dark panel (the blocks do this) and the accent colour for the one thing that matters.
- Check the final frame with `preview_frame(t=[mid, end])` and read every number in it.

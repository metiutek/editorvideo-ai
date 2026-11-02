---
name: lower-thirds
description: Name-and-role straps, corner bugs and other identity graphics laid over footage. Use when the user wants a lower third, a name tag, a speaker caption, a show bug or a title strap on a vedit video, and for how to size, place and time them.
source: Adapted from the iart.ai lower-thirds skill (MIT). See NOTICE.md.
---

# Lower thirds

A lower third says who is speaking, laid over footage the graphic never sees. It must read on any picture.

## Brief first

- **The words exactly as the user gave them**: names, roles, show name, handle. Keep their spelling and punctuation; setting a line in capitals is styling, the words stay.
- **How many**: one per person or item. Make them with the same design.
- **The look**: the show, brand colours, mood (news, podcast, gaming, documentary, corporate). The design comes from this.
- Defaults when nothing is said: lower left; about 8 s (under 1 s in, a still hold of 5-6 s, half a second out).

## Design rules

- **Legible over any footage.** The graphic cannot know what is behind it, so the text sits on its own backing: a panel, a bar, a band, or a heavy shadow. Thin light text straight on the picture disappears on a bright shot.
- **Inside title-safe.** At least 5% in from each edge. The strap lives in the bottom third; a corner bug in a corner; the middle of the frame stays empty.
- **Small.** A name strap covers a few percent of the frame; the name about 50-80 px tall at 1080p, the role about half.
- **Still while it is read.** The motion is in the build-in and build-out; the hold does not move (at most one slow sheen).
- **Starts and ends empty.** The first and last frames have nothing in them, so it never pops on or cuts off.
- **The words are never cut.** A long name shrinks to its box instead of overflowing; check the longest name.

## In vedit

`add_block` `lower_third` (`nome`, `ruolo`, `colore`) is exactly this: accent line, name, role, enters in 0.5 s and fades out inside its duration. Give it `duration=6` to `8` for a name that has to be read, on a track above the footage (`add_track`), with `start` on the first word of the speaker.

- Several people: one block each, in one `batch`, same `colore`.
- A different look (a news bar, a boxed card): write it as `add_html`, keeping the rules above; `caption_pill`, `section_label` and `handle_tag` cover the neighbouring jobs (a short caption, a part label, a channel watermark).
- Check with `preview_frame(t=[start+0.2, start+3])`: the strap readable over the real shot, the longest name inside its box.

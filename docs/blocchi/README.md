# Motion graphics blocks

Rendered by vedit itself (`python scripts/blocchi_galleria.py`), default parameters. Use them with `list_blocks` / `add_block`.

![all blocks](galleria.png)

## Titles

### `lower_third`

![lower_third](lower_third.png)

Name and role bar at the bottom left, with an accent line. Default length 4 s. Parameters: `nome`, `ruolo`, `colore`.

### `title`

![title](title.png)

Big centered title with an accent rule and optional subtitle. Default length 3 s. Parameters: `titolo`, `sottotitolo`, `colore`.

### `chapter_card`

![chapter_card](chapter_card.png)

Full-frame chapter card on a flat color: it wipes in and out. Opaque: put it in the timeline between scenes. Default length 2.5 s. Parameters: `titolo`, `numero`, `etichetta`, `sfondo`, `testo_colore`.

### `end_card`

![end_card](end_card.png)

Closing screen: darkened frame, big title and a pulsing @handle pill. Default length 5 s. Parameters: `titolo`, `handle`, `colore`.

## Text

### `caption_pill`

![caption_pill](caption_pill.png)

Short caption in a rounded pill, at the bottom or the top. Default length 3 s. Parameters: `testo`, `posizione`, `sfondo`.

### `date_badge`

![date_badge](date_badge.png)

Small tag in a top corner for years, dates, counters: 'YEAR 20', '+50 YEARS'. Default length 3 s. Parameters: `testo`, `posizione`, `colore`.

### `quote`

![quote](quote.png)

Serif quote on a darkened frame, with the author below. Default length 5 s. Parameters: `testo`, `autore`, `colore`.

### `kinetic_words`

![kinetic_words](kinetic_words.png)

A sentence whose words pop in one after the other; *word* is highlighted. Default length 4 s. Parameters: `testo`, `colore`.

### `section_label`

![section_label](section_label.png)

Small tag in the top-left corner naming the part: 'Chapter 1 - The hook'. Default length 3 s. Parameters: `testo`, `colore`.

### `typewriter`

![typewriter](typewriter.png)

One line typed out letter by letter, with a blinking cursor (monospace). Default length 4 s. Parameters: `testo`, `colore`.

### `ticker`

![ticker](ticker.png)

News-style bar at the bottom with a label and text scrolling across it. Default length 8 s. Parameters: `testo`, `etichetta`, `sfondo`, `colore`.

### `sticker_text`

![sticker_text](sticker_text.png)

Loud rotated label that slams in the middle of the frame ('WAIT FOR IT'). Default length 2 s. Parameters: `testo`, `angolo`, `colore`.

### `speech_bubble`

![speech_bubble](speech_bubble.png)

White speech bubble placed at x, y (% of the frame), popping in. Default length 3 s. Parameters: `testo`, `x`, `y`, `colore`.

### `handle_tag`

![handle_tag](handle_tag.png)

Small @handle watermark in the bottom-right corner. Default length 6 s. Parameters: `handle`, `colore`.

## Data

### `counter`

![counter](counter.png)

Big number that counts from one value to another and holds. Default length 4 s. Parameters: `da`, `a`, `decimali`, `prefisso`, `suffisso`, `etichetta`, `colore`.

### `bar_chart`

![bar_chart](bar_chart.png)

Horizontal bar chart on a dark panel; bars grow one after the other. Default length 5 s. Parameters: `dati`, `titolo`, `colore`.

### `progress_ring`

![progress_ring](progress_ring.png)

Ring that fills to a percentage while the number counts up. Default length 4 s. Parameters: `valore`, `etichetta`, `colore`.

### `stat_card`

![stat_card](stat_card.png)

Big figure on a card with a label and an optional delta chip ('+12%'). Default length 4 s. Parameters: `valore`, `etichetta`, `delta`, `colore`.

### `steps`

![steps](steps.png)

Numbered steps joined by a line, revealed one after the other (2-6). Default length 5 s. Parameters: `voci`, `colore`.

### `comparison`

![comparison](comparison.png)

Two panels side by side joined by a VS badge. Default length 5 s. Parameters: `sinistra`, `sinistra_testo`, `destra`, `destra_testo`, `colore`.

### `list_reveal`

![list_reveal](list_reveal.png)

Panel with a title and bullet points appearing one by one (1-7). Default length 5 s. Parameters: `titolo`, `voci`, `colore`.

## Emphasis

### `highlight_box`

![highlight_box](highlight_box.png)

Pulsing frame that darkens the rest to point at one area (x, y, size in % of the frame). Default length 3 s. Parameters: `x`, `y`, `larghezza`, `altezza`, `etichetta`, `colore`.

### `progress_bar`

![progress_bar](progress_bar.png)

Thin bar along an edge that fills over the whole clip. Default length 10 s. Parameters: `posizione`, `colore`.

### `arrow_pointer`

![arrow_pointer](arrow_pointer.png)

Bobbing arrow whose tip is at x, y (% of the frame); angle = where it points. Default length 3 s. Parameters: `x`, `y`, `angolo`, `etichetta`, `colore`.

### `circle_highlight`

![circle_highlight](circle_highlight.png)

Ellipse drawn around an area, like circling it with a pen (x, y, size in %). Default length 3 s. Parameters: `x`, `y`, `larghezza`, `altezza`, `colore`.

## Transitions

### `color_wipe`

![color_wipe](color_wipe.png)

Transition: a flat color sweeps across the frame and out again. The cut between scenes goes at the middle of the clip. Default length 1.2 s. Parameters: `colore`, `direzione`.

### `flash_frame`

![flash_frame](flash_frame.png)

Transition: a short flash of color, for impact or a hard beat. Default length 0.4 s. Parameters: `colore`.

## Style

### `letterbox`

![letterbox](letterbox.png)

Cinema bars sliding in at the top and bottom. Default length 6 s. Parameters: `altezza`.

### `vignette`

![vignette](vignette.png)

Soft dark edges that fade in, to pull the eye to the center. Default length 6 s. Parameters: `forza`.

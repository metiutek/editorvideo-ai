# Motion graphics blocks

Rendered by vedit itself (`python scripts/blocchi_galleria.py`), default parameters. Use them with `list_blocks` / `add_block`.

![ten blocks edited into a short video](demo.gif)

*Ten blocks cut into a short video by vedit itself (`python scripts/blocchi_demo.py`).*

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

### `mask_reveal_title`

![mask_reveal_title](mask_reveal_title.png)

Title whose lines rise out of an invisible mask, one after the other (editorial, kinetic). Default length 3.5 s. Parameters: `titolo`, `sottotitolo`, `colore`.

### `glitch_title`

![glitch_title](glitch_title.png)

Uppercase title that tears into red and cyan slices for a moment, then settles. Default length 2.5 s. Parameters: `titolo`, `colore`.

### `word_cycle`

![word_cycle](word_cycle.png)

A fixed phrase and one word that rolls through options and stops on the last ('We make FILMS'). Default length 4 s. Parameters: `prefisso`, `voci`, `colore`.

### `countdown`

![countdown](countdown.png)

Big numbers that replace each other: '3, 2, 1, GO'. The last one stays. Default length 3.6 s. Parameters: `voci`, `colore`.

### `logo_shine`

![logo_shine](logo_shine.png)

Wordmark that lands and gets swept by a glint of light, with an optional tagline. Default length 3.5 s. Parameters: `testo`, `sottotitolo`, `colore`.

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

### `chat_messages`

![chat_messages](chat_messages.png)

Messenger-style bubbles popping in, alternating left (received) and right (sent). 1-5 messages. Default length 5 s. Parameters: `voci`, `colore`.

### `notification_toast`

![notification_toast](notification_toast.png)

Phone-style notification card dropping from the top. Default length 4 s. Parameters: `app`, `titolo`, `testo`, `colore`.

### `location_pin`

![location_pin](location_pin.png)

Map pin dropping at x, y (% of the frame, the tip) with a ripple and a place label. Default length 4 s. Parameters: `luogo`, `dettaglio`, `x`, `y`, `colore`.

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

### `donut_chart`

![donut_chart](donut_chart.png)

Donut chart sweeping round, with a legend of shares. 1-10 label:value pairs. Default length 5 s. Parameters: `dati`, `titolo`, `colore`.

### `line_chart`

![line_chart](line_chart.png)

Line chart drawn left to right with points popping on it. 2-10 label:value pairs. Default length 5 s. Parameters: `dati`, `titolo`, `colore`.

### `timeline`

![timeline](timeline.png)

Horizontal timeline that draws itself, with milestones above and below. 2-6 items. Default length 6 s. Parameters: `voci`, `colore`.

### `rating_stars`

![rating_stars](rating_stars.png)

Five stars filling up to a rating, with the number and a caption. Default length 3.5 s. Parameters: `valore`, `etichetta`, `colore`.

### `price_tag`

![price_tag](price_tag.png)

Price card: the old price gets struck out, the new one pops, with an optional badge. Default length 4 s. Parameters: `prezzo`, `vecchio`, `etichetta`, `badge`, `colore`.

### `checklist`

![checklist](checklist.png)

Panel whose items get ticked one by one, each tick drawn by hand. 1-6 items. Default length 5 s. Parameters: `titolo`, `voci`, `colore`.

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

### `marker_highlight`

![marker_highlight](marker_highlight.png)

A sentence where *starred* words get a marker swipe behind them, one after the other. Default length 4 s. Parameters: `testo`, `colore`.

### `subscribe_button`

![subscribe_button](subscribe_button.png)

Subscribe button that gets pressed, turns into 'Subscribed' and rings its bell. Default length 4 s. Parameters: `testo`, `fatto`, `colore`.

### `alert_banner`

![alert_banner](alert_banner.png)

Bar dropping from the top with a blinking '!' (warning, breaking, update). Default length 3.5 s. Parameters: `testo`, `etichetta`, `colore`.

## Transitions

### `color_wipe`

![color_wipe](color_wipe.png)

Transition: a flat color sweeps across the frame and out again. The cut between scenes goes at the middle of the clip. Default length 1.2 s. Parameters: `colore`, `direzione`.

### `flash_frame`

![flash_frame](flash_frame.png)

Transition: a short flash of color, for impact or a hard beat. Default length 0.4 s. Parameters: `colore`.

### `iris_wipe`

![iris_wipe](iris_wipe.png)

Transition: the frame closes to a color through an iris and opens again. Cut at the middle. Default length 1.2 s. Parameters: `colore`, `x`, `y`.

### `blinds_wipe`

![blinds_wipe](blinds_wipe.png)

Transition: vertical blinds close in a ripple, stay shut for a beat, then open. Cut at the middle. Default length 1.2 s. Parameters: `colore`, `strisce`.

## Style

### `letterbox`

![letterbox](letterbox.png)

Cinema bars sliding in at the top and bottom. Default length 6 s. Parameters: `altezza`.

### `vignette`

![vignette](vignette.png)

Soft dark edges that fade in, to pull the eye to the center. Default length 6 s. Parameters: `forza`.

### `film_grain`

![film_grain](film_grain.png)

Moving film grain over the whole frame (subtle; set the clip blend to overlay or soft light if you like). Default length 6 s. Parameters: `forza`.

### `light_leak`

![light_leak](light_leak.png)

Warm light drifting across the frame once, like a leak on film (set the clip blend to screen). Default length 3 s. Parameters: `colore`.

### `scanlines`

![scanlines](scanlines.png)

CRT scanlines with a slow rolling bar: retro monitor, VHS, found footage. Default length 6 s. Parameters: `forza`.

### `viewfinder`

![viewfinder](viewfinder.png)

Camera viewfinder: corner brackets, a blinking REC dot and a crosshair. Default length 6 s. Parameters: `etichetta`, `colore`.

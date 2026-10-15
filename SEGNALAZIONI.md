# Segnalazioni

Cose che non funzionano, scomode, che danno risultati sbagliati o che mancano,
annotate da chi monta (strumento MCP `report_issue`). Una voce risolta si cancella.

Tipi: `bug` errore o crash, `scomodo` funziona ma costa troppi passi,
`sbagliato` risultato diverso da quello promesso, `manca` serve e non c'e',
`lento` troppo tempo per quello che fa.

## [sbagliato] apply_style / review_edit — 2026-10-14 12:16

apply_style('dinamico') fallisce con 'nessuna clip video in timeline' su un progetto fatto solo di clip html (spot motion graphics); review_edit poi chiede movimento e colore che apply_style avrebbe dovuto dare.

- **compito:** spot/GIF promo interamente in add_html
- **proposta:** apply_style accetta clip html (spinta lenta + look master) e review_edit considera l'animazione interna all'HTML come movimento.

## [sbagliato] review_edit — 2026-10-14 12:16

review_edit su progetto solo-HTML: set_transform scale kf su tutte le 6 clip html e add_effect vignette sul master non tolgono gli avvisi 'movimento' e 'colore' (conti: clip_video 0, con_movimento 0, effetti_master 1 ma colore ancora mancante). Gli avvisi non si possono risolvere.

- **compito:** spot motion graphics solo add_html
- **proposta:** contare clip html con transform animato come movimento; per progetti senza riprese non chiedere look colore.

## [bug] add_html / preview_frame — 2026-10-14 12:28

Le clip html rendono nero/trasparente-nero negli ultimi ~2 fotogrammi (preview_frame t=17.37 su clip 13.8-17.4 = tutto nero; t=2.38 su clip 0-2.4 nero mentre t=2.30 ok). Ai tagli tra scene HTML compare un flash nero.

- **compito:** spot di 6 scene HTML consecutive su V1
- **proposta:** renderizzare la pagina fino all'ultimo fotogramma della clip (probabile off-by-one sul tempo finale o frame non ancora pronti).

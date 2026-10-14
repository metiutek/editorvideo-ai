# Registro delle modifiche

Le voci più recenti stanno in cima.

## Non ancora rilasciato

### Aggiunto
- **Particelle su misura.** Oltre ai tipi pronti, `add_particles(kind="custom")` prende una
  ricetta: forma (cerchio, quadrato, triangolo, stella, cuore, anello, trattino, testo o
  emoji), moto (cadono, salgono, vento, fluttuano, esplosione da un punto, ferme che
  compaiono), colori, quantità, dimensione e velocità da/a, direzione, ondeggio, rotazione,
  opacità, bagliore, scintillio, e per l'esplosione origine, ventaglio, gravità, durata e
  ritmo. Nell'editor, *+ particelle → su misura…* apre una finestra con l'anteprima dal vivo
  (lo stesso documento del render); le ricette si salvano fra *le mie*
  (`~/.vedit/particelle.json`) e tornano nel menu. Una clip di particelle già in timeline si
  cambia dalle proprietà o con `set_particles`, senza perdere posizione, fusione ed effetti.
  Per l'agente: `create_particles`, `delete_particles`; nella chat `add_particles` e
  `set_particles`.
- **Una clip con audio entra in timeline come negli editor desktop.** Trascinata dal
  pannello, inserita dal monitor sorgente o con doppio clic, il video va sulla traccia
  video e il suo audio su una traccia audio, come clip a parte con la sua forma d'onda.
  Le due metà sono collegate (`Clip.link`): spostarle, tagliarle, dividerle, cambiarne la
  velocità o cancellarle agisce su tutte e due, e la metà collegata si vede tratteggiata
  quando l'altra è selezionata. *scollega audio e video* nelle proprietà
  (`Store.unlink_clip`) le separa per un J/L cut; `jl_cut` e `detach_audio` lo fanno da
  soli. Se A1 è occupata in quel tratto l'audio va sulla prima traccia libera o su una
  nuova. Via MCP `add_clip` resta com'era, con l'audio dentro la clip video, salvo
  `audio_collegato=True`.
- **Importare tanti file senza bloccare l'editor.** Centinaia di file o decine di GB
  fermavano tutto. Quattro cause, sistemate come fanno gli editor desktop:
  - *trascinati*: partiva una sola richiesta multipart con tutti i file, senza progresso,
    rifiutata oltre i 1000 file e da rifare da capo se cadeva. Ora ogni file viaggia a pezzi
    da 32 MB (`/api/upload/pezzo`), tre alla volta, con avanzamento, velocità e pulsante
    *ferma*. Un pezzo fallito si ritenta, un file arrivato a metà riprende da lì, uno già
    arrivato non si ricopia. Prima di copiare si controlla lo spazio libero (`caricamento.js`);
  - *metadati*: ffprobe girava un file alla volta, col progetto bloccato. Ora va in
    parallelo (`probe.probe_many`) e fuori dal lock (`/api/import`). I file arrivano a
    blocchi da 50, quindi il bin si riempie man mano. Un file rovinato viene scartato e
    segnalato, e gli altri entrano lo stesso. Misurato: 300 clip 1080p in 6 s, con l'API
    che risponde in meno di 30 ms;
  - *miniature e forme d'onda*: la UI le chiedeva tutte insieme e il server lanciava fino
    a 40 ffmpeg che decodificavano file interi. Ora c'è una coda: al massimo 3 richieste
    dal browser, la timeline prima del pannello, e il pannello chiede solo quello che si
    vede. Sul server al massimo `cpu/2` lavori pesanti alla volta (`VEDIT_LAVORI`), in un
    gruppo di thread separato, e un solo lavoro per risultato. Sui file lunghi la striscia
    legge solo i keyframe (`-skip_frame nokey`);
  - *importa cartella*: nel dialogo di import prende una cartella intera con le
    sottocartelle, per riferimento e senza copia (`/api/scan`). Le sottocartelle diventano
    cartelle del bin.
- **`report_issue`: l'agente annota cio' che non va.** Bug, strumenti scomodi, risultati
  sbagliati, funzioni che mancano per un compito, lentezze finiscono in `SEGNALAZIONI.md`
  (dal clone) o `~/.vedit/SEGNALAZIONI.md`, da cui decidere cosa migliorare. Le istruzioni
  MCP dicono di usarlo subito, senza fermarsi (`segnalazioni.py`).
- **Import da dischi esterni.** Il dialogo di import si fermava alla radice di `C:\`: D:,
  chiavette e dischi di rete si raggiungevano solo scrivendo il percorso. Ora da `..` sulla
  radice si arriva all'elenco dei dischi (su macOS/Linux anche `/Volumes`, `/media`, `/mnt`),
  e il pulsante *tutti* seleziona in un clic i file di una cartella intera.
- **Trascinare una cartella la importa tutta.** Il browser passa la cartella come un file
  senza estensione, e l'import rispondeva "nessun file multimediale riconosciuto" davanti a
  una cartella di effetti sonori e canzoni. Ora si scende nelle sottocartelle, e ognuna
  diventa una cartella del bin (`trascina.leggiTrascinati`). Riconosciuti anche `.aif`,
  `.wma`, `.aiff` e `.gif` trascinati.

### Corretto
- **Un progetto nuovo parte senza stile di montaggio.** Lo stile scelto nella chat restava
  quello del progetto precedente (era salvato nel browser e basta): creare un progetto, dal
  dialogo o trascinando dei file senza progetto aperto, ora lo rimette su *nessuno*.
- **Video neri e muti nel monitor (DNxHR, ProRes, H.265, MXF...).** Il browser riproduce
  solo H.264/VP9/AV1 a 8 bit 4:2:0 con audio AAC/MP3/Opus: i .mov esportati da Resolve
  (DNxHR 4:2:2 con audio PCM) restavano neri e senza suono, mentre il render usciva
  giusto. Ora `probe` legge codec e formato dei pixel, e appena un file non leggibile
  entra nel progetto (import, apertura di un progetto vecchio, agente via MCP) il server
  ne prepara da solo un proxy H.264/AAC in fondo, uno alla volta, con l'avviso
  "preparo l'anteprima". Il monitor passa al proxy appena è pronto; il render usa
  sempre l'originale. `VEDIT_PROXY_AUTO=0` lo spegne.
- **L'audio delle clip video si vede in timeline.** Era già nel montaggio e nel render,
  ma la clip video non lo mostrava: ora la forma d'onda sta in fondo alla clip finché
  l'audio non viene scollegato o silenziato.
- **File trascinati che fallivano su Windows con "Permission denied" / "file utilizzato
  da un altro processo".** L'antivirus (o l'indicizzazione, o un client di sincronizzazione)
  apre il `.part` appena chiuso per scansionarlo, e in quei secondi il pezzo dopo non si
  poteva scrivere e il file finito non si poteva rinominare: il server rispondeva 500 con
  una traccia lunghissima. Ora aspetta e riprova fino a una ventina di secondi; se il
  blocco resta risponde 503, e il browser rimanda il pezzo da solo. Due upload dello stesso
  file (trascinato due volte, un secondo tab) non scrivono più insieme sullo stesso `.part`.
- **Chiudere l'editor chiude anche i suoi render.** Su Windows un ffmpeg lanciato
  dall'interfaccia sopravviveva alla chiusura: un export a grafo unico è rimasto acceso da
  solo per ore a 20 GB di memoria, con l'editor già chiuso e riaperto, rallentando tutto
  il resto. Ora `vedit ui` e il server MCP entrano in un Job Object che chiude ffmpeg,
  Chromium e la CLI di Claude Code quando vedit muore. Il browser con l'interfaccia resta
  aperto (`figli.py`).
- **Il "despill" del chroma key non toglieva il verde.** Era `chromanr`, una riduzione del
  rumore di crominanza: raddoppiava il costo del key e il riflesso restava tutto. Ora è
  `despill`, sul canale del fondale (verde o blu, dal colore del key). `despill_amount` è
  la percentuale di riflesso tolta, 100 di default.
- **Le cache non crescono più senza limite.** Le grafiche HTML lasciavano una versione per
  ogni ritocco, fino a 1,4 GB l'una: la cartella era arrivata a 12 GB. Grafiche html (4 GB,
  `VEDIT_CACHE_HTML_MB`), anteprime (2 GB, `VEDIT_CACHE_ANTEPRIMA_MB`) e pezzi d'export si
  potano buttando i file usati meno di recente, mai quelli usati nell'ultima ora;
  `clear_cache` svuota anche le grafiche html.
- **In modalità fedele una modifica non butta via tutti i segmenti pronti.** La cache dei
  segmenti era legata alla revisione del progetto: qualunque ritocco, anche a un minuto di
  distanza, rifaceva tutto. Ora la chiave è il contenuto del segmento, come per i pezzi
  dell'export: dopo una modifica lontana lo stesso segmento torna in 0,1 s invece di 5 s,
  e un undo ritrova quello di prima.
- **In diretta gli effetti ora si vedono, da fermi.** La riproduzione in diretta la compone
  il browser, che non sa rifare glitch, warp, lenti, LUT, chroma key, glow e simili: anche a
  video fermo si vedeva l'immagine senza effetti, e l'unico modo per giudicarli era passare
  a "fedele". Ora, quando ti fermi su un punto dove la diretta è approssimata, il monitor
  mostra il fotogramma calcolato da ffmpeg (uguale all'export, mezzo secondo) con il badge
  "fotogramma esatto". In riproduzione il badge dice di fermarsi per vedere gli effetti.
  Anche gli effetti del master ora fanno scattare l'avviso.
- **Le grafiche HTML non si rifotografano a ogni tratto.** La cache delle clip HTML era per
  tratto: ogni segmento d'anteprima o fotogramma mai visto riapriva Chromium e rifotografava
  la grafica, e sul videoclip con quattro clip HTML un segmento fedele da 4 s costava 50-62 s,
  un fotogramma 5,5 s. Ora si fotografano a blocchi di 4 s allineati al tempo della clip,
  riusati da qualunque tratto (più blocchi si leggono in fila con un elenco `ffconcat`), lo
  scrub fotografa solo i fotogrammi che servono, e l'anteprima usa anche le grafiche intere
  già fotografate a piena misura da un export. Stesso progetto: segmento da 4 s in 5,4 s,
  fotogramma in 0,5-0,65 s. Una schermata che Chromium non consegna sotto carico si riprova
  invece di far fallire l'export.

### Migliorato
- **Riesportare rifa' solo quello che è cambiato.** I pezzi del render si conservano in
  `~/.vedit/pezzi`, con una chiave fatta dal comando ffmpeg e dai file che leggono: correggi
  un taglio e riesporti, e si ricalcolano solo i pezzi che quel taglio tocca. Sul videoclip
  vero, 40 s di timeline: 124 s il primo export, 2,9 s il secondo, 12,7 s dopo aver cambiato
  una clip, con un file identico bit per bit. Tetto di 4 GB (`VEDIT_CACHE_PEZZI_MB`, `0` la
  spegne), i pezzi usati meno di recente vanno via per primi; `clear_cache` la svuota.
- **Vortice e rigonfiamento circa 7 volte più veloci quando si smorzano.** Un `warp` a
  keyframe che arriva e torna a zero in qualche decimo di secondo pagava l'espressione su
  tutta la mappa per l'intera clip: ora, con `amount` a zero, la mappa restituisce subito
  la coordinata del pixel stesso, cioè nessuna distorsione. Vortice e rigonfiamento usano
  inoltre una mappa 8 volte più piccola a 1080p (stesso errore della 4x, metà del costo),
  proporzionata alla risoluzione; l'increspatura resta a 4x. Su un videoclip vero di
  2'17" con 9 warp ogni 8 s il tempo di render è sceso del 30% (da 28 s a 19,5 s per 8 s di
  video).

## v0.1.3 — 2026-10-11 · Effetti speciali, stili creati dall'agente, export veloce

### Nuovo
- **Export molto più veloce sulle timeline lunghe.** Un progetto di 2 minuti con 370 tagli
  si esportava a 1/69 del tempo reale (circa 1 ora e 45). Il grafo unico teneva aperte tutte
  le clip per tutta la durata, con un costo che cresce col quadrato dei tagli. Ora sopra i
  20 s il render va a pezzi di circa 4 s, tagliati sugli stacchi e mai dentro clip con effetti
  temporali; i pezzi girano in parallelo (`jobs`, `VEDIT_RENDER_JOBS`), l'audio si fa in un
  passaggio solo e tutto si incolla senza ricodificare. Gli effetti del master nei pezzi
  vedono il tempo vero della timeline.
- **Il render non si mangia più la RAM.** Un pezzo a 1080p con effetti pesanti arriva a 2 GB
  (cresce con le clip che contiene): ora un pezzo parte solo se la sua stima ci sta nella
  memoria libera, e con poca RAM i pezzi vanno in fila. Gli zoom animati che scendono sotto 1
  usano `scale` per fotogramma invece di una tela 4x (fino a 7680x4320) per `zoompan`, e non
  sono più limitati a 0,25.
- **`warp` e `glitch` 4-11 volte più veloci**: l'espressione si calcola su una mappa ridotta
  e si applica con `displace`/`remap` invece di `geq` su ogni pixel. L'immagine resta la
  stessa a meno di mezzo pixel.
- **L'agente crea gli stili da solo** (`create_style`, `delete_style`, anche nella chat).
  Prima uno stile personale si poteva scrivere solo a mano dalla UI, e la sua ricetta era
  per forza quella del ritmo di base. Ora l'agente salva guida e ricetta (look, movimento,
  zoom, transizioni, dissolvenze, curva della musica, accenti, attese di `review_edit`):
  le voci non nominate vengono dal ritmo di base, i valori sbagliati sono rifiutati con
  l'elenco di quelli ammessi. Lo stile compare nel menu della chat (che ora si ricarica a
  ogni apertura) e `apply_style` lo esegue. `list_styles` mostra anche gli stili di
  montaggio con le loro ricette e i look ammessi. Salvare dalla UI non cancella la ricetta.
- **Gli stili montano davvero** (`apply_style`, anche nella chat). Uno stile era solo testo
  per il modello, che metteva le clip in fila e si fermava: montaggi di soli tagli secchi
  anche con lo stile scelto. Ora ogni stile ha una ricetta (`stili.RICETTE`): look sul
  master, spinte o punch-in a keyframe, transizioni ai cambi di sezione, dissolvenze
  d'apertura e chiusura, accenti (shake, glitch) e curva del volume della musica (arco,
  crescendo, sotto la voce). Un gesto solo, un undo solo, e non tocca quello che è già
  deciso. Gli stili personali prendono la ricetta del ritmo scelto, senza look. Restituisce
  anche `da_fare`: testi, grafica e momenti forti, la parte che dipende dal contenuto.
- **`review_edit`**: dice se il montaggio è fatto o solo tagliato, senza render. Conta
  movimento, colore, transizioni, grafica, musica automatizzata e varietà delle durate, e
  per ogni mancanza dice con quale strumento rimediare; con `style` giudica rispetto allo
  stile. `verify_edit` lo include in `montaggio`, `plan_edit apply=True` ricorda che la
  timeline ha solo tagli.
- **`preview_media`**: fotogrammi di un media importato (griglia o fotogramma singolo)
  **senza metterlo in timeline**. Prima l'agente poteva guardare solo la timeline e doveva
  montare il materiale per vederlo. `guide=True` disegna una griglia al 10% per leggere le
  coordinate di un oggetto.
- **Tracking di un oggetto qualsiasi**: `track_mask` e `pin_to_subject` accettano
  `box=[x, y, w, h]` (frazioni del fotogramma o pixel) e seguono l'oggetto indicato invece
  di una classe YOLO — un logo, un pallone, un attrezzo. `vision.track_box` è
  correlazione normalizzata in numpy (FFT + immagini integrali), avanti e indietro dal
  fotogramma indicato, senza extra.
- **Evidenziare**: nuovi effetti `mask_outline` (cornice colorata), `mask_spotlight`
  (scurisce e desatura tutto tranne il riquadro) e `tint` (porta l'immagine verso un colore
  tenendo luci e ombre); `track_mask` li fa seguire al soggetto, con `params` per colore e
  intensità. **`highlight_subject`** (extra `vision`) evidenzia con la sagoma vera: duplica
  la clip su una traccia sopra, muta e scontornata, e la mette in glow, tint o spotlight.
- **Modalità di fusione per clip** (`Clip.blend`, `set_clip(blend=...)`, menu *fusione* nelle
  proprietà): normal, screen, add, multiply, overlay, softlight, hardlight, darken, lighten,
  difference, exclusion, dodge, burn. `graph._blend` posa la clip su un canvas trasparente,
  fonde l'immagine intera con la base e la rimette sopra con l'alpha della clip: posizione,
  opacità, dissolvenze e transizioni restano quelle di sempre. Nell'anteprima diretta diventa
  `mix-blend-mode`.
- **Nuovi effetti video**: `glitch` (raffiche ripetibili con `seed`), `rgb_split`
  (aberrazione cromatica), `warp` (wave, ripple, swirl, bulge; `amount` animabile), `lens`
  (fisheye/cuscino), `shake` (tremolio che non scopre i bordi), `tilt3d` (rotazione 3D con
  prospettiva vera, yaw e pitch animabili), `sky_key` (toglie il cielo sopra l'orizzonte),
  `remove_object` (cancella un rettangolo animabile ricostruendolo dai bordi), `matte`.
- **`remove_background`** (MCP, extra `vision`): scontorno senza green screen. YOLO-seg
  segmenta ogni fotogramma del tratto usato, la maschera finisce in cache
  (`~/.vedit/mattes`) e l'effetto `matte` la fonde come alpha, allineata dal grafo a
  attacco, velocità, reverse e inquadratura della clip. `invert` tiene lo sfondo e toglie
  il soggetto.
- **`pin_to_subject`** (MCP, extra `vision`): motion tracking, aggancia una clip a un
  soggetto che si muove (`Store.pin_to_subject`).
- **`add_particles`** (MCP, menu *particelle* nella barra): neve, pioggia, scintille,
  coriandoli, pulviscolo, bokeh, stelle, lucciole come clip html deterministica
  (`particelle.py`).
- `Ctx.offset`: il tempo della clip al primo fotogramma, per i filtri che contano i
  fotogrammi invece di leggere `t` (`perspective`).

### Correzioni
- `warp` e `glitch` funzionano anche con ffmpeg piu' vecchi del 7.1 (quello di Ubuntu 24.04):
  `scale2ref` ha cambiato il significato di `iw`/`ih`, e la misura della mappa ora si sceglie
  provando cosa capisce l'ffmpeg installato.
- **Render che si bloccava a caso per sempre.** Con una musica lunga sotto tante clip brevi,
  `amix` di ffmpeg 8 restava fermo a consumare un core in circa un render su dieci (riprodotto
  con ffmpeg da solo: 5 blocchi su 40). Ora ogni ramo audio dura quanto il progetto, col
  silenzio in coda (`apad`): 0 blocchi su 90. Ogni ingresso apre solo il flusso che gli serve
  (`-an` per il video, `-vn` per l'audio).
- **Clip HTML fotografate in parallelo**, un browser per clip entro la memoria libera: 2,6
  volte più in fretta sulle grafiche non ancora in cache.
- **`track_mask` metteva la maschera nel posto sbagliato se la sorgente non aveva la
  risoluzione del progetto**: le coordinate erano in pixel della sorgente, ma gli effetti
  lavorano dopo l'adattamento al canvas. Un 4K in un progetto 1080p aveva la maschera al
  doppio della distanza dall'angolo. Ora passano per `vision.to_canvas` (contain, cover,
  stretch, none).
- Il prompt della chat diceva "non aggiungere effetti o titoli non chiesti" anche quando si
  chiedeva di montare un video: ora vale per le modifiche puntuali, e per "fammi il video"
  chiede `apply_style` e `review_edit`. Stessa indicazione all'assistente Claude Code.
- **Una trascrizione poteva chiudere l'intero editor.** Su GPU faster-whisper passa da
  ctranslate2 e cuDNN, codice nativo: con librerie cuDNN non allineate (`Could not load
  symbol cudnnGetLibConfig. Error code 127`) il processo muore senza eccezione Python, e
  dentro `vedit ui` o il server MCP si portava via tutto. Ora la trascrizione gira in un
  processo figlio (`analyze._asr_isolata`): se cade sulla GPU si rifà su CPU, il risultato
  porta un `avviso`, e per il resto della sessione non si riprova la GPU.
  `VEDIT_ASR_DEVICE=cpu` salta la GPU fin dall'inizio.
- Niente più traceback `ConnectionResetError [WinError 10054]` nel terminale di `vedit ui`
  quando il browser chiude una connessione: su Windows era rumore di asyncio, non un errore.
- `set_clip` da MCP falliva sempre se non si passava `fit`: il `None` veniva validato come
  un adattamento sconosciuto.
- `track_mask` metteva i keyframe nel tempo della *sorgente*: su una clip con attacco
  diverso da zero la maschera arrivava in ritardo. Ora sono nel tempo della clip.

## v0.1.2 — 2026-10-09 · UX: effetti, titoli, davanti/dietro, stili personali

### Correzioni
- **Gli effetti (video e audio) non si applicavano al clic** nel pannello proprietà. Il
  catalogo era un componente dichiarato dentro un altro: a ogni ridisegno React buttava via
  e ricreava tutti i riquadri, e il passaggio del mouse (che accende l'anteprima) bastava
  perché il riquadro premuto non fosse più quello rilasciato. Ora il clic arriva sempre;
  l'effetto aggiunto viene portato in vista ed evidenziato, così si vede subito dove
  regolarlo. Nuovo test `frontend/fxclick.mjs` che ripete il gesto (fallisce sul codice
  vecchio).
- **Un titolo aggiunto non si vedeva nel video**: `add_text` (e `add_html`) senza traccia
  andavano sulla *prima* traccia video, cioè quella in fondo, sotto qualunque ripresa delle
  tracce sopra. Ora vanno sulla traccia video più in alto (non bloccata).
- **L'anteprima "diretta" mostrava un ordine dei livelli diverso dal render**: ordinava
  tutte le clip insieme, così un titolo coperto nel file finale qui si vedeva. Ora impila
  traccia per traccia come `graph.build_video`.
- `index.html` servito con `Cache-Control: no-cache`: dopo un aggiornamento il browser
  teneva l'interfaccia vecchia e le correzioni sembravano non funzionare.
- Gli effetti senza icona propria hanno un'icona generica invece di un riquadro vuoto.

### Davanti / dietro
- Le testate delle tracce video dicono quale sta **davanti** e quale **dietro**; le frecce
  si chiamano "porta avanti" / "manda dietro".
- Nuovo gruppo *davanti / dietro* nelle proprietà della clip: su che livello sta, quali
  clip sopra di lei nello stesso momento possono coprirla, e i pulsanti per spostarla.
- Nuova operazione `Store.move_layer(clip_id, direction)` (`up` / `down` / `top` /
  `bottom`): se la traccia di arrivo è occupata in quel tratto ne inserisce una nuova lì,
  così le clip non finiscono sovrapposte. Un solo passo di undo.

### Stili di montaggio personali
- Nel menu *stile* della chat: **crea il tuo stile** con nome, descrizione e istruzioni
  libere per l'assistente (arrivano al modello a ogni messaggio, come un prompt di sistema)
  più il ritmo di base per `plan_edit`. Si modificano ed eliminano dallo stesso menu.
- Salvati in `~/.vedit/stili.json`, accanto a `llm.json`: sono una preferenza di chi
  monta, non del progetto. API: `GET/POST /api/stili`, `DELETE /api/stili/{id}`.

## v0.1.1 — 2026-10-09 · README leggibile su PyPI

### Vetrina (GitHub, PyPI, motori di ricerca)
- **Logo, GIF e link del README rotti sulla pagina PyPI**: il README è anche la descrizione
  del pacchetto, ma usava percorsi relativi (`docs/logo/logo.png`, `docs/vedit-promo.gif`,
  `AGENTS.md`, `LICENSE`…) che PyPI non risolve. Ora puntano a `raw.githubusercontent.com` e
  a `github.com/.../blob/main`: funzionano su GitHub e su PyPI. Si vede su PyPI da
  questa versione.
- Il conteggio degli strumenti MCP diceva 77, sono 83: corretto in README, README.it e
  descrizione della repo su GitHub.
- Parole chiave del pacchetto: aggiunte `ai-video-editor`, `claude-code`, `cursor`, `llm`,
  `subtitles`, `agentic-ai`.
- Verificata l'installazione da utente esterno con cache vuota: `uvx vedit-mcp`,
  `vedit doctor`, `vedit ui` (interfaccia servita dal pacchetto) e un render
  `new -> import -> add -> render` andato a buon fine.

## v0.1.0 — 2026-10-08 · prima pubblicazione su PyPI

### Pubblicazione
- **Il pacchetto `vedit-mcp` non era mai stato pubblicato**: su PyPI il nome non esisteva
  (404), quindi `uvx vedit-mcp` e `uvx --from vedit-mcp vedit ui` fallivano per chiunque
  installasse senza clonare la repo (errore `vedit-mcp was not found in the package registry`).
- Creato l'environment `pypi` su GitHub. Il workflow `release.yml`, a ogni tag `v*`, esegue
  i test, costruisce il pacchetto con l'interfaccia dentro e lo carica su PyPI tramite
  pubblicazione fidata (Trusted Publisher).
- Primo tentativo col tag `v0.1.0` fermato dai test in CI, per i due difetti qui sotto:
  niente è stato pubblicato. Tag ricreato sul commit corretto (`0c6e193`).
- Secondo tentativo: test e build passati, caricamento rifiutato (`invalid-publisher`)
  perché su pypi.org mancava il publisher. Registrato il pending publisher (`vedit-mcp`,
  owner `metiutek`, repo `editorvideo-ai`, workflow `release.yml`, environment `pypi`) e
  rilanciato il solo caricamento.
- **Pubblicato**: https://pypi.org/project/vedit-mcp/ . Provato da zero con
  `uv tool install vedit-mcp`: installa `vedit` e `vedit-mcp`, l'interfaccia web è nel
  pacchetto, `vedit doctor` risponde.
- La repo si è spostata da `metiu1/editorvideo-ai` a `metiutek/editorvideo-ai`: aggiornati
  `origin`, i link in README, `pyproject.toml`, `CONTRIBUTING.md`, `collegamenti.py` e
  l'owner indicato in `release.yml`.

### Errori leggibili dall'agente con mcp 2.3+
- Da `mcp` 2.3 un'eccezione che non è `ToolError` viene trattata come crash: all'agente
  arrivava solo `Error executing tool add_clip`, senza il motivo ("clip inesistente",
  "nessun progetto aperto"…). Chi installa da PyPI riceve proprio l'ultima versione di mcp.
- Gli strumenti ora si registrano con `_strumento()` in `mcp_server.py`, che trasforma gli
  errori previsti (`EditError`/`ValueError`, `KeyError`, file mancanti) in `ToolError` col
  loro testo. Verificato con mcp 2.0 e 2.3.

### Correzione al filtro degli effetti
- `natura()` leggeva `has_audio`, ma lo stato mandato all'interfaccia chiama quel campo
  `audio`: nell'app vera un video con audio perdeva il gruppo audio e gli effetti audio.
  L'ha trovato il test di montaggio `catalogo: un riquadro per effetto`.

### Documentazione
- **Installazione in 3 passi in cima al README** (inglese e italiano), subito sotto la GIF:
  1. installare uv (comando per Windows, macOS e Linux), poi riaprire il terminale;
  2. `uv tool install vedit-mcp` e `vedit install-ffmpeg`;
  3. `vedit ui`.
- Detto chiaramente che `claude mcp add` **collega** Claude Code a vedit ma non installa il
  comando `vedit`: era il punto in cui chi provava si bloccava (`vedit` non riconosciuto).
- La configurazione JSON per gli altri client ora usa `vedit-mcp` installato, non `uvx`.

### Ispettore: solo quello che la clip può usare (`2ad5472`)
- Una clip su traccia audio non mostra più correzione colore, effetti video, inquadratura,
  dissolvenze video, transizioni, posizione e scala.
- Testo, colore, html e video senza audio non mostrano più il gruppo audio e gli effetti audio.
- Un video con audio continua a mostrare tutti e due.
- Un effetto già applicato che la clip non può usare resta in lista, così si può togliere, con
  la nota "l'effetto non cambia niente".
- La stessa regola sta in `Store` (`clip_produces`, `_effect_fits`): `add_effect` e
  `add_effects` rifiutano un effetto che non cambierebbe niente, quindi vale anche per
  l'assistente in chat e per gli agenti MCP. `add_effects` resta atomico.
- Test: `natura()` in `frontend/test-util.mjs`, `test_effetti_solo_dove_cambiano_qualcosa`
  in `tests/test_core.py`. Suite veloce: 353 test passati.

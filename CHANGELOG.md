# Registro delle modifiche

Le voci più recenti stanno in cima.

## v0.4.0 — 2026-10-31 · Stile imparato da un video, skill di montaggio

### Aggiunto
- **Copiare gli errori**: l'errore di export e l'avviso in basso hanno un pulsante che li copia
  negli appunti. L'avviso resta finché ci sta sopra il puntatore, e l'errore di export si
  scorre invece di allargare il dialogo.

- **Stile imparato da un video**: nel menu stili, *learn a style from a video* prende un
  link (YouTube, TikTok, Instagram, mp4 diretto), un file o un video caricato e ne misura il
  montaggio: ritmo e accelerazioni, stacchi sul battito, dissolvenze e passaggi al nero,
  flash, zoom lenti e punch-in, scosse, colore e look, formato e bande nere, cartelli su nero,
  aperture e chiusure. Ne esce uno stile personale (guida con i numeri e ricetta per
  `apply_style`) che si apre per essere corretto. Anche da chat, da MCP (`learn_style`, con il
  foglio dei fotogrammi da guardare) e da terminale (`vedit style learn`). Lo stile porta il
  colore vero del riferimento (`colormatch` su ogni ripresa, non solo il look più vicino); il
  foglio dei fotogrammi arriva anche all'assistente della chat; da un link si scarica solo il
  tratto analizzato (`--max-seconds`, di norma 10 minuti).
- **YouTube con yt-dlp aggiornata**: l'extra `web` ora installa `yt-dlp[default]>=2026.10.26`
  (con il risolutore JavaScript) e vedit usa Node.js come runtime quando manca Deno. Con la
  yt-dlp di giugno YouTube rispondeva 403.
- **Skill di montaggio**: un modo semplice per aggiungere i propri modi di montare. Dalle
  impostazioni del modello (*editing skills*) si incolla un link GitHub, uno zip, un `.md` o
  una cartella, si carica un file o se ne scrive una al volo; da terminale `vedit skill
  add|new|list|rm`. Stanno in `~/.vedit/skills` e valgono a ogni livello d'accesso della chat,
  per Claude Code dentro l'editor e per gli agenti MCP (`list_skills`, `use_skill`,
  `create_skill`, `install_skill` con conferma, `delete_skill`). L'assistente puo' salvare da
  se' una skill quando glielo si chiede. Al livello *solo l'editor* la chat vede solo queste,
  non le altre skill di Claude Code.

### Corretto
- **Export con molta grafica html che riempiva il disco**: i blocchi fotografati stavano in
  `.mov` qtrle, 500-700 MB ogni 4 secondi a 1080p; un video di nove minuti tutto in html
  lasciava 71 GB in `~/.vedit/html` e il disco pieno. Ora sono FFV1 (sempre senza perdita,
  alpha compreso): 100-150 MB a blocco e codifica tre volte più veloce. La cache si pota anche
  prima di fotografare, così le versioni vecchie fanno posto alle nuove. La cache qtrle
  esistente non si usa più e se ne va alla prima potatura.
- **Export fermo al 93% con clip html lunghe**: l'elenco `ffconcat` dei blocchi non diceva
  la durata di ognuno, e ffmpeg, per arrivare all'attacco di un pezzo, decodificava tutti i
  blocchi prima. Un pezzo al minuto otto rileggeva otto minuti di grafica: la parte finale
  dell'export (il 10% della barra dopo la grafica) durava più della grafica stessa. Con
  `duration` per blocco il pezzo salta dritto al suo blocco: a 96 s da 60 s a 8 s, a parità
  di fotogrammi.
- **Export fallito a fine corsa con molti keyframe di volume**: un `duck_music` su nove minuti
  di voce metteva centinaia di keyframe sulla musica, compilati in una catena di `if` uno
  dentro l'altro; il parser di ffmpeg ne regge circa cento livelli e la passata audio falliva
  con "Missing ')' or too many args". Ora l'espressione è una ricerca binaria sui tratti
  (profondità log₂ n), con gli stessi valori. Le righe lunghissime del log di ffmpeg
  nell'errore si accorciano.

## v0.3.2 — 2026-10-29 · Correzione

### Corretto
- **Messaggi scritti mentre l'assistente lavora**: se il server non li accetta (turno appena
  finito, interfaccia nuova su un server avviato prima dell'aggiornamento) vanno in coda e
  partono a fine turno, invece di restare nella casella con un errore.

## v0.3.1 — 2026-10-29 · Menu "/" e messaggi durante il lavoro nella chat

### Aggiunto
- **Menu `/` nella chat**: scrivendo `/` compaiono i comandi dell'editor (`/clear`, `/stop`,
  `/model`, `/style`, `/memory`, `/settings`) e le skill dell'utente, con frecce, Tab e Invio.
  `/skill argomenti` arriva al modello come richiesta esplicita di usare quella skill
  (`chat.comando_skill`): Claude Code non riconosceva il comando, che nel prompt non sta in
  testa, e i modelli via API non conoscono la sintassi. Le skill compaiono con l'accesso
  "Editor + my skills" o completo.
- **Scrivere mentre l'assistente lavora**: Invio manda il messaggio al turno in corso
  (`/api/chat/posta`), che il modello legge col risultato del prossimo strumento — sia via API
  (`run_op`) sia con Claude Code (strumenti del server MCP dell'editor,
  `api.consegna_posta`). Alt+Invio, o un messaggio con riferimenti, lo mette **in coda** e
  parte come turno nuovo a fine lavoro; la coda si modifica e si svuota dalla chat. Quello che
  il modello non fa in tempo a leggere torna in coda da solo.

## v0.3.0 — 2026-10-22 · Video raccontati da una voce, chat per progetto, modello e sforzo

### Aggiunto
- **`speech_times`** (MCP e chat): in che secondo della timeline la voce dice ogni frase del
  copione, con posizione, attacco e velocita' delle clip; ricerca nell'ordine del copione
  (una frase ripetuta prende l'occorrenza giusta) e numeri confrontati in lettere. Senza
  faster-whisper, stima dal testo delle battute di `generate_voice`.
- **Metodo per i video raccontati da una voce** nelle istruzioni dell'agente MCP e
  dell'assistente: fonti, copione per la voce, voce prima, tempi misurati, una scena html per
  capitolo con metafore animate, controlli ripetuti sui fotogrammi, suono. Nasce dal
  confronto fra uno short venuto male nell'editor e uno fatto bene a mano.
- **Voce di Google Gemini** (`gemini` in `generate_voice`): ritmo e tono chiesti a parole
  nello `style`.
- **Ogni progetto ha la sua chat**, salvata in `<progetto>.chat.json` e ripresa quando lo si
  riapre (sessione di Claude Code, cronologia dei modelli via API, oppure la conversazione
  come testo se il modello e' cambiato).
- **Modello e sforzo in un clic** dalla pastiglia in cima alla chat; Claude Code parte con
  `--effort`, Claude via API con `output_config.effort`. Fra i modelli di Claude Code c'e'
  anche `fable`.

### Corretto
- `apply_style` abbassava la voce fuori campo come fosse musica (-16 dB).
- Cambiare modello o livello d'accesso cancellava la conversazione.
- L'assistente con i modelli via API si fermava dopo 16 giri: un video intero ne vuole di
  piu' (ora 80).

## v0.2.0 — 2026-10-22 · Voce, web, pubblicazione, memoria, skill e server MCP

### Aggiunto
- **Skill, server MCP, plugin e browser dell'utente nell'assistente**: tre livelli di
  accesso nelle impostazioni del modello (solo editor / editor + skill e server MCP /
  accesso completo). Con Claude Code: configurazione dell'utente caricata, `--chrome`, skill,
  modalita' `auto` per le azioni (o nessun permesso nel livello completo). Con i modelli via
  API: client MCP verso i server di Claude Code, Claude Desktop e `~/.vedit/mcp.json`, piu'
  le skill come `use_skill`. Ogni server si spegne da solo.
- **Il web per il modello, senza siti fissi**: `web_search` (pagine, immagini, video,
  notizie), `web_read` (testo, immagini e video di una pagina), `web_download` (qualunque
  file, e le pagine video con yt-dlp, importati nel bin nella cartella `web`), da MCP e dalla
  chat; Claude Code nella chat ha anche la sua ricerca web. Scheda *web* nel pannello
  sinistro. Motore senza chiave (DuckDuckGo, Bing per le immagini) o Brave, Tavily, SearXNG.
  Fonte di ogni file in `FONTI.md`; indirizzi locali e privati rifiutati anche dopo un
  redirect. Nuovo extra `web` (yt-dlp); `certifi` dichiarato per i Windows con certificati
  di sistema vecchi.
- **Voce dal testo (TTS)**: `generate_voice` da MCP e dalla chat, pulsante *voice* nella UI.
  Motori OpenAI e compatibili (anche server locali come Kokoro-FastAPI), ElevenLabs, Piper
  offline e voce di sistema senza installare niente. Le battute vanno sulla traccia `VO` in un
  solo undo (`Store.add_voiceover`); stessa battuta, stesso file, niente seconda chiamata.
- **Pubblicare sui social**: pulsante *publish* e `publish_video`. YouTube con login OAuth e
  caricamento a riprese (parte privato), TikTok come bozza nella casella. Sempre con conferma
  dell'utente. Solo libreria standard.
- **Memoria fra i progetti** in `~/.vedit/MEMORIA.md`: `remember`, `forget`, `memory`;
  `project_create`/`project_open` la restituiscono, la chat la passa al modello, la UI la
  mostra e la fa modificare (segnalibro nella scheda assistente).
- **Formati per rapporto d'aspetto: 16:9, 9:16, 1:1, 4:5, 4:3, 3:4, 21:9, 2:3** (o `WxH`),
  con la qualita' come lato corto (720, 1080, 1440, 4K). Nella UI il nuovo progetto ha i
  riquadri dei formati, la qualita' e gli fps; a progetto aperto il pulsante del formato
  nella barra in alto (e la voce *format* nelle proprieta' del progetto) lo cambia senza
  toccare la timeline, con *fill* che fa riempire il nuovo fotogramma alle clip invece di
  lasciare le bande. `Store.set_format`, `project_settings(format, size, fill)` e
  `project_create(preset="9:16", size=...)` da MCP, `set_format` nella chat,
  `vedit new --preset 4:5 --size 1080` e `vedit format progetto.json 9:16 --fill` da CLI.

### Corretto
- **Export con grafica HTML da ore a minuti.** Un progetto di nove minuti fatto di clip html
  costava circa 2,5 ore di export a qualunque qualita': tutto il tempo era Chromium che
  fotografava, il render vero dopo era di secondi. Ora la cattura passa da CDP
  (`optimizeForSpeed`, sfondo trasparente impostato una volta: meta' del tempo per
  fotogramma), i blocchi di 4 s di *tutte* le clip si dividono tra piu' browser (anche una
  clip lunga sola, prima un browser per clip), e la stima di memoria per browser e' quella
  misurata (115 MB, presi 250) invece di 500 MB, che su un PC con un paio di giga liberi
  lasciava un browser solo. Su 8 s di grafica a 1080p: da 137 s a 21 s.
- **La barra dell'export si muove mentre si fotografa la grafica**: prima restava a 0% per
  tutto il tempo del browser e l'export sembrava bloccato. La UI e la CLI dicono a che
  fotogramma della grafica si e' arrivati.

## v0.1.4 — 2026-10-15 · Montaggio MCP con molti meno token, interfaccia in inglese, mixer

### Aggiunto
- **Montare via MCP costa molti meno token.** Una sessione reale (due minuti di video, 402 giri,
  contesto medio 248k token) aveva esaurito un abbonamento Pro: il costo e' giri per lunghezza
  del contesto. Ora le risposte di tutti gli strumenti escono una volta sola in JSON compatto
  (prima `indent=2` piu' `structuredContent`), senza eco di cio' che l'agente ha appena
  passato (`add_clips` restituisce gli id, `set_transform`/`set_audio` riassumono i keyframe),
  e `project_info` lascia fuori percorsi e campi ai valori di default (`track=` per una
  traccia sola). Nuovo strumento **`batch`**: molte modifiche in una chiamata, atomiche e con
  un solo undo. `transcribe(media=["*"])` trascrive tutto il girato in una chiamata, con i
  segmenti come `[inizio, fine, testo]`; `preview_media(media=["*"])` mostra tutte le riprese
  in un foglio solo. `list_effects` e' compatto (`name=` per la scheda completa),
  `music_beats` da' il profilo come lista di numeri. Le istruzioni del server hanno una
  sezione *ECONOMIA*.
- **Meno giri per guardare e per la grafica.** `preview_frame(t=[...])` mette fino a 16
  istanti in un'immagine sola, `batch(look=[...])` modifica e restituisce i fotogrammi nello
  stesso giro. `add_html`/`set_html` accettano `vars`: un file modello con segnaposto
  `{{nome}}` per tanti cartelli diversi, invece di un documento intero per ognuno.
  `add_clips` crea da sola le tracce `V<n>`/`A<n>` che nomina. `list_styles` non porta piu'
  le guide degli stili personali (fino a 20.000 caratteri l'una: `list_styles(style=id)`), e
  `project_info` riassume i keyframe come `kf xN` (`detail='full'` li da' per intero).

- **Niente piu' strumenti troncati a 300 secondi.** Claude Code interrompe una chiamata MCP
  muta per cinque minuti: render, trascrizioni di tutto il girato e verifiche lunghe
  ripartivano da capo (sette render persi nelle sessioni registrate). Ora ogni lavoro lungo
  manda un battito di progresso ogni 15 s (`mcp_server._off`), con la percentuale vera per
  il render e il file in corso per `transcribe`.
- **Schemi degli strumenti piu' corti del 28%.** Tolti `title`, `anyOf` con `null` e
  `default: null` che pydantic ripete su ogni parametro, e l'indentazione delle descrizioni
  (`mcp_server._snello`): gli argomenti accettati sono gli stessi.
- **`duck_music` su tracce intere** (`music="A2", voice="V1"`): tutta la musica sotto tutto il
  parlato in una chiamata e un undo, invece di calcolare l'automazione a mano clip per clip.
- **`preview_grid` su un video**: se `path` e' un file video (di solito il render appena
  fatto) ne mostra i fotogrammi invece di fallire.

### Corretto
- **Fotogrammi neri in anteprima a fine clip.** `preview_frame` sugli ultimi due fotogrammi di
  una clip html, o a meta' dell'ultimo fotogramma di qualunque clip, dava nero: l'agente
  vedeva un lampo che nel render non c'e' e provava a correggerlo. L'istante va all'inizio
  del suo fotogramma (`render.render_frame`) e la grafica html salta a confine di
  fotogramma (`graph`).
- **Spot di sola grafica html.** `apply_style` falliva con "no video clips" e `review_edit`
  chiedeva movimento e colore che non si potevano dare: senza riprese la grafica html e' il
  materiale principale.
- **`make_captions` su piu' clip.** Senza `output` ogni clip scriveva lo stesso file e tutte
  mostravano i sottotitoli dell'ultima; ora ogni clip ha il suo file accanto al progetto
  (`<progetto>_sottotitoli/<clip>.ass`) e restano solo le righe del tratto montato.
  `clips=[...]` le sottotitola tutte in una chiamata.
- **Chat più leggera sul contesto.** La guida dello stile e lo stato del progetto entrano nella
  conversazione solo la prima volta e quando cambiano, invece di ripetersi a ogni messaggio.
  Col motore Anthropic, sistema, strumenti e cronologia passano dalla cache dei prompt
  (`cache_control`): l'API resta senza stato, ma il prefisso già visto costa un decimo.
- **Interfaccia in inglese.** Tutti i testi della UI, i messaggi di errore che arrivano a
  schermo e dagli strumenti MCP, e i cataloghi (effetti, look, catene audio, transizioni,
  stili integrati, particelle, impostazioni del modello) sono in inglese. Codice e commenti
  restano in italiano; l'assistente risponde nella lingua in cui gli si scrive. La conferma
  dell'export accetta sia "Yes" sia "Si'".
- **Istruzioni di stile fino a 20.000 caratteri** (prima 4.000): una guida di montaggio
  dettagliata ci sta. L'editor dello stile mostra quanti caratteri restano.
- **Mixer e audio 5.1.** Nuova scheda *mixer*: un canale per traccia che suona e il master,
  con fader in dB (doppio clic: 0 dB), muto/solo e misuratori di picco, RMS e tenuta del
  picco. I livelli li misura il server renderizzando ogni traccia da sola, con effetti e fader
  ma senza la catena del master (`review.livelli`, `GET /api/mixer/levels`, in cache per
  revisione): sono quelli che usciranno nel file, e si leggono anche a riproduzione ferma. Il
  volume del master ora si cambia (`Store.set_master_volume`, `project_settings(master_volume)`).
  Progetti **5.1** (`Settings.audio_layout`): ogni traccia va dove dice `Track.surround`
  (davanti, centro, dietro, tutto, LFE con passa-basso a 120 Hz), il mix e il loudnorm restano
  a sei canali, il file esce 5.1 in AAC (bitrate doppio), Opus, PCM; un `.mp3` ripiega in
  stereo.
- **Sottotitoli: import e traccia nel file.** Un `.srt`, `.vtt` o `.ass` (scelto o trascinato
  in *importa*, `import_subtitles`) diventa una traccia *sottotitoli* di clip di testo
  modificabili, in basso su riquadro, in un solo passo di undo (`captions.leggi`,
  `Store.import_subtitles`). All'export la traccia esce impressa oppure come traccia di
  sottotitoli del file, con la lingua: `mov_text` in .mp4/.mov, SRT in .mkv, WebVTT in .webm,
  con video e audio non ricodificati e i tempi riportati al tratto esportato
  (`RenderOptions.subtitle_track`, `render_video(subtitle_track=...)`). In quel caso la traccia
  non si imprime. *salva .srt* / `export_subtitles` la scrivono come file.
- **Timeline per e da altri montaggi: FCPXML, OTIO, EDL.** Nuovo `interscambio.py`. Export
  dal dialogo *esporta*, da `export_timeline` e da `vedit export-timeline`: FCPXML 1.9 e OTIO
  con tutte le tracce e i percorsi dei file, EDL CMX3600 per una traccia. Escono tagli,
  posizioni, velocità (non in FCPXML) e dissolvenze: la sovrapposizione di vedit diventa un
  taglio a metà con la transizione sopra. Gli avvisi elencano cosa resta a vedit (effetti,
  testi, grafica, movimento). Import scegliendo o trascinando il file in *importa*, da
  `import_timeline` e da `vedit import-timeline`: la timeline si accoda, le tracce si creano,
  le dissolvenze tornano sovrapposizioni, tutto in un `batch` (un undo; se manca un file non
  entra niente). L'EDL ritrova i file per nome. Andata e ritorno verificati anche con la
  libreria ufficiale OpenTimelineIO.
- **Trim da montatore: ripple, roll, slip, slide, e J/K/L.** In `Store` (`ripple_trim`,
  `roll_edit`, `slip_clip`, `slide_clip`), che tengono conto di velocità, reverse e lunghezza
  della sorgente, portano con sé le clip collegate e, se un passo è impossibile, non lasciano
  niente a metà (un solo passo di undo). In timeline con i modificatori del trascinamento
  (Maiusc/Ctrl su bordi e clip) e da tastiera: Q/W ripple fino alla testina, `,` `.` slip,
  Ctrl+frecce slide, J/K/L. Per l'agente `trim_edit(mode=ripple|roll|slip|slide)`, nella chat
  i quattro strumenti.
- **Scope grafici.** Nuova scheda *scope* nel pannello di destra: waveform della luminanza in
  IRE, parade RGB, vettorscopio, istogramma R/G/B e luma su scala logaritmica, del
  fotogramma sotto la testina. Si aggiornano a riproduzione ferma e sono misurati sugli
  originali, non sui proxy (`review.scope_immagine`, `GET /api/scope`). Per l'agente,
  `scope_image` accanto ai numeri di `color_scopes`.
- **Export ProRes e DNxHR, anche in MXF.** Nel dialogo *esporta*, da `render_video` e da
  `vedit render --codec`: `prores` e `dnxhr` in `.mov`, `.mxf` o `.mkv`, con audio PCM
  24 bit a 48 kHz. La qualità sceglie il profilo (ProRes Proxy/422/HQ/4444, DNxHR
  LB/SQ/HQ/HQX 10 bit). Sono i file per passare il lavoro a Premiere, Resolve, Avid o Final
  Cut. Un `.mxf` impone DNxHR come `.webm` impone VP9; codec e contenitore incompatibili
  (`prores` in `.mp4`) vengono rifiutati prima di partire (`render.controlla_codec`). Anche
  il render a pezzi paralleli li incolla senza ricodifica.
- **Firma nell'editor.** In fondo al pannello di sinistra c'è *made by metiu.xyz*, con il
  link al sito; la stessa riga chiude `README.md` e `README.it.md`.
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
- **Export `.mp3`.** Come per il `.webm`, prendeva l'AAC predefinito e ffmpeg rifiutava il
  file: ora ogni contenitore che accetta solo certi codec audio usa il suo.
- **Export `.webm` con audio.** Prendeva l'AAC predefinito, che WebM non accetta, e ffmpeg
  falliva: ora l'audio di un `.webm` è Opus.
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

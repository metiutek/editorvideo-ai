# Registro delle modifiche

Le voci più recenti stanno in cima.

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

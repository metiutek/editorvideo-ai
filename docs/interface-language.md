# English and Simplified Chinese

Choose **English / 中文** beside the vedit logo. The selector is also available in dialog headers, so you can switch while editing a form. The choice is saved locally in this browser as `vedit.language`; reloading restores it. The default remains English. Refresh an already-open editor after rebuilding/updating to load the new interface.

The language applies across the editor: toolbar, media library, timeline, keyframes, effects and graphics catalogs, project/import/export dialogs, audio and particles, assistant/model/access settings, collections, voice generation, publishing, web search and the activity recap form. The local Chinese dictionary contains **1,624 entries**, including built-in effect/graphic descriptions and parameter/enum labels. Common application progress/errors are translated as well.

This is interface localization, not translation of video subtitles or of your content. Project/activity/track names, source paths, filenames, input text, AI responses and personal skill/style descriptions remain as entered. API identifiers and option values stay English; for example, **均衡** is still submitted as `balanced` and **填满（裁切）** as `cover`. Model names, product brands, technical codes, arbitrary third-party plugin metadata and unrecognized diagnostic messages may remain in their original language. No text is sent to an external translation service, and language selection does not change the project or incur model fees. Native operating-system file dialogs follow the operating system/browser language.

## Implementation

`frontend/localize.cjs` is a Babel plugin run by the existing Vite React plugin, with no new dependency. It wraps visible static JSX copy and presentation attributes in the local `translate` function at build time. It leaves API calls, identifiers, CSS classes, input values and expressions containing user content alone. Source strings stay English, consistent with repository conventions; Chinese copy is in `frontend/src/locales/zh-CN.json`. Literal code examples and diagnostic blocks are excluded. Dynamic built-in labels use explicit `translateLabel` calls; known status/error messages use `translateMessage` with opaque interpolated names/paths. Unknown strings fall back to their original text.

`useLanguage` subscribes through React's external-store hook, rerendering existing component instances without changing component keys or reopening the project. Timeline JSX memoization includes the language dependency. Every option has an explicit stable value independent of its translated label. The document language is updated for accessibility, and changes are shared with other tabs of the same browser origin.

## Verification

- `frontend/test-i18n.mjs` checks all visible static JSX strings have dictionary entries, placeholder parity, persisted language, English fallback, interpolation without translating user values, stable option values and unchanged API arguments.
- `frontend/smoke.mjs` switches the mounted editor both ways, including memoized timeline controls, the recap form and a live dialog. Activity names, unsaved form values and paths remain intact; language switching sends no editing operation. Existing editing/graphics/keyframe interactions continue to pass.
- `tests/test_ui_translations.py` checks the real built-in effects, presets, graphics, parameters and provider catalogs against the Chinese dictionary.
- Production build and all frontend test scripts passed. The backend fast suite completed with **929 passed, 1 skipped, 1 failed, 214 deselected**; the additional catalog-coverage test added after collection passed separately. The sole failure is the already-reproduced baseline `test_scale2ref_porta_alla_misura_del_riferimento` FFmpeg issue documented in the recap PR.
- In a real browser on Windows, verified Chinese/English switching, restoration after reload, localized timeline controls and effect labels, and the recap pace retaining value `balanced` while displaying **均衡**. macOS/Linux browser layout was not checked.

When adding static UI copy, add its Chinese entry; the coverage test reports missing keys. Add translated backend catalog labels/descriptions when those definitions change. Preserve original option values and never pass arbitrary user/assistant content through translation helpers.

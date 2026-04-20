## Plan: Minimal Theme Model and Settings Visibility

Reduce the theme system to three primary palette colors plus two explicit state colors: `bg`, `text`, `accent`, with selectable `success` and `danger`. Derive `panel`, `panel_hv`, `border`, and `muted` from `bg` using hue/saturation/luma shifts. Expose each editable color with a paired shift slider in Settings, and make the settings button use the resolved derived theme so it stays visible.

**Steps**
1. Phase 1 - Theme contract and derivation rules
1. Define the stored palette contract as `bg`, `text`, `accent`, `success`, and `danger`.
2. Define derived neutral tokens from `bg`: `panel`, `panel_hv`, `border`, and `muted`. Keep `fg_dim` derived from `text`.
3. Define per-derived-token shift settings with hue, saturation, and luma adjustments. Use directional luma logic: if source luma is above 50%, apply the configured luma shift downward; if below 50%, apply it upward.
4. Map resolved runtime tokens back to the existing TCSS variables: `$c-bg`, `$c-panel`, `$c-panel-hv`, `$c-border`, `$c-accent`, `$c-muted`, `$c-fg`, `$c-fg-dim`, `$c-danger`, `$c-success`.
5. Create `palettes.json` with several harmonic presets containing only the five stored colors and the default shift settings.

1. Phase 2 - Persistence and theme resolution pipeline (*depends on Phase 1*)
1. Extend prefs to store `palette_name`, base color overrides, and shift override values.
2. Add palette loading with validation and safe fallback if `palettes.json` is missing or corrupt.
3. Resolve the active theme as preset base colors + user base-color overrides + user shift overrides, then compute all derived tokens.
4. Apply the resolved theme on startup and immediately after Settings save.

1. Phase 3 - Settings UI model (*depends on Phase 2 contract; UI wiring can proceed once field names are fixed*)
1. Add a Theme section with palette selection.
2. For each editable base color (`bg`, `text`, `accent`, `success`, `danger`), add a color input.
3. For each derived neutral token, add a slider row for its shift amount(s), paired with the source color it derives from. At minimum this covers `panel`, `panel_hv`, `border`, and `muted`; optionally `fg_dim` if exposed.
4. Make slider semantics explicit in the UI: luma shift moves darker when the source is light and lighter when the source is dark.
5. Add reset actions for palette defaults and user overrides.
6. On Save, validate colors and numeric shift ranges, persist the values, return updated prefs, and trigger live apply.

1. Phase 4 - Settings button visibility (*parallel with Phase 3 once resolved tokens exist*)
1. Restyle `#header-bar #settings-btn` to use resolved `panel`/`border`/`text` values instead of blending into `bg`.
2. Add explicit hover and focus states using `panel_hv` and accent/border emphasis.
3. Verify the control remains visible across dark and light background palettes because the neutral tokens are derived relative to source luma.

1. Phase 5 - Validation and guardrails
1. Clamp shift slider values to safe ranges so derived colors stay usable.
2. Ignore invalid color values or corrupted shift values without crashing; fall back to preset defaults.
3. Keep old prefs files working by defaulting missing palette and shift keys.
4. Preserve unknown future prefs keys on save.

**Relevant files**
- `c:/Users/piotr/dev/converter/converter.tcss` - keep runtime token names stable; fix settings button contrast and hover/focus styling.
- `c:/Users/piotr/dev/converter/dialogs.py` - add theme settings UI for base colors plus shift sliders and save validation.
- `c:/Users/piotr/dev/converter/converter.py` - resolve derived tokens and reapply theme live on startup/save.
- `c:/Users/piotr/dev/converter/persistence.py` - store/load palette name, base color overrides, and shift settings.
- `c:/Users/piotr/dev/converter/palettes.json` - new preset source containing base colors and default shift values.

**Verification**
1. Launch with old prefs and confirm the app computes a default theme without errors.
2. Switch preset palette and confirm the theme updates immediately.
3. Change `bg` and verify `panel`, `panel_hv`, `border`, and `muted` all update from the new source color.
4. Move shift sliders with both dark and light source colors and confirm luma adjustment flips direction around the 50% threshold.
5. Change `success` and `danger` independently and confirm only those semantic states change.
6. Confirm the settings button is visible in default, hover, and focus states across multiple presets.
7. Corrupt `palettes.json` or prefs theme keys and confirm graceful fallback.

**Decisions**
- Stored base colors: `bg`, `text`, `accent`, `success`, `danger`.
- Derived from `bg`: `panel`, `panel_hv`, `border`, `muted`.
- Derived from `text`: `fg_dim`.
- Settings expose direct color selection for the five stored colors and slider-based control for derived-token shifts.
- Apply mode: immediate apply after Save.
- Included: palettes JSON, live theme apply, derived neutral system, success/danger selection, settings button visibility fix.
- Excluded: broader screen redesign or palette import/export.

**Further Considerations**
1. Store shift settings as sparse overrides against preset defaults; recommendation: yes.
2. Use HSL/HSV-style transforms consistently for derivation; recommendation: HSL-style hue/sat/luma shifts because they match the requested mental model.
3. `fg_dim` stays implicit from `text` and is not exposed as a separate slider.

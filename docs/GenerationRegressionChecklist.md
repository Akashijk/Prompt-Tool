# Generation Regression Checklist

Use this after queue/model-resolution/refactor changes.

## Core Generate Flows
- Main prompt window: `Generate Image` with 2+ models.
- Prompt variations: create variants, run, then generate LoRA permutations from a variant image.
- Prompt variations: generate seed permutations from a variant image.
- Edit & Regenerate from preview tile.
- History viewer: `Generate New`, `Regenerate`, `LoRA Variations`, `Seed Variations`, `Model Variations`.

## Queue Behavior
- While model A is generating, queue extra A jobs (seed/LoRA permutations) and confirm they run before switching models.
- Confirm placeholders show spinner + model/seed metadata for queued permutations.
- Confirm `Cancel` from preview/scheduler windows cancels server jobs (no orphan queue growth).
- Confirm completion sound only fires when queue is fully empty.

## Model Resolution
- Test with a model that has been renamed/reloaded on server and ensure generation still resolves.
- Verify per-model scheduler overrides still apply during generation.
- Verify graph replay (`PNG graph replay`) works when model IDs in saved graph are stale.

## History / Save Integrity
- Save experiment runs and confirm saved prompt is the generated prompt, not raw template.
- Confirm variant metadata is correct (`Mode`, `Variant Label`, `Variant Index`).
- Confirm newly saved images appear immediately in history/analytics without manual filter toggles.

## UI Spot Checks
- Prompt Variation dialog: controls visible and not overlapping.
- Image Details: keyboard left/right navigation works immediately (without focusing buttons first).
- Wildcard browse flyout: title and contents not clipped.

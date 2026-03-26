# Stabilization Plan

## Goal

Tighten the application around the workflows that already matter instead of expanding the feature surface. The priority is to make the current behavior easier to trust, easier to reason about, and easier to verify after changes.

## Phase 1: Establish Safety Nets

1. Strengthen automated checks around wildcard mutation flows.
2. Cover history replay and save/load behavior with repeatable tests.
3. Convert manual regression items into code-backed checks where practical.
4. Ensure every high-risk mutation path invalidates caches and refreshes derived state.

## Phase 2: Reduce Complexity in Hotspots

1. Split large orchestration logic out of `MainWindowViewModel`.
2. Move prompt generation, history replay, and image-generation parameter assembly into focused services.
3. Separate `WildcardManagerViewModel` UI state from wildcard domain operations.
4. Shrink methods that combine file I/O, parsing, dependency analysis, and UI status updates.

## Phase 3: Tighten Critical User Flows

1. Generate prompt from template and wildcard selections.
2. Edit and regenerate from history.
3. Save generated images and reload them correctly.
4. Convert, validate, merge, archive, and delete wildcards without stale state.
5. Confirm queue, cancellation, and completion behavior stay consistent.

## Immediate Slice Implemented Now

1. Fix stale wildcard dependency cache invalidation in mutation paths.
2. Add automated checks for dependency and unused-wildcard recomputation after save, delete, and legacy conversion.
3. Keep changes isolated to the wildcard domain so they are safe to land in a dirty worktree.

## Exit Criteria For This Phase

1. Wildcard dependency and unused reports stay correct after file mutations.
2. The existing lightweight test harness exercises these mutation paths.
3. Follow-up work can build on a written plan instead of ad hoc feature additions.

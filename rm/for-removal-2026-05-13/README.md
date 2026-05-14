# For Removal - 2026-05-13

Quarantine for unrelated local/tool artifacts found while creating the Lucy
notice-retrieval known-good checkpoint.

Contents are intentionally ignored from Git so a duplicate checkout, local
OpenKit logs, or generated root Chainlit config cannot be committed by accident.

- `root-chainlit-generated/`: Chainlit 2.9 generated config created at repo
  root. The real app config remains tracked at `agent/app/.chainlit/`.
- `root-openkit-state/`: local OpenKit state/config/log files.
- `openkit-worktrees/feat-lucytesting/`: linked Git worktree moved with
  `git worktree move`; branch remains `feat/lucytesting`.

Safe base for new work: `known-good/stable-20260513`.

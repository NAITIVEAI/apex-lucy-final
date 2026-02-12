# Git History Handoff Strategy

## Goal
Provide client with a clean repository history while preserving full internal history separately.

## Recommended Approach
1. Keep this repository as the internal system-of-record with full history.
2. Create a new client-facing repository initialized from the current cleaned working tree.
3. Push a single sanitized initial commit to the client repository.

## Steps (Clean-Room Export)
Run from the current repository root:

```bash
# 1) Create an export directory without git metadata
EXPORT_DIR="../lucy-client-handoff"
rm -rf "$EXPORT_DIR"
mkdir -p "$EXPORT_DIR"

rsync -a --exclude '.git' ./ "$EXPORT_DIR"/

# 2) Initialize a fresh git repo for client handoff
cd "$EXPORT_DIR"
git init
git add .
git commit -m "chore: initial client handoff snapshot"

# 3) Add client remote and push (example)
# git remote add origin <client-repo-url>
# git branch -M main
# git push -u origin main
```

## Alternative (If You Need Partial Historical Commits)
Use `git filter-repo` in a cloned copy to rewrite/remove historical paths, then publish that rewritten repository as client-facing history.

## Governance Notes
- Do not include internal remotes, issue references, or private operational notes in the client-facing repo.
- Verify no secrets in committed files before final push.
- Keep `/removal` only if you want traceability visible to the client; otherwise exclude it from export.


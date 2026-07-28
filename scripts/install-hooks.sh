#!/bin/sh
# Install this repository's git hooks. Run once per clone:
#
#   sh scripts/install-hooks.sh
#
# .git/hooks/ is not tracked by git, so hooks do not survive a clone. This
# script is the tracked copy; the hook it installs is the author-email lock
# described in README.md ("Reproducing the results").
set -e
root=$(git rev-parse --show-toplevel)
cp "$root/scripts/pre-commit" "$root/.git/hooks/pre-commit"
chmod +x "$root/.git/hooks/pre-commit"
echo "Installed .git/hooks/pre-commit (author-email lock)."
echo "Verify without committing:  sh scripts/pre-commit; echo \$?"

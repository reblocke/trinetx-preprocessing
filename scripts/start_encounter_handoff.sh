#!/bin/bash
# Use the existing private Mini launcher under a full-session execution lock.
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(dirname "$script_dir")
handoff_dir="${1:-$(dirname "$repo_dir")/encounter-refactor-handoff}"
mode="${2:-start}"
case "$mode" in start|--check) ;; *) echo 'Usage: start_encounter_handoff.sh [PRIVATE_HANDOFF_DIR] [--check]' >&2; exit 2 ;; esac
private_launcher="$handoff_dir/start-on-mini.sh"
lock_tool="$script_dir/with_execution_lock.py"
if [[ ! -f "$private_launcher" || ! -f "$handoff_dir/LOCAL_PATHS.md" ]]; then
  echo 'Existing private Mini handoff is required; no private paths are stored in Git.' >&2
  exit 1
fi

if [[ "$mode" == --check ]]; then
  /usr/bin/python3 "$lock_tool" --check "$handoff_dir/locks/controller.lock"
  /usr/bin/python3 "$lock_tool" --check "$handoff_dir/locks/build.lock"
  exec /bin/bash "$private_launcher" --check
fi

# The inner shell runs only after the controller lock is acquired. It probes
# the separate build lock to detect a detached build left by an earlier session.
exec /usr/bin/python3 "$lock_tool" "$handoff_dir/locks/controller.lock" -- \
  /bin/bash -c '
    set -euo pipefail
    /usr/bin/python3 "$1" --check "$2/locks/build.lock"
    cp "$3/NEXT_STEPS.md" "$2/NEXT_STEPS.md"
    printf "%s\n" "Use the audited NEXT_STEPS.md gates. Historical private notes supply paths, not superseded acceptance rules." \
      "Every build/comparison must use with_execution_lock.py with the shared build.lock." \
      "Starting one Mini-local session; keep this Terminal open and the Mini online."
    exec /bin/bash "$2/start-on-mini.sh"
  ' encounter-handoff "$lock_tool" "$handoff_dir" "$repo_dir"

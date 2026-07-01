# Task Queue (manually curated -- only the repo owner adds/reorders lines)
#
# Format:
# STATUS | task-id | one-line description + short acceptance criteria
#
# Valid STATUS values:
#   READY    -> ready to be dispatched by run_dev_loop.sh, no branch/PR yet
#   REVIEW   -> already dispatched, PR is open, awaiting manual review
#   BLOCKED  -> loop stops here, needs a decision from the repo owner
#   DONE     -> PR has been manually merged
#
# RULES:
# - Only the repo owner may add new lines or reorder them.
# - Claude Code must NOT add new tasks to this file.
# - Claude Code may ONLY change the STATUS of the line it is working on,
#   from READY -> REVIEW (after opening a PR) or READY -> BLOCKED (if
#   STEP 0 in the task prompt finds an ambiguity). This status change is
#   part of the same PR as the task itself.
# - run_dev_loop.sh stops completely if it finds a new BLOCKED line.

REVIEW | manual-council-review-matrix | Build a read-only Manual Council Review Matrix for the 6 stable review candidates, per project_checkpoint.md section 3h/3i. Acceptance: report per candidate + manual review questions, does not change candidate status, does not touch future_position_events.

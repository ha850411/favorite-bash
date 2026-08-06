# Entry point for sourcing pr-review & pr-reviews in Zsh shell configs
SCRIPT_DIR="${0:A:h}"
if [[ -f "$SCRIPT_DIR/lib/pr-review-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-review-helpers.zsh"
fi

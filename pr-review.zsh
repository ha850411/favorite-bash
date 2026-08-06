# ==============================================================================
# Legacy entry point - redirects to favorite-bash.zsh
# ==============================================================================
SCRIPT_DIR="${0:A:h}"
if [[ -f "$SCRIPT_DIR/favorite-bash.zsh" ]]; then
  source "$SCRIPT_DIR/favorite-bash.zsh"
fi

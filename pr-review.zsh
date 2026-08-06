# ==============================================================================
# Favorite Bash - Zsh Entry Point & Auto-Completion Loader
# ==============================================================================
SCRIPT_DIR="${0:A:h}"

# Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":${HOME}/.local/bin:"* ]]; then
  export PATH="${HOME}/.local/bin:$PATH"
fi

# Source Zsh wrappers, helper functions and completion specs
if [[ -f "$SCRIPT_DIR/lib/pr-review-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-review-helpers.zsh"
fi
if [[ -f "$SCRIPT_DIR/lib/pr-merge-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-merge-helpers.zsh"
fi
if [[ -f "$SCRIPT_DIR/lib/completion.zsh" ]]; then
  source "$SCRIPT_DIR/lib/completion.zsh"
fi

# ==============================================================================
# Favorite Bash - Zsh Entry Point & Auto-Completion Loader
# ==============================================================================
SCRIPT_DIR="${0:A:h}"

# Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":${HOME}/.local/bin:"* ]]; then
  export PATH="${HOME}/.local/bin:$PATH"
fi

# Source Zsh wrappers and helper functions
if [[ -f "$SCRIPT_DIR/lib/pr-review-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-review-helpers.zsh"
fi
if [[ -f "$SCRIPT_DIR/lib/pr-merge-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-merge-helpers.zsh"
fi

# Enable Zsh Tab Autocomplete for pr-merge, pr-review, pr-reviews
if typeset -f compdef &>/dev/null || autoload -Uz compinit 2>/dev/null; then
  _pr_merge_autocomplete() {
    local -a branches
    branches=(${(=)$(git branch -a --format='%(refname:short)' 2>/dev/null)})
    _describe 'git branches' branches
  }
  compdef _pr_merge_autocomplete pr-merge 2>/dev/null || true
fi

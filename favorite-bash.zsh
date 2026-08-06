# ==============================================================================
# Favorite Bash - Project Entry Point & Zsh Auto-Completion Loader
# 整包專案共用的 Zsh 入口檔與自動補全載入器
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
if [[ -f "$SCRIPT_DIR/lib/pr-scan-helpers.zsh" ]]; then
  source "$SCRIPT_DIR/lib/pr-scan-helpers.zsh"
fi
if [[ -f "$SCRIPT_DIR/lib/completion.zsh" ]]; then
  source "$SCRIPT_DIR/lib/completion.zsh"
fi

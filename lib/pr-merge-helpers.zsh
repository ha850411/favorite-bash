#!/usr/bin/env zsh
# ==============================================================================
# Favorite Bash - gh PR Merge Tool Wrapper
# ==============================================================================

function pr-merge() {
  local script_dir="${0:A:h}"
  local bin_path="${script_dir:h}/bin/pr-merge"

  if [[ -f "$bin_path" ]]; then
    "$bin_path" "$@"
  elif command -v pr-merge &>/dev/null; then
    command pr-merge "$@"
  else
    echo "❌ 無法找到 pr-merge 執行檔。"
    return 1
  fi
}

#!/usr/bin/env zsh
# ==============================================================================
# Favorite Bash - gh PR Scan Tool Wrapper
# ==============================================================================

function pr-scan() {
  local script_dir="${0:A:h}"
  local bin_path="${script_dir:h}/bin/pr-scan"

  if [[ -f "$bin_path" ]]; then
    "$bin_path" "$@"
  elif command -v pr-scan &>/dev/null; then
    command pr-scan "$@"
  else
    echo "❌ 無法找到 pr-scan 執行檔。"
    return 1
  fi
}

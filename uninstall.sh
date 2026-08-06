#!/usr/bin/env bash
# Support both ./uninstall.sh and source uninstall.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_BIN_DIR="${HOME}/.local/bin"
TARGET_CONFIG_DIR="${HOME}/.config/favorite-bash"

GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${CYAN}🗑  開始卸載 favorite-bash 自定義指令...${RESET}"

# 1. 移除 bin/ 下對應的指令軟連結
for cmd_path in "${SCRIPT_DIR}"/bin/*; do
  if [[ -f "${cmd_path}" ]]; then
    cmd_name="$(basename "${cmd_path}")"
    target_link="${TARGET_BIN_DIR}/${cmd_name}"
    if [[ -L "${target_link}" ]]; then
      rm -f "${target_link}"
      echo -e "  ${GREEN}✔${RESET} 移除指令軟連結: ${target_link}"
    fi
  fi
done

# 2. 移除設定檔軟連結
if [[ -L "${TARGET_CONFIG_DIR}/pr-scan.json" ]]; then
  rm -f "${TARGET_CONFIG_DIR}/pr-scan.json"
  echo -e "  ${GREEN}✔${RESET} 移除設定檔軟連結: ${TARGET_CONFIG_DIR}/pr-scan.json"
fi

# 3. 清理 ~/.zshrc 中的引用設定
ZSHRC="${HOME}/.zshrc"
if [[ -f "${ZSHRC}" ]]; then
  tmp_rc="$(mktemp)"
  if grep -qE "${SCRIPT_DIR}/(favorite-bash|pr-review)\.zsh" "${ZSHRC}"; then
    grep -vE "${SCRIPT_DIR}/(favorite-bash|pr-review)\.zsh" "${ZSHRC}" | grep -v "# favorite-bash" > "${tmp_rc}" || true
    mv "${tmp_rc}" "${ZSHRC}"
    echo -e "  ${GREEN}✔${RESET} 已清理 ${ZSHRC} 中的引用設定"
  else
    rm -f "${tmp_rc}"
    echo -e "  ${YELLOW}ℹ${RESET} ${ZSHRC} 中無引用設定，跳過清理"
  fi
fi

# 4. 若透過 source uninstall.sh 執行，直接清空當前視窗記憶體快取與函式定義
if [ -n "$ZSH_VERSION" ]; then
  rehash 2>/dev/null || true
  unfunction pr-scan pr-review pr-reviews 2>/dev/null || true
elif [ -n "$BASH_VERSION" ]; then
  hash -r 2>/dev/null || true
fi

echo -e "${GREEN}✨ 卸載完成！已即時自動刷新 Shell 環境。${RESET}\n"

# 5. 若為普通模式執行 (./uninstall.sh)，自動替換目前進程重載 Zsh，無須手動執行任何指令
if [ -t 0 ] && [[ "$SHELL" == *"zsh"* ]] && [ -z "$ZSH_VERSION" ]; then
  exec zsh
fi

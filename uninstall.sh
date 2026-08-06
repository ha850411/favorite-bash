#!/usr/bin/env bash
set -e

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
if [[ -L "${TARGET_CONFIG_DIR}/pr-merge.json" ]]; then
  rm -f "${TARGET_CONFIG_DIR}/pr-merge.json"
  echo -e "  ${GREEN}✔${RESET} 移除設定檔軟連結: ${TARGET_CONFIG_DIR}/pr-merge.json"
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

echo -e "${GREEN}✨ 卸載完成！${RESET}"

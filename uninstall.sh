#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_BIN_DIR="${HOME}/.local/bin"

GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${CYAN}🧹 開始卸載 favorite-bash 自定義指令...${RESET}"

# 1. 移除指令軟連結 (symlink)
for cmd_path in "${SCRIPT_DIR}"/bin/*; do
  if [[ -f "${cmd_path}" ]]; then
    cmd_name="$(basename "${cmd_path}")"
    target="${TARGET_BIN_DIR}/${cmd_name}"
    if [[ -L "${target}" || -f "${target}" ]]; then
      rm -f "${target}"
      echo -e "  ${GREEN}✔${RESET} 移除指令軟連結: ${target}"
    fi
  fi
done

# 2. 清理 ~/.zshrc 中的引用設定
ZSHRC="${HOME}/.zshrc"
if [[ -f "${ZSHRC}" ]]; then
  if grep -qF "${SCRIPT_DIR}/pr-review.zsh" "${ZSHRC}"; then
    tmp_rc="$(mktemp)"
    grep -vF "${SCRIPT_DIR}/pr-review.zsh" "${ZSHRC}" | grep -v "# favorite-bash" > "${tmp_rc}" || true
    mv "${tmp_rc}" "${ZSHRC}"
    echo -e "  ${GREEN}✔${RESET} 已從 ${ZSHRC} 清理引用設定"
  fi
fi

echo -e "${GREEN}✨ 卸載完成！${RESET}"

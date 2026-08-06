#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_BIN_DIR="${HOME}/.local/bin"
TARGET_CONFIG_DIR="${HOME}/.config/favorite-bash"

GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${CYAN}🚀 開始安裝 favorite-bash 自定義指令...${RESET}"

# 1. 確保 ~/.local/bin 目錄存在
mkdir -p "${TARGET_BIN_DIR}"

# 2. 為 bin/ 下所有指令檔建立軟連結 (symlink)
for cmd_path in "${SCRIPT_DIR}"/bin/*; do
  if [[ -f "${cmd_path}" ]]; then
    cmd_name="$(basename "${cmd_path}")"
    ln -sf "${cmd_path}" "${TARGET_BIN_DIR}/${cmd_name}"
    echo -e "  ${GREEN}✔${RESET} 建立指令軟連結: ${TARGET_BIN_DIR}/${cmd_name} -> ${cmd_path}"
  fi
done

# 3. 確保設定檔 pr-merge.json 軟連結至 ~/.config/favorite-bash/pr-merge.json
mkdir -p "${TARGET_CONFIG_DIR}"
if [[ -f "${SCRIPT_DIR}/pr-merge.json" ]]; then
  ln -sf "${SCRIPT_DIR}/pr-merge.json" "${TARGET_CONFIG_DIR}/pr-merge.json"
  echo -e "  ${GREEN}✔${RESET} 建立設定檔軟連結: ${TARGET_CONFIG_DIR}/pr-merge.json -> ${SCRIPT_DIR}/pr-merge.json"
fi

echo -e "${GREEN}✨ 安裝完成！所有指令已透過 ~/.local/bin 獨立運行。${RESET}"

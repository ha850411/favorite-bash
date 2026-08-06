#!/usr/bin/env bash
# Support both ./install.sh and source install.sh

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

# 4. 檢查並將專案入口引用寫入 ~/.zshrc (載入 Zsh Tab Autocomplete 自動補全)
ZSHRC="${HOME}/.zshrc"
SOURCE_LINE="[[ -f \"${SCRIPT_DIR}/favorite-bash.zsh\" ]] && source \"${SCRIPT_DIR}/favorite-bash.zsh\""

if [[ -f "${ZSHRC}" ]]; then
  if ! grep -qF "${SCRIPT_DIR}/favorite-bash.zsh" "${ZSHRC}"; then
    echo "" >> "${ZSHRC}"
    echo "# favorite-bash" >> "${ZSHRC}"
    echo "${SOURCE_LINE}" >> "${ZSHRC}"
    echo -e "  ${GREEN}✔${RESET} 已將專案入口與 Tab 補全設定寫入 ${ZSHRC}"
  else
    echo -e "  ${YELLOW}ℹ${RESET} ${ZSHRC} 中已包含專案入口設定，跳過寫入"
  fi
fi

# 5. 若為 source 模式則即時載入
if [ -n "$ZSH_VERSION" ]; then
  if [[ -f "${SCRIPT_DIR}/favorite-bash.zsh" ]]; then
    source "${SCRIPT_DIR}/favorite-bash.zsh" 2>/dev/null || true
  fi
  rehash 2>/dev/null || true
fi

echo -e "${GREEN}✨ 安裝完成！已即時自動刷新 Shell 環境。${RESET}\n"

# 6. 若為普通模式執行 (./install.sh)，自動替換目前進程重載 Zsh，無須手動執行任何指令
if [ -t 0 ] && [[ "$SHELL" == *"zsh"* ]] && [ -z "$ZSH_VERSION" ]; then
  exec zsh
fi

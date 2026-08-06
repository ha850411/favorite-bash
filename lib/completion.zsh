# ==============================================================================
# Favorite Bash - Zsh Autocomplete Spec
# 支援指令與 Git 分支名稱 Tab 自動補全提示
# ==============================================================================

if typeset -f compdef &>/dev/null || autoload -Uz compinit 2>/dev/null; then
  _pr_merge_autocomplete() {
    local -a branches flags
    flags=(
      '-r[只針對特定 GitHub Repo]:repo'
      '-b[指定建立 Target Branch B 時的 Base 分支]:base branch'
      '-M[自動 Merge 模式 (預設開啟)]'
      '--no-merge[關閉自動 Merge]'
      '-t[指定 PR 標題]:title'
      '-m[指定 PR 內容]:body'
      '-d[開立為 Draft PR]'
      '-y[跳過預覽直接執行]'
      '-h[顯示說明訊息]'
      'help[顯示說明訊息]'
    )

    branches=(${(=)$(git branch -a --format='%(refname:short)' 2>/dev/null)})

    if [[ $CURRENT -eq 2 || $CURRENT -eq 3 ]]; then
      _describe 'git branches' branches
    else
      _describe 'options' flags
    fi
  }

  compdef _pr_merge_autocomplete pr-merge 2>/dev/null || true
fi

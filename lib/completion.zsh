# ==============================================================================
# Favorite Bash - Zsh Autocomplete Spec
# 支援跨目錄動態定位、單號比對與各 Repo 限制最多 2 個分支之 Tab 自動補全
# ==============================================================================

_FAVORITE_BASH_ROOT="${${(%):-%x}:A:h:h}"

if typeset -f compdef &>/dev/null || autoload -Uz compinit 2>/dev/null; then
  _pr_scan_autocomplete() {
    local tool_dir="${_FAVORITE_BASH_ROOT}"

    # 1. 動態透過 symlink (例如 ~/.local/bin/pr-scan) 解析專案根目錄
    if [[ ! -f "${tool_dir}/lib/pr-scan-autocomplete-helper.py" ]]; then
      local binary_path="$(command -v pr-scan 2>/dev/null)"
      if [[ -n "$binary_path" ]]; then
        local real_bin=""
        if [[ -L "$binary_path" ]]; then
          real_bin="$(readlink "$binary_path" 2>/dev/null)"
        else
          real_bin="$binary_path"
        fi
        if [[ -n "$real_bin" ]]; then
          tool_dir="${real_bin:A:h:h}"
        fi
      fi
    fi

    # 2. 備用常見預設路徑
    if [[ ! -f "${tool_dir}/lib/pr-scan-autocomplete-helper.py" ]]; then
      tool_dir="/Volumes/workspace/favorite-bash"
    fi

    local helper_script="${tool_dir}/lib/pr-scan-autocomplete-helper.py"
    local config_file="${tool_dir}/pr-scan.json"

    if [[ ! -f "$config_file" && -f "$PWD/pr-scan.json" ]]; then
      config_file="$PWD/pr-scan.json"
    elif [[ ! -f "$config_file" && -f "${HOME}/.config/favorite-bash/pr-scan.json" ]]; then
      config_file="${HOME}/.config/favorite-bash/pr-scan.json"
    fi

    local -a flags
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

    if [[ $CURRENT -eq 2 ]]; then
      local current_word="${words[2]}"
      local -a branches_a
      if [[ -f "$helper_script" ]]; then
        branches_a=("${(f)$(python3 "$helper_script" branch_a "$current_word" "$config_file" 2>/dev/null)}")
      fi
      if [[ ${#branches_a} -gt 0 ]]; then
        _describe 'source branches (Branch A)' branches_a
      else
        local -a default_branches
        default_branches=("${(f)$(git branch -a --format='%(refname:short)' 2>/dev/null)}")
        _describe 'git branches' default_branches
      fi
    elif [[ $CURRENT -eq 3 ]]; then
      local branch_a="${words[2]}"
      local branch_b_input="${words[3]}"
      local -a target_branches
      if [[ -f "$helper_script" ]]; then
        target_branches=("${(f)$(python3 "$helper_script" branch_b "$branch_a" "$config_file" "$branch_b_input" 2>/dev/null)}")
      fi
      if [[ ${#target_branches} -gt 0 ]]; then
        _describe 'matched target branches (max 3 per repo)' target_branches
      else
        local -a default_branches
        default_branches=("${(f)$(git branch -a --format='%(refname:short)' 2>/dev/null)}")
        _describe 'git branches' default_branches
      fi
    else
      _describe 'options' flags
    fi
  }

  _bulletin_quiz_autocomplete() {
    local -a flags
    flags=(
      '-d[查詢題目與答案，但不送出登記]'
      '--dry-run[查詢題目與答案，但不送出登記]'
      '--slug[只處理指定文章尾碼，例如 20260831_BeAGiver]:slug'
      '--config[設定檔路徑]:config file:_files'
      '-e[員工編號]:employee id'
      '--employee-id[員工編號]:employee id'
      '-h[顯示說明訊息]'
      '--help[顯示說明訊息]'
    )
    _describe 'options' flags
  }

  _release_pr_autocomplete() {
    local -a flags
    flags=(
      '-i[指定 Jira 需求單號]:issue'
      '--issue[指定 Jira 需求單號]:issue'
      '-d[僅併發掃描與預覽，不實際在 GitHub 建立 PR]'
      '--dry-run[僅併發掃描與預覽，不實際在 GitHub 建立 PR]'
      '-r[指定 PR Reviewer 使用者名稱]:reviewer'
      '--reviewer[指定 PR Reviewer 使用者名稱]:reviewer'
      '-c[指定設定檔路徑]:config:_files'
      '--config[指定設定檔路徑]:config:_files'
      '-h[顯示說明訊息]'
      '--help[顯示說明訊息]'
    )

    if [[ $CURRENT -eq 2 ]]; then
      _message '上線單號 (例如: PMOJBVIP-30282)'
    elif [[ $CURRENT -eq 3 ]]; then
      local -a release_branches
      release_branches=("${(f)$(git branch -a --format='%(refname:short)' 2>/dev/null | grep -E '(^|/)release/' | sed -e 's#^origin/##' | sort -u)}")
      if [[ ${#release_branches} -gt 0 ]]; then
        _describe 'release branches' release_branches
      else
        _message '來源 Release 分支 (例如: release/SERVICE-0922)'
      fi
    elif [[ $CURRENT -eq 4 ]]; then
      local -a envs
      envs=(
        'staging:預發布環境 (STG)'
        'develop:開發基準環境 (Develop)'
        'prod:正式發布環境 (PROD)'
      )
      _describe '目標環境' envs
    else
      _describe 'options' flags
    fi
  }

  _merge_pr_autocomplete() {
    local -a flags
    flags=(
      '-m[指定 Git 合併方式 (預設 merge)]:method:(merge squash rebase)'
      '--method[指定 Git 合併方式 (預設 merge)]:method:(merge squash rebase)'
      '-f[強制合併，略過 Reviewer APPROVED 檢查]'
      '--force[強制合併，略過 Reviewer APPROVED 檢查]'
      '-d[預覽檢查 PR 審核與合併狀態，不實際在 GitHub 執行 Merge]'
      '--dry-run[預覽檢查 PR 審核與合併狀態，不實際在 GitHub 執行 Merge]'
      '-t[手動指定上線單號 (例如 PMOJBVIP-30282)]:ticket'
      '--ticket[手動指定上線單號 (例如 PMOJBVIP-30282)]:ticket'
      '-h[顯示說明訊息]'
      '--help[顯示說明訊息]'
    )

    if [[ $CURRENT -eq 2 ]]; then
      local -a release_branches
      release_branches=("${(f)$(git branch -a --format='%(refname:short)' 2>/dev/null | grep -E '(^|/)release/' | sed -e 's#^origin/##' | sort -u)}")
      if [[ ${#release_branches} -gt 0 ]]; then
        _describe 'release branches or PR URLs' release_branches
      else
        _message 'PR 網址、Release 分支、Issue 編號，或留空自動讀取剪貼簿'
      fi
    elif [[ $CURRENT -eq 3 ]]; then
      local -a envs
      envs=(
        'staging:預發布環境 (STG)'
        'develop:開發基準環境 (Develop)'
        'prod:正式發布環境 (PROD)'
      )
      _describe '目標環境' envs
    else
      _describe 'options' flags
    fi
  }

  compdef _pr_scan_autocomplete pr-scan 2>/dev/null || true
  compdef _bulletin_quiz_autocomplete bulletin-quiz 2>/dev/null || true
  compdef _release_pr_autocomplete release-pr 2>/dev/null || true
  compdef _merge_pr_autocomplete merge-pr 2>/dev/null || true
fi


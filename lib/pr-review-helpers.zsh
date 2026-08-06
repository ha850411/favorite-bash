# 將文字依終端顯示寬度截斷或補空白，結果放在 $REPLY。
function _pr_review_fit_cell() {
  emulate -L zsh
  setopt multibyte

  local text="$1"
  local width="$2"
  local char fitted='' padding
  local -a chars char_widths
  local i code char_width total_width=0 used_width=0 target_width

  for (( i = 1; i <= ${#text}; i++ )); do
    char="${text[i]}"
    printf -v code '%d' "'$char"

    # 常見 combining marks / variation selectors 不占寬度；CJK 與 emoji 占兩格。
    if ((
      (code >= 0x0300 && code <= 0x036f) ||
      (code >= 0x1ab0 && code <= 0x1aff) ||
      (code >= 0x1dc0 && code <= 0x1dff) ||
      (code >= 0xfe00 && code <= 0xfe0f) ||
      code == 0x200d
    )); then
      char_width=0
    elif ((
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe10 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6) ||
      (code >= 0x1f300 && code <= 0x1faff)
    )); then
      char_width=2
    else
      char_width=1
    fi

    chars+=("$char")
    char_widths+=("$char_width")
    (( total_width += char_width ))
  done

  if (( total_width <= width )); then
    fitted="$text"
    used_width=$total_width
  else
    target_width=$(( width - 1 ))
    for (( i = 1; i <= ${#chars}; i++ )); do
      (( used_width + char_widths[i] > target_width )) && break
      fitted+="${chars[i]}"
      (( used_width += char_widths[i] ))
    done
    fitted+='…'
    (( used_width++ ))
  fi

  printf -v padding '%*s' $(( width - used_width )) ''
  REPLY="${fitted}${padding}"
}

# 依終端顯示寬度將文字切成多列，每列補齊空白後放在 $WRAPPED_LINES。
function _pr_review_wrap_cell() {
  emulate -L zsh
  setopt multibyte

  local text="$1"
  local width="$2"
  local char current_line=''
  local i code char_width current_width=0
  typeset -ga WRAPPED_LINES
  WRAPPED_LINES=()

  for (( i = 1; i <= ${#text}; i++ )); do
    char="${text[i]}"
    printf -v code '%d' "'$char"

    if ((
      (code >= 0x0300 && code <= 0x036f) ||
      (code >= 0x1ab0 && code <= 0x1aff) ||
      (code >= 0x1dc0 && code <= 0x1dff) ||
      (code >= 0xfe00 && code <= 0xfe0f) ||
      code == 0x200d
    )); then
      char_width=0
    elif ((
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe10 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6) ||
      (code >= 0x1f300 && code <= 0x1faff)
    )); then
      char_width=2
    else
      char_width=1
    fi

    if (( current_width + char_width > width )); then
      _pr_review_fit_cell "$current_line" "$width"
      WRAPPED_LINES+=("$REPLY")
      current_line=''
      current_width=0
      [[ "$char" == ' ' ]] && continue
    fi

    current_line+="$char"
    (( current_width += char_width ))
  done

  _pr_review_fit_cell "$current_line" "$width"
  WRAPPED_LINES+=("$REPLY")
}

# 將 GitHub UTC timestamp 轉為本機時區的 Y/m/d H:i:s。
function _pr_review_format_timestamp() {
  emulate -L zsh
  setopt multibyte

  local timestamp_input="$1"
  local epoch

  # macOS / BSD date
  if epoch="$(date -j -f '%Y-%m-%dT%H:%M:%S%z' "${timestamp_input/Z/+0000}" '+%s' 2>/dev/null)"; then
    REPLY="$(date -r "$epoch" '+%Y/%m/%d %H:%M:%S')"
    return 0
  fi

  # GNU date fallback
  if REPLY="$(date -d "$timestamp_input" '+%Y/%m/%d %H:%M:%S' 2>/dev/null)"; then
    return 0
  fi

  REPLY="$timestamp_input"
}

# 建立「欄位 │ 值」格式的可換行內容，結果放在 $LABELED_LINES。
function _pr_review_labeled_lines() {
  emulate -L zsh
  setopt extendedglob

  local label="$1"
  local value="$2"
  local content_width="$3"
  local label_width="$4"
  local hyperlink_url="$5"
  local value_width=$(( content_width - label_width - 3 ))
  local label_cell blank_label value_cell visible_value trailing_padding
  local hyperlink_start='' hyperlink_end=''
  local i
  typeset -ga LABELED_LINES
  LABELED_LINES=()

  _pr_review_fit_cell "$label" "$label_width"
  label_cell="$REPLY"
  _pr_review_fit_cell '' "$label_width"
  blank_label="$REPLY"
  _pr_review_wrap_cell "$value" "$value_width"

  if [[ -n "$hyperlink_url" ]]; then
    hyperlink_start=$'\e]8;;'"$hyperlink_url"$'\a'
    hyperlink_end=$'\e]8;;\a'
  fi

  for (( i = 1; i <= ${#WRAPPED_LINES}; i++ )); do
    value_cell="${WRAPPED_LINES[i]}"
    if [[ -n "$hyperlink_url" ]]; then
      visible_value="${value_cell%%[[:space:]]##}"
      trailing_padding="${value_cell#$visible_value}"
      value_cell="${hyperlink_start}${visible_value}${hyperlink_end}${trailing_padding}"
    fi
    if (( i == 1 )); then
      LABELED_LINES+=("$label_cell │ $value_cell")
    else
      LABELED_LINES+=("$blank_label │ $value_cell")
    fi
  done
}

# 動態繪製單張 PR 卡片（Pixel-Perfect 精確對齊版）
function _pr_review_render_card() {
  emulate -L zsh
  setopt multibyte

  local is_focused="$1"
  local is_checked="$2"
  local content_width="$3"
  local repo="$4"
  local number="$5"
  local title="$6"
  local draft="$7"
  local head="$8"
  local base="$9"
  local updated="${10}"
  local changed_files="${11}"
  local author="${12}"
  local url="${13}"

  local detail_width=$(( content_width - 6 ))
  local label_width=7
  local val_width=$(( detail_width - label_width - 6 ))

  # ANSI Colors & Styles
  local C_RESET=$'\e[0m'
  local C_BORDER C_POINTER C_CHECK C_TITLE

  if (( is_focused )); then
    C_BORDER=$'\e[1;36m'        # 亮青
    C_POINTER=$'\e[1;36m❯\e[0m'
    C_TITLE=$'\e[1;97m'         # 亮白
  else
    C_BORDER=$'\e[38;5;240m'    # 暗灰
    C_POINTER=' '
    C_TITLE=$'\e[37m'           # 一般白
  fi

  if (( is_checked )); then
    C_CHECK=$'\e[1;32m[✔]\e[0m' # 亮綠
  else
    if (( is_focused )); then
      C_CHECK=$'\e[1;36m[ ]\e[0m'
    else
      C_CHECK=$'\e[90m[ ]\e[0m'
    fi
  fi

  local C_REPO=$'\e[1;34m'
  local C_NUMBER=$'\e[1;33m'
  local C_DRAFT=$'\e[43;30;1m DRAFT \e[0m'
  local C_LABEL=$'\e[90m'
  local C_HEAD=$'\e[36m'
  local C_ARROW=$'\e[90m→\e[0m'
  local C_BASE=$'\e[32m'
  local C_TIME=$'\e[90m'
  local C_FILES=$'\e[33m'
  local C_AUTHOR=$'\e[1;35m'
  local C_URL=$'\e[34m'

  # 1. 頂邊框 (Top Border) - 精確 100% 對齊
  local top_rule=""
  printf -v top_rule "%*s" $(( content_width - 7 )) ""
  top_rule="${top_rule// /─}"
  print -r -- " ${C_POINTER} ${C_BORDER}╭─${C_CHECK}${C_BORDER}─${top_rule}╮${C_RESET}"

  # 2. Header Line (Repo, Number, Draft)
  local raw_first="${repo} · #${number}"
  local vis_first pad_first
  if [[ "$draft" == "true" ]]; then
    _pr_review_fit_cell "$raw_first" $(( detail_width - 8 ))
    vis_first="${REPLY%%[[:space:]]##}"
    pad_first="${REPLY#$vis_first}"
    if [[ "$vis_first" == "$raw_first" ]]; then
      print -r -- "   ${C_BORDER}│${C_RESET}  ${C_REPO}${repo}${C_RESET} · ${C_NUMBER}#${number}${C_RESET}${pad_first} ${C_DRAFT}  ${C_BORDER}│${C_RESET}"
    else
      print -r -- "   ${C_BORDER}│${C_RESET}  ${C_REPO}${vis_first}${C_RESET}${pad_first} ${C_DRAFT}  ${C_BORDER}│${C_RESET}"
    fi
  else
    _pr_review_fit_cell "$raw_first" "$detail_width"
    vis_first="${REPLY%%[[:space:]]##}"
    pad_first="${REPLY#$vis_first}"
    if [[ "$vis_first" == "$raw_first" ]]; then
      print -r -- "   ${C_BORDER}│${C_RESET}  ${C_REPO}${repo}${C_RESET} · ${C_NUMBER}#${number}${C_RESET}${pad_first}  ${C_BORDER}│${C_RESET}"
    else
      print -r -- "   ${C_BORDER}│${C_RESET}  ${C_REPO}${vis_first}${C_RESET}${pad_first}  ${C_BORDER}│${C_RESET}"
    fi
  fi

  # 3. Title Lines
  _pr_review_wrap_cell "$title" "$detail_width"
  local w_line
  for w_line in "${WRAPPED_LINES[@]}"; do
    print -r -- "   ${C_BORDER}│${C_RESET}  ${C_TITLE}${w_line}${C_RESET}  ${C_BORDER}│${C_RESET}"
  done

  # 4. Blank Divider Line
  _pr_review_fit_cell "" "$(( content_width - 2 ))"
  print -r -- "   ${C_BORDER}│${REPLY}│${C_RESET}"

  # 5. Metadata Lines
  local raw_val vis_val pad_val

  # Branch
  raw_val="${head} → ${base}"
  _pr_review_fit_cell "$raw_val" "$val_width"
  vis_val="${REPLY%%[[:space:]]##}"
  pad_val="${REPLY#$vis_val}"
  if [[ "$vis_val" == "$raw_val" ]]; then
    print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}Branch ${C_RESET} │ ${C_HEAD}${head}${C_RESET} ${C_ARROW} ${C_BASE}${base}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"
  else
    print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}Branch ${C_RESET} │ ${C_HEAD}${vis_val}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"
  fi

  # Updated
  raw_val="${updated}"
  _pr_review_fit_cell "$raw_val" "$val_width"
  vis_val="${REPLY%%[[:space:]]##}"
  pad_val="${REPLY#$vis_val}"
  print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}Updated${C_RESET} │ ${C_TIME}${vis_val}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"

  # Files
  raw_val="${changed_files} changed files"
  _pr_review_fit_cell "$raw_val" "$val_width"
  vis_val="${REPLY%%[[:space:]]##}"
  pad_val="${REPLY#$vis_val}"
  print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}Files  ${C_RESET} │ ${C_FILES}${vis_val}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"

  # Author
  raw_val="@${author}"
  _pr_review_fit_cell "$raw_val" "$val_width"
  vis_val="${REPLY%%[[:space:]]##}"
  pad_val="${REPLY#$vis_val}"
  print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}Author ${C_RESET} │ ${C_AUTHOR}${vis_val}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"

  # URL
  raw_val="${url}"
  _pr_review_fit_cell "$raw_val" "$val_width"
  vis_val="${REPLY%%[[:space:]]##}"
  pad_val="${REPLY#$vis_val}"
  print -r -- "   ${C_BORDER}│${C_RESET}     ${C_LABEL}URL    ${C_RESET} │ ${C_URL}${vis_val}${C_RESET}${pad_val}  ${C_BORDER}│${C_RESET}"

  # 6. Bottom Border - 精確 100% 對齊
  local bot_rule=""
  printf -v bot_rule "%*s" $(( content_width - 2 )) ""
  bot_rule="${bot_rule// /─}"
  print -r -- "   ${C_BORDER}╰${bot_rule}╯${C_RESET}"
}

# 顯示可多選與捲動導覽的 PR TUI 選單，選取結果放進 $reply。
function _pr_review_menu() {
  emulate -L zsh
  setopt localtraps multibyte

  local total_items=${#urls}
  local -a checked
  local cursor=1 key sequence
  local i selected_count=0
  local scroll_offset=1
  local visible_count=3
  local content_width

  reply=()
  for (( i = 1; i <= total_items; i++ )); do
    checked[i]=0
  done

  # 使用 alternate screen，隱藏光標
  print -n -- $'\e[?1049h\e[?25l'
  trap 'print -n -- $'\''\e[?25h\e[?1049l'\''; return 130' INT TERM HUP

  while true; do
    local term_lines=${LINES:-$(tput lines 2>/dev/null || echo 24)}
    local term_cols=${COLUMNS:-$(tput cols 2>/dev/null || echo 120)}
    
    (( term_cols < 72 )) && term_cols=72
    content_width=$(( term_cols - 6 ))
    (( content_width > 96 )) && content_width=96

    # 每張卡片約 11 行，計算當前畫面可容納的卡片數量
    local max_visible=$(( (term_lines - 7) / 11 ))
    (( max_visible < 1 )) && max_visible=1
    visible_count=$max_visible

    # 調整 scroll_offset 確保 cursor 落在可見視窗內
    if (( cursor < scroll_offset )); then
      scroll_offset=$cursor
    elif (( cursor >= scroll_offset + visible_count )); then
      scroll_offset=$(( cursor - visible_count + 1 ))
    fi

    local title_rule=""
    printf -v title_rule "%*s" $(( content_width + 3 )) ""
    title_rule="${title_rule// /─}"

    print -n -- $'\e[H\e[2J'
    print -r -- $'\e[1;36m ⚡ PULL REQUEST REVIEWS\e[0m  \e[90m·  指派給你的待 Review PR\e[0m'
    print -r -- $'\e[1;36m '"${title_rule}"$'\e[0m'
    print -r -- $'\e[90m 總計 \e[1;97m'"$total_items"$'\e[0;90m 個 PR  ·  已選擇 \e[1;32m'"$selected_count"$'\e[0;90m 個\e[0m'
    print

    if (( scroll_offset > 1 )); then
      print -r -- $'\e[1;33m    ▲ 上方還有 '"$(( scroll_offset - 1 ))"$' 個 PR...\e[0m'
    fi

    local end_index=$(( scroll_offset + visible_count - 1 ))
    (( end_index > total_items )) && end_index=$total_items

    for (( i = scroll_offset; i <= end_index; i++ )); do
      local is_focused=0
      (( i == cursor )) && is_focused=1
      _pr_review_render_card \
        "$is_focused" \
        "${checked[i]}" \
        "$content_width" \
        "${repos[i]}" \
        "${numbers[i]}" \
        "${titles[i]}" \
        "${drafts[i]}" \
        "${heads[i]}" \
        "${bases[i]}" \
        "${updates[i]}" \
        "${changed_files[i]}" \
        "${authors[i]}" \
        "${urls[i]}"
      (( i < end_index )) && print
    done

    if (( end_index < total_items )); then
      print -r -- $'\e[1;33m    ▼ 下方還有 '"$(( total_items - end_index ))"$' 個 PR...\e[0m'
    fi

    print
    print -r -- $'\e[90m [↑/k] 向上  [↓/j] 向下  [Space] 選擇  [a] 全選  [Enter] 批次審核  [q] 離開\e[0m'

    if ! read -rs -k 1 key; then
      print -n -- $'\e[?25h\e[?1049l'
      return 1
    fi

    case "$key" in
      $'\e')
        sequence=''
        read -rs -k 2 -t 0.1 sequence 2>/dev/null
        case "$sequence" in
          '[A') (( cursor > 1 )) && (( cursor-- )) ;;
          '[B') (( cursor < total_items )) && (( cursor++ )) ;;
          *)
            print -n -- $'\e[?25h\e[?1049l'
            return 1
            ;;
        esac
        ;;
      k|K)
        (( cursor > 1 )) && (( cursor-- ))
        ;;
      j|J)
        (( cursor < total_items )) && (( cursor++ ))
        ;;
      g)
        cursor=1
        ;;
      G)
        cursor=$total_items
        ;;
      ' ')
        if (( checked[cursor] )); then
          checked[cursor]=0
          (( selected_count-- ))
        else
          checked[cursor]=1
          (( selected_count++ ))
        fi
        ;;
      a|A)
        if (( selected_count == total_items )); then
          for (( i = 1; i <= total_items; i++ )); do checked[i]=0; done
          selected_count=0
        else
          for (( i = 1; i <= total_items; i++ )); do checked[i]=1; done
          selected_count=$total_items
        fi
        ;;
      $'\n'|$'\r')
        break
        ;;
      q|Q)
        print -n -- $'\e[?25h\e[?1049l'
        return 1
        ;;
    esac
  done

  print -n -- $'\e[?25h\e[?1049l'
  for (( i = 1; i <= total_items; i++ )); do
    (( checked[i] )) && reply+=("$i")
  done
  return 0
}

# 搜尋待 review PR，使用 checkbox 多選後批次執行 approve。
function pr-reviews() {
  emulate -L zsh
  setopt multibyte

  typeset -g -a urls repos numbers authors drafts heads bases updates changed_files titles
  urls=()
  repos=()
  numbers=()
  authors=()
  drafts=()
  heads=()
  bases=()
  updates=()
  changed_files=()
  titles=()

  local -a selected_urls
  local output url repo number author draft head base updated changed_file_count title index
  local total rows
  local failures=0

  print -n -- $'\e[1;36m🔍 正在搜尋指派給你的待 Review PR…\e[0m\r'
  output="$(
    gh api graphql \
      -F first=100 \
      -f searchQuery='is:pr is:open review-requested:@me' \
      -f query='query($searchQuery: String!, $first: Int!) {
        search(query: $searchQuery, type: ISSUE, first: $first) {
          issueCount
          nodes {
            ... on PullRequest {
              url number title isDraft updatedAt changedFiles headRefName baseRefName
              repository { nameWithOwner }
              author { login }
            }
          }
        }
      }' \
      --template '{{.data.search.issueCount}}{{"\n"}}{{range .data.search.nodes}}{{.url}}{{"\t"}}{{.repository.nameWithOwner}}{{"\t"}}{{.number}}{{"\t"}}{{.author.login}}{{"\t"}}{{.isDraft}}{{"\t"}}{{.headRefName}}{{"\t"}}{{.baseRefName}}{{"\t"}}{{.updatedAt}}{{"\t"}}{{.changedFiles}}{{"\t"}}{{.title}}{{"\n"}}{{end}}'
  )" || { print -r -- $'\e[K\e[1;31m✖ 搜尋失敗，請檢查 gh auth 狀態。\e[0m'; return 1; }

  print -n -- $'\e[K'
  total="${output%%$'\n'*}"
  if [[ -z "$total" || "$total" == 0 ]]; then
    print -r -- $'\e[1;32m✨ 目前沒有指派給你的待 Review PR。\e[0m'
    return 0
  fi
  rows="${output#*$'\n'}"

  while IFS=$'\t' read -r url repo number author draft head base updated changed_file_count title; do
    [[ -z "$url" ]] && continue
    urls+=("$url")
    repos+=("$repo")
    numbers+=("$number")
    authors+=("$author")
    drafts+=("$draft")
    heads+=("$head")
    bases+=("$base")
    _pr_review_format_timestamp "$updated"
    updates+=("$REPLY")
    changed_files+=("$changed_file_count")
    titles+=("$title")
  done <<< "$rows"

  if ! _pr_review_menu; then
    print -r -- $'\e[90m已取消，沒有 Approve 任何 PR。\e[0m'
    return 0
  fi

  if (( ${#reply} == 0 )); then
    print -r -- $'\e[90m沒有選擇任何 PR。\e[0m'
    return 0
  fi

  for index in "${reply[@]}"; do
    selected_urls+=("${urls[index]}")
  done
  urls=("${selected_urls[@]}")

  print -r -- $'\e[1;36m🚀 正在 Approve '"${#urls}"$' 個 PR…\e[0m'
  print

  for (( index = 1; index <= ${#urls}; index++ )); do
    url="${urls[index]}"
    print -n -- $'\e[90m['"$index"'/'"${#urls}"$']\e[0m Approving: \e[1;34m'"$url"$'\e[0m ... '
    if gh pr review "$url" --approve >/dev/null 2>&1; then
      print -r -- $'\e[1;32m✔ Approved\e[0m'
    else
      print -r -- $'\e[1;31m✖ Failed\e[0m'
      (( failures++ ))
    fi
  done

  print
  if (( failures == 0 )); then
    print -r -- $'\e[1;32m✨ 全部 '"${#urls}"$' 個 PR 已成功 Approve！\e[0m'
  else
    print -r -- $'\e[1;33m⚠️ 處理完成：'"$(( ${#urls} - failures ))"$' 個成功，'"$failures"$' 個失敗。\e[0m'
  fi
}

# 批次開啟/審核 PR 的函式
function pr-review() {
  local urls=()
  local input

  # 有帶參數時，也支援把多行網址包在同一個引號參數內。
  if [[ $# -gt 0 ]]; then
    for input in "$@"; do
      urls+=("${=input}")
    done
  # Pipe / redirect 傳入時，讀取標準輸入。
  elif [[ ! -t 0 ]]; then
    input="$(<&0)"
    urls+=("${=input}")
  # 互動執行且沒有參數時，直接使用 macOS 剪貼簿，方便貼上多個 PR。
  elif (( $+commands[pbpaste] )); then
    input="$(pbpaste)"
    urls+=("${=input}")
  else
    print -u2 "Usage: pr-review <PR URL> [PR URL ...]"
    print -u2 "   or: printf '%s\\n' <PR URLs> | pr-review"
    return 2
  fi

  if (( ${#urls} == 0 )); then
    print -u2 -r -- $'\e[1;31mpr-review: 找不到 PR 網址\e[0m'
    return 2
  fi

  print -r -- $'\e[1;36m🚀 正在批次 Approve PR…\e[0m'
  local url failures=0
  for url in "${urls[@]}"; do
    if [[ -n "$url" ]]; then
      print -n -- $'  Approving: \e[1;34m'"$url"$'\e[0m ... '
      if gh pr review "$url" --approve >/dev/null 2>&1; then
        print -r -- $'\e[1;32m✔ Approved\e[0m'
      else
        print -r -- $'\e[1;31m✖ Failed\e[0m'
        (( failures++ ))
      fi
    fi
  done
}

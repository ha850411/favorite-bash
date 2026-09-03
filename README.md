# Favorite Bash & Zsh Scripts

個人常用的自定義 Shell 指令與自動化工具集合。

## 🚀 快速安裝與環境設定

### 1. 一鍵安裝 (自動即時生效)
在專案根目錄下執行：
```bash
./install.sh
```
此動作會：
1. 將 `bin/` 下所有指令軟連結（symlink）至 `~/.local/bin/`。
2. 將 `pr-scan.json` 與 `bulletin-quiz.json` 軟連結至 `~/.config/favorite-bash/`。
3. 將專案入口與 Zsh Tab 補全載入點寫入 `~/.zshrc`。
4. **自動替換進程重載 Shell（`exec zsh`），當下視窗即時生效所有指令與 Tab 分支自動補全！無須輸入任何多餘指令。**

### 2. 環境變數確認 ($PATH)
`~/.local/bin` 為 Unix/macOS 使用者自訂執行檔的標準目錄。
請確保您的 `~/.zshrc`（或 `~/.bashrc`）包含以下設定：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### 一鍵卸載 (自動即時失效)
在專案根目錄下執行：

```bash
./uninstall.sh
```
此動作會移除 `~/.local/bin/` 中屬於本專案的指令軟連結、清理 `~/.config/favorite-bash`、移除 `~/.zshrc` 中的載入點，並**自動重載 Shell 當下無感失效**。

---

## 🛠 指令列表

### 1. `pr-review`
批次審核並 Approve 指定的 GitHub Pull Request 網址。

**使用方式：**
```bash
# 帶入一至多個 PR 網址
pr-review https://github.com/owner/repo/pull/1 https://github.com/owner/repo/pull/2

# 透過 Pipe 輸入
cat urls.txt | pr-review

# 直接執行（將自動從 macOS 剪貼簿讀取網址）
pr-review
```

---

### 2. `pr-reviews`
透過 GitHub GraphQL API 搜尋指派給你的待審核 PR，並提供互動式 TUI 卡片選單進行批次 Approve。

**使用方式：**
```bash
pr-reviews
```

**操作快捷鍵：**
- `↑` / `k`: 上移選擇
- `↓` / `j`: 下移選擇
- `Space`: 勾選 / 取消勾選單一 PR
- `a`: 全選 / 全部取消
- `Enter`: 執行批次 Approve
- `q`: 離開選單

---

### 3. `pr-scan`
跨 Repositories 快速預覽分支變更、自動發起 PR 並支援一鍵/自動 Merge。若目標 Branch B 不存在，自動在遠端建立 Branch B。

**使用方式：**
```bash
# 基本用法：指定來源分支 A 與目標分支 B (預設開啟自動 Merge)
pr-scan feature/SERU-12705 release/SERVICE-0811

# 關閉自動 Merge (僅建立/檢查 PR)
pr-scan feature/SERU-12705 release/SERVICE-0811 --no-merge

# 指定 Target Branch B 不存在時所使用的 Base 分支
pr-scan feature/SERU-12705 release/SERVICE-0811 -b develop

# 指定特定 GitHub Repository
pr-scan -r owner/repo feature/SERU-12705 release/SERVICE-0811

# 自動確認預覽直接執行
pr-scan feature/SERU-12705 release/SERVICE-0811 -y
```

**互動介面操作 (單鍵零延遲響應)：**
- `y` 或 `Enter`: 確認執行選取 Repos
- `m`: 零延遲切換「自動 Merge 模式」開關
- `b`: 選擇並修改某個 Repo 建立 Branch B 時的 Base 分支
- `1-9`: 即時勾選 / 取消勾選指定 Repo
- `q`: 退出選單

---

### 📸 `pr-scan` 執行過程與效果預覽

#### 步驟 1：Tab 智慧單號與分支自動補全
在 Terminal 輸入 `pr-scan` 時，支援單號、前綴雙向匹配與跨追蹤 Repos 檢索（每個 Repo 最多自動篩選 3 個最相符分支）：

```text
$ pr-scan feature/SERU-127<Tab>
feature/SERU-12700  -- 104crm-laravel (遠端來源分支)
feature/SERU-12705  -- 104crm-laravel (遠端來源分支)
feature/SERU-12716  -- 104crm-laravel-api (遠端來源分支)

$ pr-scan feature/SERU-12705 release/SERVICE-08<Tab>
release/SERVICE-0811  -- 104crm-laravel-api (前綴完全符合)
release/SERVICE-0804  -- 104crm-laravel-api (前綴完全符合)
release/SERVICE-0806  -- 104crm-b (前綴完全符合)
```

#### 步驟 2：跨 Repo 掃描與互動式 TUI 預覽
執行指令後，自動非同步掃描所有 `tracked_repos` 的分支狀態、Diff 變更、與已存在 PR：

```text
🔍 正在掃描 9 個 Repositories 中的分支與變更... (設定檔: ~/.config/favorite-bash/pr-scan.json)

================================================================================
 🔍 跨 Repository 掃描結果與 PR 管理 (來源: feature/SERU-12705 ➔ 目標: release/SERVICE-0811)
 ⚡ 自動 Merge 模式: 🟢 已開啟 (單鍵 m 切換，發起/偵測 PR 後會直接自動 Merge)
================================================================================
 ❯ [✓] 1) 104corp/104crm-laravel (有檔案變更: 3 commits, 5 files (+120/-45))
        • 目標分支 B: 遠端已存在 release/SERVICE-0811 ➔ 將【自動 Merge】
   [✓] 2) 104corp/104crm-laravel-api (PR 已存在 #142)
        • 狀態: PR 已存在 (#142): https://github.com/104corp/104crm-laravel-api/pull/142 ➔ 將【自動 Merge】
   [ ] 3) 104corp/104crm-b (無檔案變更: 0 commits, +0/-0) ➔ 自動跳過
   [✓] 4) 104corp/104crm-c (有檔案變更: 1 commits, 2 files (+15/-2))
        • 目標分支 B: 遠端尚未建立 release/SERVICE-0811 ➔ 將自動建立並 Base 於: develop (Repo 預設 (*)) ➔ 將【自動 Merge】
================================================================================
請按按鍵進行操作 (單鍵即時響應，零延遲原地刷新)：
  • ↑ / ↓ (或 j/k)       : 上下移動游標選擇 Repo
  • ← / → (或 Space)     : 左右切換勾選 (← 取消勾選 / → 勾選 / Space 切換)
  • 按 a                 : 全選 / 全部取消勾選
  • 按 m                 : 切換【自動 Merge 模式】 (零延遲原地切換)
  • 按 b                 : 選擇並修改目前游標 (或指定) Repo 的 Base 分支
  • 按 1-9               : 即時勾選 / 取消勾選指定 Repo
  • 按 y 或 Enter          : 確認執行勾選的 3 個 Repos (發起/檢查 PR 並直接 Merge)
  • 按 q                 : 取消操作並退出

👉 請按下按鍵 [↑↓←→/Space/y/m/b/1-9/q]: y
```

#### 步驟 3：自動建立目標分支、發起 PR 與批次 Merge
確認執行後，系統會自動在遠端建立欠缺的分支、透過 GitHub API 發起 PR、並自動執行 Merge：

```text
🚀 開始批次執行 3 個 Repositories 的 Branch B 建立、PR 發起與 Merge...

--------------------------------------------------------------------------------
📦 [104corp/104crm-laravel]
  🚀 發起 Pull Request (3 commits, 5 files)...
  ✨ PR 建立成功！
  🔗 https://github.com/104corp/104crm-laravel/pull/208
  🔀 正在將 PR 合併進 release/SERVICE-0811...
  ✨ PR 已成功合併進 release/SERVICE-0811！
--------------------------------------------------------------------------------
📦 [104corp/104crm-laravel-api]
  ℹ️ 偵測到 PR 已存在：#142 (Merge feature/SERU-12705 into release/SERVICE-0811)
  🔗 https://github.com/104corp/104crm-laravel-api/pull/142
  🔀 正在將 PR 合併進 release/SERVICE-0811...
  ✨ PR 已成功合併進 release/SERVICE-0811！
--------------------------------------------------------------------------------
📦 [104corp/104crm-c]
  🔨 正在基於 "develop" (a1b2c3d) 建立遠端分支 "release/SERVICE-0811"...
  ✔ 已成功建立遠端分支 "release/SERVICE-0811" (based on "develop")！
  🚀 發起 Pull Request (1 commits, 2 files)...
  ✨ PR 建立成功！
  🔗 https://github.com/104corp/104crm-c/pull/85
  🔀 正在將 PR 合併進 release/SERVICE-0811...
  ✨ PR 已成功合併進 release/SERVICE-0811！

================================================================================
 ✨ 所有選取 Repositories 的 PR 與 Merge 作業已執行完成！
================================================================================
```

---

**設定檔說明：**
設定檔預設讀取 `~/.config/favorite-bash/pr-scan.json`（或專案目錄下 `pr-scan.json`）：
```json
{
  "default_target_base": "main",
  "tracked_repos": [
    "owner/frontend-app",
    "owner/backend-api"
  ],
  "repos": {
    "owner/frontend-app": {
      "default_base": "main",
      "branch_rules": [
        { "pattern": "release/hotfix/*", "base": "main" },
        { "pattern": "release/*", "base": "develop" }
      ]
    },
    "owner/backend-api": {
      "default_base": "develop",
      "branch_rules": [
        { "pattern": "release/v1.*", "base": "v1-legacy" },
        { "pattern": "release/v2.*", "base": "main" }
      ]
    }
  }
}
```
- `default_target_base`: 全域備用 Base 分支。
- `repos`: 針對不同 GitHub Repositories 個別設定：
  - `default_base`: 該 Repo 預設的 Base 分支。
  - `branch_rules`: 針對該 Repo 內不同的 Target Branch 通配符 Match Pattern (例如 `release/hotfix/*` 或 `release/*`)，各自指定要使用的 Base 分支。

---

### 4. `feature-branch-scan`

掃描 `pr-scan.json` 內所有 `tracked_repos` 的遠端 branches，找出符合
`feature/SERU-<單號>`（可帶描述後綴）的分支，並透過 Jira API 判斷 Jira 狀態分類是否為
`Done`。清單同時顯示 Jira Assignee，並提供互動式勾選；只有勾選後按 Enter 送出的 branches
才會透過 GitHub API 刪除。清單預設全部不勾選，按 `q` 可安全離開。

先在專案根目錄建立不會被 Git 追蹤的 `jira.env`：

```bash
JIRA_URL=https://your-company.atlassian.net
JIRA_USERNAME=your-email@example.com
JIRA_API_TOKEN=your-api-token
```

**使用方式：**

```bash
# 掃描設定檔內全部 repositories
feature-branch-scan

# 只掃描單一 repository
feature-branch-scan --repo 104corp/104crm-laravel

# 輸出可供其他工具使用的完整 JSON 結果（唯讀，不進入刪除選單）
feature-branch-scan --json
```

**互動選單快捷鍵：**

- `↑` / `k`：上移
- `↓` / `j`：下移
- `Space`：勾選／取消勾選
- `a`：全選／全部取消
- `Enter`：送出並刪除已勾選 branches
- `q`：取消並離開，不刪除任何 branch

判定依據為 Jira `fields.status.statusCategory.key == "done"`，不依賴工作流程中可能客製化的狀態名稱。

若任一 GitHub repository 或 Jira issue 查詢失敗，仍會輸出已取得的部分結果，並以 exit code `2` 結束，避免把未知狀態誤列為可刪除。

---

### 5. `bulletin-quiz`

查詢 104 佈告欄近兩個月的點閱紀錄，自動處理尚未完成的公告題目，送出後會再次查詢並確認點閱紀錄已完成。

執行指令時請直接帶入員工編號，不預存任何員工編號。若有自訂查詢頁或短網址的需求，可透過 `bulletin-quiz.json` 設定：

```json
{
  "api_url": "https://ud05zawv78.execute-api.ap-northeast-1.amazonaws.com/prod",
  "search_url": "https://bulletin-104.s3-ap-northeast-1.amazonaws.com/search.html",
  "short_link_base": "https://o.104.tw"
}
```

指令會由 SharePoint 文章網址尾碼（例如 `20260831_BeAGiver.aspx`）自動推導表單短網址 `https://o.104.tw/20260831_BeAGiver`。目前頁面會在題目資料中標示正確選項，錯誤選項只由瀏覽器前端攔截，因此指令會直接選正確答案，再送出一次登記。

**使用方式：**

```bash
# 完成所有未完成公告（直接帶入員工編號）
bulletin-quiz 3395

# 預覽所有未完成公告的題目與答案，不送出
bulletin-quiz 3395 --dry-run

# 只處理指定文章尾碼
bulletin-quiz 3395 --slug 20260831_BeAGiver

# 使用另一份個人設定檔
bulletin-quiz 3395 --config /path/to/bulletin-quiz.json
```


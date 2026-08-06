# Favorite Bash & Zsh Scripts

個人常用的自定義 Shell 指令與自動化工具集合。

## 🚀 快速安裝與環境設定

### 1. 一鍵安裝 (當下即時生效)
在專案根目錄下執行：
```bash
# 推薦方式：安裝並在當前視窗【即時啟用】所有指令與 Tab 自動補全
source install.sh

# 傳統方式：
./install.sh
```
此動作會：
1. 將 `bin/` 下所有指令軟連結（symlink）至 `~/.local/bin/`。
2. 將全域設定檔軟連結至 `~/.config/favorite-bash/pr-merge.json`。
3. 將專案入口與 Zsh Tab 補全載入點寫入 `~/.zshrc`。
4. 使用 `source install.sh` 模式會在**當下視窗即時啟用**所有指令與 Tab 分支自動補全！

### 2. 環境變數確認 ($PATH)
`~/.local/bin` 為 Unix/macOS 使用者自訂執行檔的標準目錄。
請確保您的 `~/.zshrc`（或 `~/.bashrc`）包含以下設定：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

加入後執行 `source ~/.zshrc`，即可在終端機任意目錄下直接使用 `pr-merge`、`pr-review` 等指令！

---

### 一鍵卸載
在專案根目錄下執行（任選一種方式）：

```bash
# 方式 A：當下視窗直接清空記憶體快取並立刻失效 (推薦)
source uninstall.sh

# 方式 B：傳統執行
./uninstall.sh
```
此動作會移除 `~/.local/bin/` 中屬於本專案的指令軟連結、清理 `~/.config/favorite-bash` 並移除 `~/.zshrc` 中的載入點。

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

### 3. `pr-merge`
跨 Repositories 快速預覽分支變更、自動發起 PR 並支援一鍵/自動 Merge。若目標 Branch B 不存在，自動在遠端建立 Branch B。

**使用方式：**
```bash
# 基本用法：指定來源分支 A 與目標分支 B (預設開啟自動 Merge)
pr-merge feature/login release/v1.0

# 關閉自動 Merge (僅建立/檢查 PR)
pr-merge feature/login release/v1.0 --no-merge

# 指定 Target Branch B 不存在時所使用的 Base 分支
pr-merge feature/login release/v1.0 -b develop

# 指定特定 GitHub Repository
pr-merge -r owner/repo feature/login release/v1.0

# 自動確認預覽直接執行
pr-merge feature/login release/v1.0 -y

# 編輯設定檔（設定要追蹤的 Repo 與預設 Base 分支）
pr-merge config
```

**互動介面操作 (單鍵零延遲響應)：**
- `y` 或 `Enter`: 確認執行
- `m`: 零延遲切換「自動 Merge 模式」開關
- `b`: 選擇並修改某個 Repo 建立 Branch B 時的 Base 分支
- `1-9`: 即時勾選 / 取消勾選指定 Repo
- `q`: 退出選單

**設定檔說明：**
設定檔預設讀取 `~/.config/favorite-bash/pr-merge.json`（或專案目錄下 `pr-merge.json`）：
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

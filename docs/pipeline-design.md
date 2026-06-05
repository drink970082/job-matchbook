# 半自動 Job-Hunt Pipeline 整合進 personal-ats

> **Note (historical design doc).** This is the original design write-up. Paths
> have since changed: the web app moved to `apps/web/` (was `ats-next/`), the
> worker to `apps/worker/` (was `ats-worker/`), and `docker-compose.yml` now
> lives at the repo root and defines two services, `web` and `worker`. References
> to `ats-next/` / `ats-worker/` below should be read accordingly. See the root
> README's Architecture section and [`SETUP.md`](./SETUP.md) for the current layout.

## Context（為什麼做這個）

現在的 personal-ats 是一個**事後記錄**工具：你手動投完履歷，再把每筆 application 記進去看圖表。
目標是在它前面接一條**半自動 pipeline**，把「找職缺 → 篩選 → 改履歷」自動化，但**投遞動作仍由人手動完成**（不做 auto-apply）：

```
公司清單 → 定時抓職缺(Greenhouse/Lever/Ashby) → 本地 LLM 評分
        → 高分者用 Claude 改一版單頁 LaTeX 履歷 → Telegram 推送
        → 在既有 UI 檢視/下載履歷 → 你手動投遞 → 一鍵記成 application
```

預期成果：每天起床看 Telegram，幾筆已經幫你打好分、改好履歷的高匹配職缺；點開 UI 就能投、投完一鍵記錄，分析圖表自動接上。

### 已定案的架構決定（與使用者確認過）
- **來源**：公司 ATS 公開 JSON API（Greenhouse / Lever / Ashby）。穩定、合規、不需 proxy。**不爬 LinkedIn/Indeed**（反爬+ToS 風險）。
- **執行環境**：獨立 **Python worker** 容器，與 Next.js app **共用同一個 SQLite 檔**（沿用現有 bind-mount 模式）。Next.js 只負責讀取與管理。
- **LLM 混合策略**：
  - 評分（高頻、每個職缺都跑）→ **本地 Ollama**，host 上的 RTX 4060 **8GB** → `qwen2.5:7b` 或 `llama3.1:8b`（Q4）。
  - 改履歷（低頻、只有高分者）→ **Anthropic Claude API**（忠實重寫 + 乾淨 LaTeX + 單頁迴圈穩定）。
- **履歷輸出**：LaTeX → PDF，用編譯後數頁數的迴圈確保單頁。

---

## 架構總覽

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  ats-next/ (既有 Next.js)    │        │  ats-worker/ (新, Python)     │
│  - 讀 job_postings           │        │  APScheduler 定時觸發:         │
│  - Discovered Jobs 分頁      │        │   1 fetch  (Greenhouse/...)   │
│  - 手動「標記已投遞」         │        │   2 score  (Ollama, 本地)     │
│  - 既有 applications 圖表    │        │   3 tailor (Claude + tectonic)│
└──────────────┬──────────────┘        │   4 notify (Telegram)         │
               │                        └───────────────┬──────────────┘
               │      共用 SQLite (WAL) db/applications.db │
               └───────────────────────────────┬─────────┘
                              ┌─────────────────┴────────────────┐
                              │  Ollama (host, 用 4060 GPU)        │
                              │  Claude API / Telegram Bot API     │
                              └────────────────────────────────────┘
```

**SQLite 共寫**：兩個 process 同時開同一檔。必須開 **WAL mode + busy_timeout**（worker 主要寫 `job_postings`，Next 主要讀 `job_postings`、寫 `applications`，衝突低）。Prisma 端在 `DATABASE_URL` 加 `?connection_limit=1` 並在啟動時 `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`；worker 端連線時設同樣 PRAGMA。

**Schema 所有權**：Prisma 是 schema 的唯一擁有者（`prisma db push`）。Python worker 用 raw SQL / SQLAlchemy core，欄位對齊 Prisma model，不自己改 schema。

---

## Step 1 — 新增資料表（Prisma 擁有）

檔案：`ats-next/prisma/schema.prisma`，新增一張 `job_postings`，並在 `applications` 加反向關聯。

```prisma
model job_postings {
  id              Int       @id @default(autoincrement())
  source          String    // greenhouse | lever | ashby
  external_id     String    // board 回傳的職缺 id
  company_name    String
  job_title       String
  location        String?
  job_url         String
  description     String    // 完整 JD 文字（給 LLM 用）
  score           Int?      // 0-100，Ollama 產出
  score_detail    String?   // JSON: { matched:[], missing:[], reasoning }
  resume_tex      String?   // tailored LaTeX 原始碼
  resume_path     String?   // tailored PDF 在共用 volume 的路徑
  resume_pages    Int?      // 編譯後實際頁數（單頁=1）
  pipeline_status String    @default("new") // new|scored|tailored|notified|applied|discarded
  application_id  Int?      // 標記已投遞後回連
  application     applications? @relation(fields: [application_id], references: [id], onDelete: SetNull)
  created_at      String
  updated_at      String?

  @@unique([source, external_id])   // 去重關鍵
}
```
`applications` model 加一行：`job_postings job_postings[]`（反向關聯）。
套用：在 host `ats-next/` 跑 `npx prisma db push`（沿用上次建 fresh db 的做法）。

---

## Step 2 — Python worker（新目錄 `ats-worker/`）

建議結構：
```
ats-worker/
  pyproject.toml / requirements.txt
  config.yaml              # 公司清單 + 篩選 + 門檻 + 排程（使用者填）
  .env                     # ANTHROPIC_API_KEY, TELEGRAM_*, OLLAMA_HOST（gitignore）
  resume/master.tex        # 使用者的 master LaTeX 履歷
  resume/master.txt        # 純文字履歷（給評分用，省 token）
  ats_worker/
    db.py                  # sqlite 連線 + WAL pragma + upsert/查詢
    fetch/greenhouse.py    # boards-api.greenhouse.io/v1/boards/{slug}/jobs
    fetch/lever.py         # api.lever.co/v0/postings/{slug}?mode=json
    fetch/ashby.py         # jobs.ashbyhq.com/api/...  (公開 board endpoint)
    score.py               # Ollama: JD+resume.txt → {score, matched, missing}
    tailor.py              # Claude: master.tex+JD → tailored.tex → 單頁迴圈
    notify.py              # Telegram sendMessage + sendDocument(PDF)
    pipeline.py            # 串 4 步, 依 pipeline_status 推進
    run.py                 # APScheduler cron;  --once 跑一次方便測試
```

### 1) fetch（參考：Greenhouse/Lever/Ashby 公開 API；備援 [JobSpy](https://github.com/speedyapply/JobSpy)）
- 每家公司依 `source` 打對應 API，取回 `title / location / url / 完整 JD`。
- 依 `config.yaml` 的關鍵字/地點過濾。
- `INSERT ... ON CONFLICT(source, external_id) DO NOTHING` 去重；新職缺 `pipeline_status='new'`。
- 三家的 endpoint 形態各異，各寫一個薄 adapter，輸出統一 dict。

### 2) score（本地 Ollama，參考 [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) 的 Ollama 用法）
- 對所有 `status='new'` 的列，呼叫 `OLLAMA_HOST`（host 上跑，用 GPU）的 `qwen2.5:7b`。
- prompt：丟 `resume/master.txt` + JD，要求**回 JSON**：`{score:0-100, matched_keywords, missing_keywords, reasoning}`。
- 寫回 `score / score_detail`，`status='scored'`。
- 8GB VRAM 跑 7B Q4 足夠；這步量大但便宜，全本地。

### 3) tailor（Claude API，參考 [ai-resume-builder](https://github.com/abhineetgupta/ai-resume-builder) 的 YAML→LaTeX per-job 思路、[ResuLLMe](https://github.com/IvanIsCoding/ResuLLMe)）
- 只處理 `status='scored'` 且 `score >= threshold`（config 設，預設 75）。
- 流程（**單頁保證的核心迴圈**）：
  1. Claude：給 `master.tex` + JD + 評分缺漏關鍵字 → 產 tailored `.tex`（**嚴禁捏造經歷**，只能重排/挑選/改寫既有內容）。
  2. 用 **`tectonic`**（單一執行檔、Docker 友善，免裝整套 texlive）編譯成 PDF。
  3. `pypdf` 數頁數。>1 頁 → 把「目前 N 頁、需壓到 1 頁」回饋給 Claude 再砍一輪 → 重編。最多 3 輪。
  4. 仍 >1 頁 → 存最後一版並 flag（`resume_pages` 記實際頁數，UI 顯示警告）。
- 存 `resume_tex / resume_path（PDF）/ resume_pages`，`status='tailored'`。

### 4) notify（Telegram Bot API，零依賴）
- 對 `status='tailored'` 且未通知者：`sendMessage`（公司 / 職稱 / 分數 / JD 連結）+ `sendDocument`（tailored PDF）。
- `status='notified'`。

### 排程
- `run.py` 用 **APScheduler** cron trigger（間隔由 config，預設每天一次）；`run.py --once` 供手動測試。

---

## Step 3 — Next.js UI 整合（讀取 + 手動投遞）

### 新 server actions（加在 `ats-next/src/lib/actions.ts`，沿用既有 `prisma` singleton 與回傳 `{success,...}` 慣例）
- `getJobPostings({ minScore?, status?, search? })` — 列出待檢視職缺，預設依 score desc。
- `discardJobPosting(id)` — `status='discarded'`。
- `markJobApplied(id)` — **重用既有 `addApplication()`** 建一筆 application（company/title/url 帶入、status='Applied'），成功後把該 `job_postings.status='applied'`、`application_id` 回填。這是「手動投遞後一鍵記錄」的接點。

### 新元件（複製既有樣式，符合現有設計系統）
- `ats-next/src/components/DiscoveredJobsTable.tsx` — 仿 `ApplicationTable.tsx`，欄位：公司 / 職稱 / **分數** / 地點 / 動作（看 JD、下載履歷、標記已投遞、捨棄）。單頁 flag 用 `Badge` 標警告。
- `Dashboard.tsx` 頂部加一個 **Tab 切換**：`Applications`（既有）↔ `Discovered Jobs`（新）。
- 職缺詳情用 Radix `Dialog`（仿 `StatusHistoryModal.tsx`）：顯示 JD + `score_detail`（命中/缺漏關鍵字）+ 下載 tailored PDF。

### 提供 PDF 下載（目前專案無 API route，新增一條）
- `ats-next/src/app/api/resume/[id]/route.ts` — 讀 `job_postings.resume_path` 串流回該 PDF（檔案在 worker 寫入的共用 volume）。

---

## Step 4 — Docker / 部署

`ats-next/docker-compose.yml` 擴充：
- 既有 `ats` service 不變（讀同一 db）。
- 新增 `ats-worker` service：build `../ats-worker`，掛 `../db/applications.db`（共寫）、`../ats-worker/resume`、PDF 輸出 volume；env 帶 `OLLAMA_HOST`、`ANTHROPIC_API_KEY`、`TELEGRAM_*`。
- **Ollama 跑在 host**（直接吃 4060 GPU，WSL2 下最省事），worker 經 `host.docker.internal:11434` 連。（容器內 GPU 直通要 nvidia-container-toolkit，較麻煩，不採。）
- worker Dockerfile：`python:3.11-slim` + `pip install`（jobspy 備援、anthropic、apscheduler、pypdf、requests）+ 裝 `tectonic`。

`.gitignore` 補：`ats-worker/.env`、`ats-worker/resume/`、PDF 輸出目錄。

---

## 需要你提供的輸入（config-time，非架構）
1. **公司清單**：每家的 ATS 類型 + board slug（例：Greenhouse 的 `boards-api.greenhouse.io/v1/boards/<slug>`）+ 想要的地點/關鍵字。
2. **履歷兩份**：`master.tex`（LaTeX 母版）+ `master.txt`（純文字，給評分省 token）。
3. **Anthropic API key**。
4. **Telegram**：bot token + chat id（用 @BotFather 建 bot、向 bot 發一則訊息後查 `getUpdates` 拿 chat id，我可帶你做）。
5. **參數**：分數門檻（預設 75）、排程間隔（預設每天）、單頁迴圈最大輪數（預設 3）。

---

## 驗證（end-to-end）
1. **schema**：`cd ats-next && npx prisma db push`，確認 `job_postings` 表建立。
2. **fetch 單測**：對每家挑一個真實公司，`python -m ats_worker.run --once` 只跑 fetch，確認 `job_postings` 有資料、JD 完整、去重正常。
3. **score**：確認 Ollama 在 host 起來（`ollama run qwen2.5:7b`），跑 score，檢查 `score/score_detail` 寫入且為合法 JSON。
4. **tailor**：對一筆高分職缺跑 tailor，確認 PDF 產出、`tectonic` 編得過、`resume_pages==1`；故意給長履歷測單頁迴圈會收斂。
5. **notify**：確認 Telegram 收到訊息 + PDF 附件。
6. **UI**：`docker compose up`，開 Discovered Jobs 分頁 → 看 JD/分數/下載 PDF → 點「標記已投遞」→ 確認 `applications` 多一筆、該職缺轉 `applied` 並從清單消失、既有圖表反映新 application。
7. **共寫**：worker 寫入時同時在 UI 操作，確認無 `database is locked`（WAL + busy_timeout 生效）。

---

## 主要風險與緩解
- **單頁無法 100% 保證** → 編譯數頁迴圈 + flag 警告，超過上限交人工微調。
- **SQLite 雙 process 共寫** → WAL + busy_timeout；worker 寫入批次短交易。
- **Ashby/Lever endpoint 變動** → adapter 隔離，壞掉只影響單一來源；保留 JobSpy 為備援來源。
- **LLM 捏造履歷內容** → tailor prompt 嚴格限制「只能重排/改寫既有內容」，PDF 產出後仍由你人工過目才投。
```

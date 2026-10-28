# 把一小段小說，做成能接著看的彩色漫畫

適用：桌面版 Codex、本機專案、可用的內建 ImageGen，以及你有權處理的小說與角色參考。先做一話或幾頁，確認角色、台詞與順序，再擴大範圍。

這是從實際長篇彩漫專案的通用元件整理出的 **新 starter**，並非原專案的完整發行包。保留來源一次解讀、角色素材綁定、整話分格、原生繁中字、每頁呼叫上限與續跑回收。原小說、角色圖、漫畫頁、私人網站與既有生產 state 均未包含。

## 給 AI 的安裝指令

把本儲存庫的真正網址貼進 Codex 專案聊天，再貼：

```text
請把上面的 GitHub starter 下載或 clone 到目前專案的 novel-comic-starter 子目錄。
若目錄已存在先讀現況，不覆寫。先讀 README.md、AGENTS.md、GOAL_PROMPT.md
及 .agents/skills/novel-comic/SKILL.md，學習工作流程，再檢查 exact Python
interpreter、Python 版本與 built-in image_gen 是否可用。先顯示要安裝的依賴與設定差異。
不要改全域 config、模型或最大代理數。執行 doctor、乾淨目錄 init --sample、
plan；先回報樣本頁數、來源、輸出路徑與缺少能力，不先生圖或公開。
```

## 需求與快速開始

Python 3.11 以上；核心只用標準函式庫。TXT/HTML/EPUB 的剖析、hash、JSON、ZIP 為 CPU 本質步驟。生圖由 Codex 內建 ImageGen 提供，依帳號當時的工具與額度；本工具不安裝模型、不供應 API 額度。

```powershell
python tools/comic.py doctor
python tools/comic.py --root work init --sample
python tools/comic.py --root work plan --episode sample/episode.json
python tools/comic.py --root work status
```

預期：一話一頁原創樣本完成編譯，control 仍 hold=true。已有 work 時執行 status，不重跑 init。sample 圖像及故事是本 starter 原創示範；是否已含實際生圖，依 samples/PROVENANCE.md。

PDF 是可選功能：先在專案內建立 `.venv`，使用該 interpreter 安裝 `requirements-pdf.txt`。掃描 PDF 不在核心支援範圍；請提供可選取文字的版本，或另外確認 GPU OCR。不要用 CPU-only OCR 靜默補救。

## 提供來源與插圖

```powershell
python tools/comic.py --root work import "我的小說.txt"
python tools/comic.py --root work import "我的小說.epub"
```

支援 UTF-8 TXT/HTML、未加密 EPUB、具文字層 PDF（需 pypdf）。inventory 列來源 SHA、每個 unit 的 locator、段落數與開頭預覽。EPUB 依 spine 次序，PDF 依實體頁；這些都不保證等於小說的卷/章/改編話，必須由人與 AI 對照目錄確認。工具不處理 DRM。

網址先交給 AI 讀指定章，請它列「能讀到的章名、開頭、結尾、缺漏」，確認後另存本機 TXT 再匯入。需要登入、反爬或缺頁時，停止抓取；在你可合法閱讀的頁面複製該章文字存成 UTF-8 TXT，或提供可下載的 EPUB/文字 PDF。不要把讀到一小段當整本已下載。

插圖放 `work/references/`；EPUB 可複製原檔成 ZIP 後解壓到 work，從 Images 等實際目錄選取。依原書頁碼/章名記來源、人物、年齡/衣裝與可使用範圍。AI 必須看圖才把 SHA 與 identity_subjects 寫入 references.json。多人同圖明確寫「左側短黑髮女子」等定位；不能同一人綁兩個角色。沒有插圖可先製作一張原創角色參考，由人確認後沿用。

## 製作一話

讀 GOAL_PROMPT.md，替換來源與範圍後貼到聊天。作者依 samples 寫 source-map、references、page spec、episode manifest，root 用 plan 檢查後才 authorize。

```powershell
python tools/comic.py --root work authorize --episode sample-e001
python tools/comic.py --root work prepare --episode sample-e001 --page p001
```

prepare 回傳 exact tool_arguments。AI 用它呼叫內建 image_gen **一次**，立即保存完整 result JSON 與原生 PNG；接著：

```powershell
python tools/comic.py --root work save --episode sample-e001 --page p001 --image "工具回傳的原生PNG" --result "完整result.json"
python tools/comic.py --root work review --episode sample-e001 --page p001 --observations "實圖核對.json"
python tools/comic.py --root work export --episode sample-e001
```

實圖核對 JSON 依 samples/review-template.json，填 exact PNG SHA 與具體觀察；工具不會替你看圖。全部 PASS 才匯出 CBZ 與 manifest。CBZ 可用支援漫畫的閱讀器，或複製成 ZIP 解壓看 PNG。匯出不會上傳。

## 多 agents 的可執行分工

```text
本次用最多 3 名子代理，沿用目前模型，不改全域 config。
作者 A：只讀指定章與已確認角色圖；只寫 work/author/e001/ 的來源表與整話分鏡。
作者完成後 root 整合並 plan、authorize。
生成 B/C：各領互不重疊頁面，例如 B=p001,p003、C=p002,p004；只用 prepare/save
寫自己頁的 attempt 目錄。每次先保存與 checkpoint 再取下一頁。
QA：生成完成後重用空出的代理，一次看原尺寸圖片並填 observations，不另開重複雙審。
root 唯一改 control、episode manifest、採用核對與 export。未知結果先回收。
```

並行上限只限制容量，AGENTS 與派工才決定工作範圍；它們不是 OS 寫入隔離。需要更強隔離可用不同 checkout，但不讓多個 checkout 同寫 canonical state。先一話用 2–4 名，只有互斥就緒頁與額度足夠才增加。

作者實測設定（2026-10-28，CLI `0.162.0-alpha.17.2`）是 `[agents] max_concurrent_threads_per_session = 16`；主聊天不算在此欄位，`agents.max_threads` 是當時文件的舊 alias。這是作者設定，不是所有版本/帳號上限。讀者應先核對 [官方設定參考](https://learn.chatgpt.com/docs/config-file/config-reference) 與本機 schema。

安裝器不改你的設定。請 AI 先只顯示目前相關欄位、建議 diff 與備份位置，遮掉其他敏感值。你決定變更後才修改；保留原檔，開新聊天核對實際工具及並行量。不要把編輯 config 當作目前 session 已生效。

作者使用 GPT-6.1 sol／極高作為主聊天經驗；本 starter 不強制該模型，子代理也預設繼承當下設定。可選名稱、推理等級與額度依 App/帳號；模型推理不等於 ImageGen 的圖像模型。

## 續作、修正、暫停與恢復

```text
從第 X 卷第 Y 章開始，只做第 Z 話，最多 4 頁。先列出 exact 來源範圍供確認。
第 Z 話通過後，只續做第 Z+1 話；保留已完成頁、角色圖與所有收據，不重生 PASS。
只修第 Z 話 p002 的第 2 格：說話者應為阿澄。保留其餘內容；核對原來源和原圖，
先指出應改 source-map/spec 或生圖哪一層，再沿同頁剩餘次數修正，禁止整話重生。
暫停新生圖，保存返還結果與 checkpoint，不刪 pending，不停止其他工作。
恢復同一 Goal：先 status，列 PASS／SAVED_NEEDS_REVIEW／UNKNOWN_RESULT／READY，
只處理未完成項；未知結果先找原 handle，不建立新目錄清零。
```

```powershell
python tools/comic.py --root work pause
python tools/comic.py --root work status
python tools/comic.py --root work resume
```

修正：先保留原 spec，另寫 `page-p001-r02.json`；需有該頁當次 FAIL 實圖紀錄且仍有額度。root 執行 `revise --episode <id> --page p001 --spec <新spec相對路徑>`，保留 input 舊版與 attempt 次數，再 prepare。若要改來源表/參考，先指出對應已生成頁與 stale evidence，停在 root 協調；不能直接換掉已綁定資料。工具預設最多2次；超過需另行明確指定單頁授權與版本，starter 不提供清零捷徑。

## 常見卡點

| 訊息/現象 | 下一步 |
|---|---|
| 找不到 python | 請 AI 核對 exact interpreter，安裝 Python 3.11+ 到可用位置 |
| EPUB 沒文字/加密 | 提供未加密合法版本或 UTF-8 TXT |
| PDF 沒文字 | 換有文字層版本；不默默 OCR |
| HOLD_OR_SCOPE_NOT_AUTHORIZED | 先確認話/頁範圍，root authorize；暫停中先恢復 |
| UNKNOWN_RESULT | 找原工具結果/handle，只保存，不重呼 |
| INPUT_CHANGED / REFERENCE_CHANGED | 對照版本與來源 SHA，root 解決該筆差異 |
| ALREADY_SAVED_OR_PASS | 看已保存圖或核對記錄；不要重新生圖 |
| ATTEMPT_LIMIT | 交付現有候選與缺陷，等待明確單頁決策 |
| 字錯/人物換人 | 看實圖、確認說話者與角色素材，再做一次定點修正 |

## 來源與授權

通用編譯器取自作者實際流程，版本與摘要見 PROVENANCE.md。程式、文件與原創樣本採 MIT；第三方小說/圖片的權利不因此移轉。只使用自己有權處理及分享的素材，公開前另核對授權。下載 starter 不附小說，也不承諾每張一次畫對、整本自動完成或免費無限額度。

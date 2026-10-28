# 小說彩漫工作約定

先讀 README.md、GOAL_PROMPT.md、.agents/skills/novel-comic/SKILL.md。本專案是可攜 starter；不依賴作者的私人小說、磁碟代號、服務、金鑰或知識庫。

root 管理有限範圍、work/control.json、整話目錄、合併、版本與匯出，是唯一 writer。先跑 doctor 與 status。沒有小說可先 init --sample；初始化預設 hold，不自動生圖。僅改已授權的話數與頁面，不續作整部小說。

使用者要求多 agents 時才分工。root 先實際確認此 session 的工具、模型選項及並行限制。通常從 2–4 名開始；可用額度與就緒頁不足就減少。不要把最大值當必派數量，不改全域 config。作者按整話/來源單元互斥分工，只寫自己 work/author/<unit>/ 的來源解讀、分鏡與素材表。生成 worker 按頁互斥，只透過 comic.py 寫所領取頁的 attempt-*，不改 control、episode manifest 或其他頁。QA 看最終原尺寸圖片，寫分配的 observations JSON；只核對一次及具體缺陷，不因美感偏好反覆生圖。root 統一採用並匯出。

作者實讀來源一次：固定場景順序、敘事視角、出場/提及人物、dialogue_id、說話者、來源段落與判斷理由。角色年齡/衣裝/傷勢分 state_id；看過參考圖才綁定 appearance、image SHA 與 identity_subjects。每格明列人物、動作、素材索引與短繁中台詞；不能把長小說原文貼進畫面指令。圖中文字與氣泡同次原生生成，後貼字不是預設。

編譯器來自實際專案通用元件；它只驗證結構與綁定，不保證人物/劇情/字形正確。不要復活歷史每頁雙審、完整 DAG 或無限修圖流程。

每頁一次初始呼叫，最多一次定點修正；未知結果保留原 handle，先回收，不能視為失敗。呼叫前 prepare；收到結果立即保存完整 result JSON、原生 PNG、prompt 與 receipt，再實圖核對。只有明確 FAIL、範圍仍有效且未到上限才可修。改修圖指令保留上一版，root 更新 input 綁定前須核對該頁舊 result、review 與使用者缺陷；不得重建 workspace 或換 ID 來清零次數。

暫停只禁止新呼叫，已返還的結果仍可 save。恢復先 status，PASS 不重看、有 result 不重生、UNKNOWN_RESULT 只回收。所有背景子程序完全隱藏。若另有本機模型/OCR/媒體運算，需先驗證實際 GPU 與 interpreter，不靜默回退 CPU。公開、付費方案、購買、部署均需當次授權。

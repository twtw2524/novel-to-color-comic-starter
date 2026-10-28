---
name: novel-comic
description: 將使用者有權處理的小說指定範圍製成繁體中文彩漫，管理來源定位、角色參考、整話分鏡、有限 Goal、互斥多代理及保存續跑。適用此 starter 的製作與修稿，不自動發布或整部無限生成。
---

以專案 AGENTS.md 的角色寫入範圍與 GOAL_PROMPT.md 的有限目標執行。先核對目前 workspace，不把新初始化當續跑。

1. `python tools/comic.py doctor`；確認 built-in image_gen 真可用。缺生圖工具時可完成安裝、來源與分鏡，清楚保留圖片 gate；不改走付費 API。
2. `python tools/comic.py --root work init --sample` 可在無小說時起步。正式來源用 `import <file>`，看 inventory 的 unit_id、locator、preview，再詢問 exact 卷/章/話。網址用可操作瀏覽器讀指定章；抓不到時指導使用者存合法可讀 TXT/EPUB/文字 PDF，不繞過登入或付費。
3. 參照 samples 的四種 JSON，替指定話編寫 source.json、source-map.json、references.json、page spec、episode.json。保留原始來源 SHA；不要因檔名認角色。來源表與分鏡區分可畫動作和台詞/來源證據。選出 EPUB 插圖需解壓到 work，檢視實圖、標來源位置與使用權，再以 SHA 和人物定位綁定。缺角色圖可先做一張原創角色參考，另計入明確 Goal 範圍。
4. `plan --episode <relative episode.json>` 以通用編譯器一次檢查；root 確認頁數與來源，再 `authorize --episode <id>`。工具只做本機資料處理；authorize 是工作流範圍，不代替使用者的付費/公開授權。
5. 生成 worker 對自己的 page 執行 `prepare --episode <id> --page <id>`。只送回傳的 tool_arguments 到 built-in image_gen 一次。完整 result JSON 立即落盤（不要在聊天列印 base64），將工具實際提供的 native PNG 路徑交給 `save --image <path> --result <json>`。不要臆測 result 內的 image 路徑，也不以截圖替原生 PNG。
6. 以 view_image 檢查實際 PNG，依 samples/review-template.json 寫 observations，含 exact PNG SHA、逐項具體觀察。`review --observations <file>`。FAIL 只修指定缺陷；需改提示時由 root 保留版本、重編綁定，見 README「修正」。到上限停止。
7. `status` 回收、`pause` 禁止新呼叫、`resume` 恢復同一 scope。全部 PASS 才 `export --episode <id>`；抽看 CBZ 內 PNG 與頁序。匯出只在本機，不自動架網站。

多代理派工訊息最少含 episode/page/來源段落、允許寫入目錄、輸入版本、呼叫上限、回收入口與交付檔。不要把所有小說、歷史文件與既有圖全塞給每名 worker。沒多代理工具時同樣按角色順序完成，報告當次實際執行方式。

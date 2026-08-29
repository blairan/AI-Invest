@echo off
echo 正在為您抓取期交所最新數據，請稍候...
<<<<<<< Updated upstream
cd /d "f:\程式設計\AI投資"
=======
cd /d "%~dp0"
>>>>>>> Stashed changes
python scraper_and_report.py
echo 更新完成！正在為您開啟報告...
start daily_report.html

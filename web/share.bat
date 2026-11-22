@echo off
rem Share with teammates through Cloudflare Tunnel.
rem In another window: cloudflared tunnel --url http://127.0.0.1:8000
rem The server still listens on 127.0.0.1 only. Requests from *.trycloudflare.com must enter the access code.
rem To keep a fixed code, run first: set SEMOGWI_ACCESS_CODE=your-code-8-or-more-chars
cd /d "%~dp0"
set SEMOGWI_SHARE=1
call "%~dp0run.bat"

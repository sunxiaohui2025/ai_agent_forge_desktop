# 打包说明（macOS / Windows 安装程序）

桌面应用由三部分组成，打包时全部塞进安装包，用户**无需安装 Python**：
- Electron 外壳（main.js / preload.js）
- Python 后端 → PyInstaller 冻结成单目录可执行文件（resources/backend）
- Vue 前端 → 生产构建，由后端同源提供（resources/frontend）

## 一次性准备
```bash
# 后端打包工具
cd backend && .venv/bin/python -m pip install pyinstaller

# 桌面依赖（含 electron-builder）
cd ../desktop && npm install
```

## 构建 macOS 安装包（在 macOS 上执行）
```bash
cd desktop
npm run dist:mac
# 产物：desktop/release/H3C Agent-<版本>-arm64.dmg  和  -x64.dmg
```

## 构建 Windows 安装包（必须在 Windows 上执行）
> Windows 的 .exe 安装包与 Python 二进制都必须在 Windows 机器（或 Windows CI）上构建，
> 无法在 macOS 上交叉编译。
```powershell
# 在 Windows 上，先准备好同样的 backend/.venv（pip install -e . + pyinstaller）
cd desktop
npm run dist:win
# 产物：desktop/release/H3C Agent-Setup-<版本>.exe (NSIS 安装向导)
```

## 分步命令
```bash
npm run build:frontend     # 构建 Vue → frontend/dist
npm run build:backend      # PyInstaller → backend/dist/h3c-agent-backend
npm run prepare:resources  # 拷贝上述产物到 desktop/resources/
```

## 运行时架构（生产）
1. Electron 主进程在固定端口启动 `resources/backend/h3c-agent-backend`
2. 该后端服务 `/api/*` 并同源托管 `resources/frontend` 的 SPA
3. 主窗口加载 `http://127.0.0.1:<port>/`，相对 `/api` 调用与前端路由开箱即用
4. 用户数据存于 `~/.h3c-agent`（SQLite）

## 代码签名 / 公证（可选）
- macOS：设置环境变量 `CSC_LINK`(证书 .p12) + `CSC_KEY_PASSWORD`，并在 electron-builder.yml 把 `mac.identity` 改为你的签名身份；公证再加 `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID`。
- 未签名包首次打开需右键「打开」绕过 Gatekeeper。
- Windows：设置 `CSC_LINK` + `CSC_KEY_PASSWORD` 进行 Authenticode 签名。

## 图标（可选）
把 `build/icon.icns`(mac) 和 `build/icon.ico`(win) 放进 desktop/build/ 即可被自动采用。

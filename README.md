# 英语小说阅读 App（读者端 + 后台上传）

## 新增：小说智能体工作台（多Agent + 知识库 + Kimi）

现在项目额外支持一个“小说生成工作台”，路径：

- `/Users/yuanxi/Documents/New project/novel_studio.html`
- 访问地址：`http://你的IP:端口/novel-studio`

能力：

1. 知识库录入（长文本自动分片）
2. 学生画像模板 + 自动分流策略（按焦虑/自律/基础/目标分配剧情推进路线）
3. 20章全书大纲生成（1-6阶段主线成长）
4. 按章多Agent协同写作（剧情/人物/深度思考/场景并行，写作与质检串行）
5. 双层逻辑审核（章节连续性 + 全书连续性）
6. 每章自动沉淀项目记忆（人物关系/时间线/世界规则/伏笔）到项目状态与知识库
7. 章节历史持久化（SQLite）
8. 审核不通过自动改写（默认最多 2 轮，可配置）
9. 每章目标字数与细节密度可配置，低于字数下限会自动触发扩写改写

Kimi 接入（可选）：

```bash
MOONSHOT_API_KEY='你的key' \
MOONSHOT_MODEL='kimi-k2-0905-preview' \
ADMIN_KEY='your-strong-key' \
./start_backend.sh 5000
```

说明：

1. 未配置 `MOONSHOT_API_KEY` 时，系统会自动使用离线模板兜底（可跑通流程）
2. 所有写入型 API（知识新增/删除、生成大纲、生成章节）都需要请求头 `X-Admin-Key`
3. Kimi 模型名可按你的账户权限替换为可用模型
4. 学生画像模板接口：`GET /api/novel-studio/student-profile-template`
5. 项目状态接口：`GET /api/novel-studio/project-state?projectName=...`
6. 工作台支持在页面中填写 Kimi API Key（保存在浏览器 localStorage，不用每次重填）
7. K2.5 推荐配置：`thinking` 模式 + `top_p=0.95` + 目标字数>=3000（不足会触发自动改写扩写）

现在是两种模式：

1. 读者端：只读书架、阅读、翻译、评论、闯关，不可上传
2. 后台端：admin 上传书籍并配置每章闯关任务，所有读者自动同步看到

## 已实现重点

1. 手机阅读半屏遮挡修复：正文全屏，控制层悬浮，不再占半屏高度
2. 释义卡显隐修复：点英文出现，点其他区域自动消失
3. 章节控制增强：新增上一章/下一章
4. 下一章逻辑：未过关先测验；如果该章没配置任务则自动通过并进下一章
5. 闯关任务改为手动配置：只对你上传并配置过的章节生效，没配置就没任务
6. `&quot;` 问题修复：导入时自动做 HTML 实体解码，正文正常显示引号
7. 服务端书架：管理员上传一次，所有用户书架自动出现，用户端不可上传

## 目录

- `/Users/yuanxi/Documents/New project/index.html` 读者端
- `/Users/yuanxi/Documents/New project/admin.html` 后台上传页
- `/Users/yuanxi/Documents/New project/quick_start.command` 一键启动（最简单）
- `/Users/yuanxi/Documents/New project/一步一步操作指南.md` 非技术用户操作手册
- `/Users/yuanxi/Documents/New project/app.js` 前端逻辑
- `/Users/yuanxi/Documents/New project/styles.css` 样式
- `/Users/yuanxi/Documents/New project/backend/server.py` 后端 API + 静态站点
- `/Users/yuanxi/Documents/New project/backend/unified_server.py` 统一入口（阅读器 + 生成器）
- `/Users/yuanxi/Documents/New project/backend/requirements.txt`
- `/Users/yuanxi/Documents/New project/start_backend.sh` 本地一键启动后端
- `/Users/yuanxi/Documents/New project/render.yaml` Render 固定网址部署配置
- `/Users/yuanxi/Documents/New project/固定域名部署清单.md` 固定域名上线清单

## 本地启动（推荐：完整后端模式）

```bash
cd '/Users/yuanxi/Documents/New project'
ADMIN_KEY='your-strong-key' ./start_backend.sh 5000
```

启动后：

- 读者端：`http://你的局域网IP:5000/`
- 后台端：`http://你的局域网IP:5000/admin`

## 后台上传规则

### 上传文件

- 支持 `.md` 或 `.json`

### Markdown 章节识别（固定模式）

仅识别 Markdown 标题里的章节：

- `# 第1章 ...`
- `## Chapter 2 ...`

规则：

1. 必须是 Markdown 标题行（`#` 到 `######`）
2. 标题文本匹配 `第X章` 或 `Chapter N`
3. 两个章节标题之间内容归属当前章节

### 手动配置闯关任务

后台上传页的“章节闯关任务”推荐这样填（不需要手填中文）：

```text
### 1章单词表
focus, logic, memory

### 2章单词表
purpose, feature, system
```

也兼容旧格式：

```text
1|focus|专注
1|logic|逻辑
2|memory|记忆
```

说明：

1. 不配置的章节 = 没有闯关任务
2. 只配置某些章节 = 只有这些章节有任务

## 给其他人最方便进入的方式

### 方案 A（最快）

把后端部署到云端，给读者一个网址即可打开，无需安装。

### 方案 B（微信内）

把云端网址放到公众号菜单/企微工作台，用户微信里直接打开 H5。

## 云端部署（固定网址 + 固定域名，Render 推荐）

本项目已提供 `render.yaml`，可直接按 Blueprint 部署，并默认启用统一入口 `backend/unified_server.py`（阅读器 + 生成器 + 后台）。

### 1. 一次性部署（固定 onrender 网址）

1. 把项目推到 GitHub。
2. Render -> `New` -> `Blueprint`，选择本仓库（自动读取 `render.yaml`）。
3. 在 Render 页面补充至少两个变量：
- `ADMIN_KEY`：后台管理员密钥（你自己设置）
- `AUTH_HASH_SECRET`：会话签名密钥（随机长字符串）
4. 点击 Deploy，等待完成。

部署后你会拿到一个固定地址（例如 `https://english-reader-story-lab.onrender.com`），后续每次更新代码，该地址不变。

### 2. 绑定你自己的固定域名

1. 在 Render 服务里打开 `Settings -> Custom Domains -> Add Domain`。
2. 输入你的域名（例如 `read.yourdomain.com`）。
3. 按 Render 给出的 DNS 记录，在域名服务商后台添加对应 `CNAME`。
4. 等待证书签发完成（HTTPS 自动）。

完成后，你可长期使用同一个正式域名（适合后续小程序业务域名配置）。

### 3. 线上访问入口

- 读者端：`https://你的固定域名/reader`
- 生成器：`https://你的固定域名/generator`
- 书架后台：`https://你的固定域名/bookshelf-admin`

## 自动化浏览器自测（E2E：自动打开网页/翻页/截图/报告）

你现在项目里自带一个“读者端自动化冒烟测试”脚本，会：

1. 自动启动一个本地服务（无需你手动开服务）
2. 用真实浏览器内核打开读者端
3. 自动进入第一本书、翻几页
4. 自动截图
5. 输出报告（Markdown + JSON）

### 0）第一次只需安装一次（macOS）

在终端执行（复制粘贴即可）：

```bash
cd '/Users/yuanxi/Documents/New project'
./.venv/bin/python -m pip install -r backend/requirements-dev.txt
./.venv/bin/python -m playwright install webkit
```

说明：`webkit` 更接近 iPhone 内核（iOS Safari）。

### 1）一条命令跑自测（推荐）

```bash
cd '/Users/yuanxi/Documents/New project'
./.venv/bin/python backend/e2e_reader_smoke.py
```

运行结束后，它会在 `reports/e2e_reader_smoke/时间戳/` 里生成：

- `report.md`（人类可读报告）
- `report.json`（机器可读数据）
- `screenshots/`（多张截图）

### 2）测试线上网站（可选）

如果你想测云服务器上的公网地址（例如 ECS 的公网 IP）：

```bash
cd '/Users/yuanxi/Documents/New project'
./.venv/bin/python backend/e2e_reader_smoke.py --base-url 'http://你的公网IP'
```

> 注意：线上测试不会帮你启动服务，只会对目标网址做自动化操作并截图。

## 小程序壳（可选）

已提供最小可用小程序壳目录：

- `/Users/yuanxi/Documents/New project/miniprogram`

按 `/Users/yuanxi/Documents/New project/miniprogram/README.md` 操作即可。

## 旧版纯静态本地验证

如果只想临时本机看页面（不走后台）：

```bash
cd '/Users/yuanxi/Documents/New project'
./start_mobile.sh 8080
```

这个模式不会有“统一后台书架同步”。

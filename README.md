# 英语小说阅读 App（读者端 + 后台上传）

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
- `/Users/yuanxi/Documents/New project/backend/requirements.txt`
- `/Users/yuanxi/Documents/New project/start_backend.sh` 本地一键启动后端

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

## 云端部署（Render 示例）

1. 新建 Git 仓库并推送本项目
2. Render 新建 `Web Service`
3. 运行命令：

```bash
pip install -r backend/requirements.txt
```

4. 启动命令：

```bash
python backend/server.py
```

5. 环境变量：

- `ADMIN_KEY=你自己的强密码`
- `PORT=10000`（Render 通常自动注入，可不手填）

部署完成后：

- 读者访问：`https://你的域名/`
- 管理员上传：`https://你的域名/admin`

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

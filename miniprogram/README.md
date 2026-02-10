# 小程序壳（WebView）

这是一个最小微信小程序壳，用 `web-view` 打开你的线上阅读站点。

## 使用步骤

1. 先把后端服务部署到 HTTPS 域名（例如 `https://reader.yourdomain.com`）
2. 在微信公众平台小程序后台把该域名加入「业务域名」
3. 用微信开发者工具打开本目录 `/Users/yuanxi/Documents/New project/miniprogram`
4. 修改 `/Users/yuanxi/Documents/New project/miniprogram/pages/index/index.js` 中的 `readerUrl`
5. 上传并提交审核

## 说明

1. 小程序里的核心阅读逻辑仍由 H5 提供，后台上传和全员同步能力在后端服务中实现
2. 读者端不可上传，后台通过 `/admin` 管理上传

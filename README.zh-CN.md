# LocalTube Dub：YouTube 中文翻译与配音

[English](README.md) | 简体中文

一个开源 Chrome 扩展，可以把 YouTube 视频字幕翻译成中文，并在原视频时间轴上播放同步中文配音。

LocalTube Dub 会优先读取 YouTube 已有的中文字幕；没有中文字幕时，再使用 Chrome 免费本地翻译或用户自己选择的翻译服务。没有字幕的视频可以使用可选的本地 Whisper Engine 转写。

> **当前版本：** `0.1.97` 开发预览版。Chrome 插件商店版本和已签名的桌面 Engine 安装包正在准备中。

## 主要功能

- 优先使用 YouTube 已有中文字幕，避免不必要的翻译调用。
- 支持 Chrome 端侧免费翻译，不需要 API Key。
- 支持用户自己的 Microsoft、Google、OpenAI、Gemini、Claude、DeepSeek、OpenRouter 等 API Key。
- 中文字幕和中文配音跟随视频播放、暂停、跳转和倍速。
- 支持 Microsoft 自然在线音色和 macOS 本地系统音色。
- 可选用 yt-dlp、FFmpeg 和 whisper.cpp 在本地转写无字幕视频。
- 可以导出 SRT/WebVTT 字幕和 M4A/WAV 配音音轨。
- API Key 保存在本机；项目没有 LocalTube 账号、广告、统计、订阅或支付系统。

## 工作方式

1. 先读取 YouTube 为当前视频提供的中文字幕。
2. 没有中文字幕时，使用 Chrome 本地翻译或用户选择的翻译 Provider。
3. 视频完全没有字幕时，可选择本地 Whisper 或自己的转写 Provider 处理一小段当前视频音频。
4. 把翻译字幕和配音按原字幕时间轴同步到视频。

## 从源码体验

1. 在 Chrome 打开 `chrome://extensions`。
2. 开启右上角的“开发者模式”。
3. 点击“加载已解压的扩展程序”，选择项目中的 `extension/` 文件夹。
4. 打开一个 YouTube 视频，选择目标语言并点击“开始翻译”。

基础的页面字幕翻译可以不安装 Engine。为了更稳定地使用 yt-dlp 读取字幕、自然/本地配音、无字幕转写和音轨导出，推荐安装配套 Engine，具体步骤见 [Engine 安装说明](companion/README.md)。

## 隐私说明

- 非敏感设置可以通过 Chrome Sync 同步。
- API Key 和字幕缓存保存在扩展本地存储中。
- 只有用户主动选择云端 Provider 后，数据才会发送到该 Provider。
- Microsoft 自然在线语音只接收合成语音所需的翻译文本和音色设置。
- 本地系统语音和本地 Whisper 转写在用户电脑上处理。

完整说明请阅读公开的 [隐私政策](https://kk-kingkong.github.io/video-dub/privacy-policy.html) 和 [Chrome 权限说明](docs/chrome-web-store-permissions.md)。

## 开发验证

```bash
node tools/verify_extension_flows.js
node tools/verify_provider_registry.js
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py
python3 tools/verify_open_source_compliance.py
```

## 项目文档

- [English README](README.md)
- [项目主页](https://kk-kingkong.github.io/video-dub/)
- [使用支持](https://kk-kingkong.github.io/video-dub/support.html)
- [Engine 安装说明](companion/README.md)
- [隐私政策](docs/privacy-policy.md)
- [Chrome 商店权限说明](docs/chrome-web-store-permissions.md)
- [发布流程](docs/release-process.md)
- [更新日志](CHANGELOG.md)
- [参与贡献](CONTRIBUTING.md)
- [安全报告](SECURITY.md)

## 当前限制

- 公开版 macOS Engine 尚未完成签名和公证。
- Windows Engine 正式安装程序尚未完成。
- 混合音轨不会自动分离原视频对白和背景音。
- 暂不包含最终视频合成和声音克隆。

## 开源许可

项目使用 Apache-2.0 许可证，详见 [LICENSE](LICENSE) 和 [第三方组件说明](THIRD_PARTY_NOTICES.md)。

LocalTube Dub 与 Google、YouTube、Microsoft 及支持的 AI Provider 没有隶属、赞助或官方合作关系。使用者需要自行遵守平台条款、版权规则、声音授权要求和当地法律。

---
layout: default
title: LocalTube Dub
---

# LocalTube Dub

An open-source Chrome extension for translating YouTube captions into Chinese and playing synchronized Chinese dubbing.

[Chrome Web Store](https://chromewebstore.google.com/detail/localtube-dub/ikoenamldegccnhmjjnlkffocdkbbbmo) | [Source code](https://github.com/Kk-kingkong/video-dub) | [Privacy policy](privacy-policy.html) | [Support](support.html) | [Security](https://github.com/Kk-kingkong/video-dub/security/policy)

## What it does

- Uses an existing Chinese YouTube caption track when one is available.
- Otherwise translates source captions with Chrome on-device translation or a Provider selected by the user.
- Plays translated subtitles and speech on the original video timeline.
- Optionally uses the local Engine for yt-dlp caption extraction, local transcription, offline Kokoro speech, and export.

Microsoft natural online speech remains the default. Kokoro is an explicit optional model download that synthesizes Chinese and English on the same computer. The packaged Engine supports macOS Apple Silicon, macOS Intel, and Windows 10/11 x64; the current desktop packages are unsigned development builds.

Engine `0.2.8` is a one-time manual upgrade for existing users. It then checks signed compatible stable updates during use and installs when idle, preserving settings and models. Chrome manages Store extension updates; unpacked extensions still need manual updates. See [update and migration help](support.html). The update signature does not replace operating-system code signing or macOS notarization.

LocalTube Dub has no account system, subscription, advertising, analytics, payment processing, or hosted translation backend. Install the extension from the Chrome Web Store or use source and Engine packages published by this repository.

## 简体中文

LocalTube Dub 是一个开源 Chrome 扩展，用于把 YouTube 字幕翻译成中文，并在原视频时间轴上播放同步中文配音。

- 优先使用 YouTube 已有的中文字幕。
- 没有中文字幕时，使用 Chrome 端侧翻译或用户自己选择的翻译服务。
- 中文字幕和配音会跟随视频播放、暂停、跳转和倍速。
- 可选的本地 Engine 提供 yt-dlp 字幕提取、本地转写、离线 Kokoro 配音和导出能力。

Microsoft 自然在线配音仍是默认选项。Kokoro 需要用户主动下载可选模型，之后中英文配音都在同一台电脑上生成。Engine 支持 macOS Apple Silicon、macOS Intel 和 Windows 10/11 x64；当前桌面安装包仍是未签名的开发版本。

旧用户手动安装一次 `0.2.8` Engine 后，实际使用时会检查经过签名的兼容正式版，并在空闲时安装，保留设置和模型。商店扩展由 Chrome 更新，已解压扩展仍需手动更新，详见[升级与迁移说明](support.html)。更新签名不等同于操作系统代码签名或 macOS 公证。

项目没有账号、订阅、广告、统计、支付或托管翻译后台。请从 Chrome 插件商店安装扩展，或只使用本仓库发布的源码和 Engine 安装包。

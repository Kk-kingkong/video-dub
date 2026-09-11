---
layout: default
title: LocalTube Dub Support
---

# LocalTube Dub Support / 使用支持

[Home / 主页](index.html) | [Privacy / 隐私政策](privacy-policy.html) | [Source / 源码](https://github.com/Kk-kingkong/video-dub)

## Updates / 版本更新

Customers with an older Engine must install the matching platform's `0.2.8` Engine once from [GitHub Releases](https://github.com/Kk-kingkong/video-dub/releases). After that, Engine checks signed compatible stable updates when it starts for actual work, at most once per six hours, and installs after tasks finish at the idle boundary. Failed activation restores the previous runtime. Settings, models, and existing extension bindings are retained. Merely restarting an older Engine does not install the updater.

旧版 Engine 用户需要先从 [GitHub Releases](https://github.com/Kk-kingkong/video-dub/releases) 下载对应平台的 `0.2.8` Engine 并手动安装一次。此后实际使用启动时会自动检查经过签名的兼容正式版，每六小时最多检查一次；任务结束并空闲后才安装。失败时恢复旧版，保留设置、模型和已有扩展绑定。只重启旧 Engine 不会把更新器装进去。

Chrome handles extensions installed from the same Store item after review and publication. Unpacked/source/ZIP extensions still need manual replacement in the original directory and reload. If an unpacked extension's directory changes, its ID can change too; use the installation page's current-ID repair instructions. Automatic Engine updates preserve registered IDs but cannot predict a new extension ID.

从同一个 Chrome 商店条目安装的扩展，由 Chrome 在审核发布后更新。源码或 ZIP“加载已解压”的扩展仍需覆盖原目录并重新加载；目录变化可能导致扩展 ID 变化，需要按安装页提示重新绑定。Engine 自动更新会保留已有绑定，但无法预先知道新扩展的 ID。

The update-feed signature is separate from platform code signing. Current Engine installers still lack macOS/Windows code signing and macOS notarization, so operating-system warnings may appear. Offline computers and busy Engines update later rather than immediately at publication.

更新信息的签名与系统代码签名不同；目前安装包尚未完成 macOS/Windows 代码签名及 macOS 公证，仍可能出现系统提示。离线电脑和仍有任务的 Engine 会稍后更新，不会在发布瞬间同时升级。

## Get help / 获取帮助

Use the [GitHub issue tracker](https://github.com/Kk-kingkong/video-dub/issues/new/choose) for reproducible bugs, setup questions, and feature requests.

如需报告可以复现的问题、安装疑问或功能建议，请使用 [GitHub Issues](https://github.com/Kk-kingkong/video-dub/issues/new/choose)。

Please include:

- the extension version shown in the popup;
- Chrome and operating-system versions;
- whether the optional Engine is installed and its platform/architecture;
- the selected speech engine (Microsoft natural online, Kokoro, or macOS system speech); and
- concise reproduction steps and the visible error category.

请附上扩展版本、Chrome 与操作系统版本、Engine 是否安装及其平台/架构、当前配音引擎、简短复现步骤和页面显示的错误类别。

Never publish API keys, YouTube cookies, private captions, generated audio, account information, or full local file paths. Report security vulnerabilities through the repository's [private security process](https://github.com/Kk-kingkong/video-dub/security/policy).

请不要公开 API Key、YouTube Cookie、私人字幕、生成音频、账号信息或完整本地路径。安全漏洞请使用项目的[私密安全报告流程](https://github.com/Kk-kingkong/video-dub/security/policy)。

LocalTube Dub is community-maintained software. Support and response times are not guaranteed.

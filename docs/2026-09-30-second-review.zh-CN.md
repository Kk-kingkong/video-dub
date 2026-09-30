# LocalTube Dub 第二轮独立审查

审查日期：2026-09-30。对象为 **0.2.8 当前工作区（HEAD `5f8884a` 加上一轮未提交修复）**，不是仅审查 HEAD。审查前 AOCI 122 条完整交付，Challenge 10/10、一致性检查通过；按前端、后台/Native、更新与安装分别审阅，并对发现做隔离复现。

初审确认 **9 项问题：1 项 P1、8 项 P2**，随后按用户“修复”指令完成修复及回归。以下九节保留修复前证据和当时行号；当前结果见末尾“修复与验收”。未提交、发布或安装到用户实际配置。

## 1. P1：撤回在线配音同意后，旧标签页仍能创建 Edge 整轨

位置：[background.js:1749](/Users/kk/Documents/code/localtube-dub/extension/background.js:1749)，关联 [popup.js:1091](/Users/kk/Documents/code/localtube-dub/extension/popup.js:1091) 和 [content.js:2918](/Users/kk/Documents/code/localtube-dub/extension/content.js:2918)。

- 触发：打开多个视频页，在当前页撤回 Microsoft 在线配音同意，再在保留旧设置的另一页生成整轨。设置通知仅发送到当前活动标签，其他页没有 storage 变更订阅。
- 根因：`startDubTrack` 合并来页设置后直接向 Engine 提交，没有像单段 `synthesizeSpeechWithEngine` 一样独立核对持久化同意。页面自身检查依赖旧快照。
- 复现：持久化 `microsoftTtsConsent=false`、来页旧设置为 true，真实后台函数仍返回成功并提交 `ttsEngine=edge` 及字幕正文。
- 影响：撤回同意后仍可能向 Microsoft 发送整段字幕；正在其他页生成的任务也不会收到本页撤回通知。
- 修复方向：在整轨后台入口读取当前持久化同意并拒绝未授权提交；同意撤回应通知所有相关页、取消其在线任务，不能仅依赖当前标签页。

## 2. P2：请求收到响应头后，超时和取消不再约束响应体

位置：[background.js:3105](/Users/kk/Documents/code/localtube-dub/extension/background.js:3105)，关联 [background.js:3072](/Users/kk/Documents/code/localtube-dub/extension/background.js:3072)。

- 触发：Engine 或 Provider 已返回响应头，但 JSON 正文持续缓慢发送或停住；随后到达请求期限或用户取消。
- 根因：`fetchWithTimeout` 在 `fetch()` 返回 Response 后立即清除计时器并移除外部 abort 监听，而调用方随后才执行 `response.text()`/JSON 读取。
- 复现：真实随机回环 HTTP 服务发送响应头和半段 JSON 后停住；配置 40ms 超时，120ms 后仍未结束，再显式 abort 后等待 60ms 仍未结束。
- 影响：健康检查、字幕、翻译等请求会超过自身期限，取消也不能及时终止正文读取；请求与状态可能持续挂起。
- 修复方向：把完整响应体消费纳入同一超时/取消生命周期，读取结束后再清理。

## 3. P2：YouTube 自动翻译字幕被误认成原始语言并污染缓存

位置：[content.js:5372](/Users/kk/Documents/code/localtube-dub/extension/content.js:5372)。

- 触发：播放器此前捕获 `lang=en&tlang=es` 的自动翻译字幕，扩展目标为 `en-US`。
- 根因：捕获正文的语言只取 `lang`，忽略决定实际正文语言的 `tlang`；page probe 的缓存也会直接返回该视频已有捕获结果。
- 复现：用真实 page probe 事件链与 `startDubbing`，西语正文 `Hola, buenos días.` 被标为英语；`skipTranslation=true`、翻译调用数为 0，并以 `targetLanguage=en-US`、`provider=youtube-captions` 保存。
- 影响：用户获得错误语言字幕及配音；之后的持久缓存命中可继续复现，不只是本次页面显示错误。
- 修复方向：优先使用实际翻译语言 `tlang`，并核对捕获轨道身份；为已有受污染字幕缓存制定失效处理。

## 4. P2：播放位置补翻失败后会无退避地重复请求

位置：[content.js:3625](/Users/kk/Documents/code/localtube-dub/extension/content.js:3625)。

- 触发：视频当前段缺少译文，Ollama 不可用、Provider 鉴权失败或持续返回错误。
- 根因：失败只更新提示，清理 pending/priority 标记后，下一次同步帧又满足补翻条件；没有终止性错误分类、退避或等待用户重试。
- 复现：真实补翻函数与 Provider 消息路径持续返回错误，8 次同步帧产生 8 次请求，`running` 保持 true。
- 影响：连续重复调用、状态闪烁；可能加重限流和服务负担。这里没有宣称固定的每秒请求数，实际速率受网络往返约束。
- 修复方向：永久错误停止自动补翻，可恢复错误采用有上限的退避，并在配置变更或主动重试时重置。

## 5. P2：弹窗较早的保存响应会覆盖较新的选择

位置：[popup.js:842](/Users/kk/Documents/code/localtube-dub/extension/popup.js:842)。

- 触发：用户快速连续调整语言等设置，第一笔保存响应晚于第二笔返回。
- 根因：`saveFromForm` 不检查请求代次；每个成功响应都会 `render` 并再次通知当前视频页。
- 复现：真实后台 `saveSettings` 和 `buildSettingsResponse`，只延迟第一笔 Chrome storage 读取；保存顺序为日语→德语，持久设置已是德语，旧响应最终把弹窗及发往当前页的设置恢复为日语。
- 影响：界面、当前播放页和持久设置不一致，用户的最后一次选择被旧结果覆盖。
- 修复方向：统一保存代次/归属，只有最新保存可更新界面及发送设置通知；同时处理权限请求阶段的乱序。

## 6. P2：Kokoro 降级音色的保存回包可恢复整份旧设置

位置：[content.js:4557](/Users/kk/Documents/code/localtube-dub/extension/content.js:4557)。

- 触发：Kokoro 某音色失败后保存替代音色；等待保存响应时用户切换目标语言和音色。
- 根因：`applyKokoroVoiceFallback` 在 await 前检查请求音色，但返回后无归属检查地合并整份保存结果；绕过了上轮为浮层普通保存增加的保护。
- 复现：用户已改为 `en-US / af_heart`，迟到回包又恢复为 `zh-CN / zf_xiaobei`，operation 仍为 8。
- 影响：新任务重新采用旧语言或错误音色，而任务代次没有反映这次逆向变化。
- 修复方向：绑定设置快照、目标语言和播放代次；迟到保存结果不得回写新任务，自动音色降级也不应合并无关旧设置。

## 7. P2：组装 WAV 时取消任务，最终仍被写成完成

位置：[local_dub_server.py:1791](/Users/kk/Documents/code/localtube-dub/server/local_dub_server.py:1791)。

- 触发：生成 WAV 音轨时在约 93% 的组装阶段点击取消；此阶段真实界面仍提供取消按钮。
- 根因：只在组装前检查取消，组装之后无条件提交 `completed`；取消与最终完成不是同一锁内的互斥状态转换。
- 复现：真实 worker、真实 WAV 写入，外部 TTS 用临时音频替代。取消 API 返回 `cancelled`，最终状态却为 `completed`，文件与下载地址都存在。
- 影响：后台保留并可复用用户已取消的产物，违背取消状态；前端的代次保护只阻止旧回包更新 UI，不能纠正服务端状态。
- 修复方向：最终提交与取消原子互斥，取消后清理输出；仅在提交前增加一个不持锁的检查仍有竞态。

## 8. P2：完整转写和整轨生成可以并发绕过重任务互斥

位置：[local_dub_server.py:1235](/Users/kk/Documents/code/localtube-dub/server/local_dub_server.py:1235) 与 [local_dub_server.py:1470](/Users/kk/Documents/code/localtube-dub/server/local_dub_server.py:1470)。

- 触发：两个标签页同时启动完整转写和整轨生成。
- 根因：两个入口分别持锁检查另一类任务，再释放该锁并用自身锁入队；“检查所有重任务并登记当前任务”不是一个原子步骤。
- 复现：实际 start 函数和锁，在合法的锁释放间隙安排线程交错；两个入口均返回成功，两个任务均为 queued。重计算 worker 为替身。
- 影响：绕过现有 `HEAVY_ENGINE_JOB_BUSY` 资源保护约定，本地重计算可能同时运行。未把资源争用夸大为已验证的崩溃或数据损坏。
- 修复方向：共享一个检查与登记的临界区，或统一锁顺序后在同一临界区完成准入。

## 9. P2：手工安装失败回滚会丢失原扩展绑定

位置：[macOS 安装器:43](</Users/kk/Documents/code/localtube-dub/packaging/macos/Install LocalTube Dub Engine.command.in:43>)；Windows 同类链路在 [install-engine.ps1.in:231](/Users/kk/Documents/code/localtube-dub/packaging/windows/install-engine.ps1.in:231)。

- 触发：旧 Engine 已绑定扩展 A+B，手动为扩展 C 安装新版，在激活阶段失败。
- 根因：手动回滚先移除原 Native manifest，再使用本次扩展 ID 注册恢复的运行时；只有自动更新模式备份并恢复原注册字节。Windows 手动路径同样先删除注册和 manifest 再重建。
- 复现：macOS 真实安装模板、manifest 注册器和卸载器，只操作临时目录；依赖及启动步骤用替身。运行时恢复为 0.2.7，但授权从 A+B 变为仅 C。
- 影响：安装虽然报告回滚，之前可用的扩展仍会遭 Native Host 拒绝。
- 修复方向：手动安装也保存原注册内容及存在性，失败时精确恢复。Windows 当前仅完成源码确认，未作实机复现。

## 本轮验证与限制

以下 **7 项现有检查重新执行并通过**：

- `node tools/verify_extension_flows.js`
- `node tools/verify_translation_integrity.js`
- `node tools/verify_engine_lifecycle.js`
- `node tools/verify_provider_registry.js`
- `.venv/bin/python tools/verify_engine_updates.py`
- `.venv/bin/python tools/verify_update_publication.py`
- `.venv/bin/python tools/verify_windows_package.py --source`

这些通过结果未覆盖上述新缺陷，不能据此认为软件没有 bug。上轮的 14 项结果是上轮证据，本轮没有把它们全部重新运行后计数。

根代理分别复跑以下隔离脚本，确认全部 9 项发现；脚本中的断言用于证明缺陷仍存在，不是证明修复成功：

| 脚本 | 复现范围 |
| --- | --- |
| `/private/tmp/localtube-second-review-root.cjs --http` | 在线同意、真实前后台设置回包乱序、真实回环 HTTP 响应体超时/取消 |
| `/private/tmp/localtube-round2-content-repro.cjs` | page probe→字幕启动→错误语言缓存、播放补翻重试、Kokoro 旧设置回包 |
| `/private/tmp/localtube-backend-second-review.py` | 取消覆盖与跨类重任务并发准入 |
| `/private/tmp/localtube-review-installer-rollback.py` | macOS 手动安装失败后原绑定丢失 |

临时脚本可能被系统清理，修复时应将这些场景加入对应现有回归脚本。所有模型、音频、安装及测试 HTTP 路径均隔离；没有调用生产 TTS/Whisper、付费 Provider，没有改用户实际 Engine 或 Native 注册。没有执行真实 Chrome/YouTube 全链路、Windows 实机安装或 GitHub 发布。

初审阶段仅新增审查报告；后续修复记录如下。


## 修复与验收（2026-09-30）

九项问题均已修复，产品版本仍为 0.2.8。修复保留上轮已有改动，没有增加依赖。

| 问题 | 当前行为及回归证据 |
| --- | --- |
| 1 在线同意 | 整轨入口独立读取持久同意；撤回广播到所有 YouTube 页并接入取消流程。只有弹窗或浮层同意复选框的明确操作允许修改同意，普通旧设置快照不能重新授权。交叉复查补上撤回无需等待无关权限请求的边界，避免音量保存淘汰尚未提交的撤回。生命周期、弹窗及浮层测试覆盖拒绝、广播、明确授权、旧快照和权限竞态。 |
| 2 响应体取消 | 四类调用方共用的超时函数在读完正文后才移除定时器和 abort 监听。真实 Response 流及随机回环 HTTP 半段 JSON 均验证超时和主动取消，成功响应及连接失败行为保留。 |
| 3 字幕身份 | 捕获正文按 `tlang || lang` 识别实际语言。真实 page probe→字幕启动→翻译/缓存测试覆盖目标匹配与不匹配；缓存格式升至 3，旧 v1/v2 条目清除，设置与凭证保留。 |
| 4 补翻重试 | 可恢复错误冷却 10 秒，连续三次失败后暂停；鉴权、权限和配置错误立即暂停。主动跳转可重试，成功/停止重置；旧任务失败不能污染新任务。 |
| 5 弹窗乱序 | 保存、模式切换、服务验证及平台归一化共用保存代次。过期权限结果不再提交，过期响应和标签查询不再更新页面；回归覆盖晚回保存、权限等待及明确同意标记。 |
| 6 Kokoro 回退 | 请求校验任务、语言、引擎和音色；自动回退不再合并整份后台设置。保存期间新设置取代旧设置时，迟到结果和旧音频均被丢弃；真实配音队列回归通过。 |
| 7 取消终态 | 完成提交和取消使用同一任务锁；已取消任务不能再完成或被晚到进度覆盖，音轨输出清理。同根因的完整转写提交也受保护；测试覆盖真实 WAV 写入、最终提交及转写解析之后取消。 |
| 8 重任务准入 | 两个入口采用一致锁序，在同一临界区检查并登记；取消后直到 worker 退出才释放工作槽，过期清理也不能提前移除。确定性交错、取消排空及清理回归通过。 |
| 9 安装回滚 | 两平台手动安装也快照注册并恢复原存在性和字节；Windows 保留默认注册值原数据/类型及其他值和子键。macOS 隔离真实安装覆盖四种运行时/manifest 存在组合；Windows 新场景加入既有 CI smoke。 |

本次重新执行并通过 **14 项项目检查**（与初审七项分开计数）：

- Node：`verify_extension_flows`、`verify_translation_integrity`、`verify_engine_lifecycle`、`verify_provider_registry`。
- Python：`verify_kokoro_engine`、`verify_local_engine`、`verify_engine_lifecycle`、`verify_native_messaging`、`verify_update_integration`、`verify_engine_updates`、`verify_update_publication`、`verify_release_packages --self-test`、`verify_open_source_compliance`、`verify_windows_package --source`。

另通过 JavaScript/Python/Bash 语法检查、`git diff --check`，以及真实随机回环 HTTP 半段响应取消检查。修复后按前端/后台交叉复查；未发现本轮修复引入的新阻塞问题。

验证过程保留一项不稳定现象：发行包健康自测有两次临时服务启动超时；诊断六种场景均在约 0.1 秒内响应，未修改正式超时或源码后，正式 `--self-test` 复跑通过。不能据此承诺所有机器的启动时序稳定。

验收范围仍为源码、替身及隔离运行测试：没有运行生产模型或付费服务、真实 Chrome/YouTube 播放、Windows 实机安装，也没有提交或发布。Windows 新增真实安装 smoke 需在现有 Windows CI 执行；本机通过的是 `--source`，不能替代实机结果。

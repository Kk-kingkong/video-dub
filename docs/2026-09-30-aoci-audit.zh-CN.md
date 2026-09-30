# LocalTube Dub 接手、AOCI 索引与代码审查

审查日期：2026-09-30。基线：`codex/fix-repeated-voice-playback`，提交 `5f8884a`，扩展及 Engine 版本 `0.2.8`。

首次审查完成项目接手、AOCI 建档、现有检查和定向缺陷复现，发现 **1 项 P1、8 项 P2**，其中 7 项有隔离复现，2 项由发布/验证控制流确认。用户随后授权先优化、再复查修复；当前修复结果见文末。下面缺陷描述及行号保留初次审查基线，不能当作修复后的源码位置。没有提交、推送、发版或替换用户已安装的 Engine。

## 接手与索引

- 已读取 `_视频翻译插件—new` 及后续 `修复视频翻译插件语音重复` 的开发记录，并以当前源码核对。后续聊天已推进到 0.2.8，不能把原聊天的 0.2.5 当作当前版本。
- 核心链路为 Chrome MV3 扩展 → 本地 HTTP / Native Messaging → Python Engine；字幕优先，必要时转写，支持实时配音、整轨导出及签名 Engine 自动更新。
- 使用 `0.1.0-rc8-local.curation.1` 建立 `aoci.txt`、`aoci.meta.txt`、`aoci.code.txt` 和 `.aoci/` 治理资产；项目 `AGENTS.md` 已接入后续认知读取及维护流程。
- 初始 120 条文件认知覆盖源代码、测试、交付脚本、配置、文档及经人工审阅纳入的 9 张 PNG 和公钥证书。生成的安装包、私有环境、模型及机器配置按忽略规则排除。加上本报告，最终管理范围为 121 条。
- 初始全量 Overview 分 3 块交付，120/120 条，约 15,672 tokens；Challenge 10/10。机器覆盖率 100% 与系统框架掌握度自评 92% 是不同指标，均不代表真实浏览器/所有平台运行验收。
- 索引结构及治理一致性使用 `verify`、`check`、实时 Guide 检查；本报告纳入后再次完成增量维护和校验。AOCI 可执行文件保存在忽略的 `.local/aoci/`，Codex MCP 配置保存在忽略的 `.codex/config.toml`。

## 缺陷与修复优先级

P1：应在下一次对外发行前处理。P2：明确的行为、边界或验证缺陷，应进入近期修复。

### 1. [P1] 本地 HTTP 副作用接口没有请求来源校验

位置：`server/local_dub_server.py:515–535`、`:622–644`。

HTTP 处理器没有校验 Origin、Host 或客户端身份，`read_json` 也会解析 `text/plain` 请求体；响应统一使用 `Access-Control-Allow-Origin: *`。模型安装、卸载及 Engine 重启等操作都经过该入口。Native Messaging 的扩展授权名单不能约束直连 HTTP 的请求。

**复现：** 在随机回环端口启动真实处理器，仅创建临时合成模型。携带不可信 Origin/Host、`Content-Type: text/plain` 的卸载请求返回 200，合成模型确实被删除。本次没有让真实网页穿过浏览器本地网络权限限制，因此不能据此断言所有浏览器都可直接利用；已证实的是服务端信任边界缺失。

**修复方向：** 在共享 HTTP 入口验证允许的 Host、Origin 和客户端凭据，覆盖所有副作用路由，并兼容已授权扩展及 Native 内部调用。仅收紧 CORS 响应头不足以阻止简单跨站 POST。增加一个真实 HTTP 拒绝不可信请求的回归测试。

### 2. [P2] 简繁中文字幕命中同一份 Engine 缓存

位置：`server/local_dub_server.py:957–963`；现有正确的字幕语言归一化函数位于 `:3061`。

`caption_cache_key` 使用只保留主语言的 `normalize_language_code`，把 `zh-CN` 与 `zh-TW` 都变成 `zh`；字幕选择逻辑却明确区分二者。成功缓存、失败退避及并发请求合并均复用这个键。

**复现：** 同一视频先请求 `zh-CN`、再请求 `zh-TW`，第二次返回 `cache=true` 和 `sourceLanguage=zh-CN`，提取函数只被调用一次。成功缓存默认一小时，可能持续返回错误文字体系。

**修复方向：** 复用已有 `normalize_caption_language_identity` 构造字幕缓存身份；同时覆盖简繁和葡语变体，以及并发/失败缓存分支。

### 3. [P2] 弹窗改语言后旧翻译任务仍运行

位置：`extension/content.js:264–281`；对照浮层处理 `:1213–1227`；消息发送在 `extension/popup.js:826–849`、`:1091–1097`。

弹窗的 `settingsChanged` 只合并配置，只有关闭扩展才停止任务；视频浮层改语言或 Provider 却会停止旧任务。视频正在翻译中文时，通过弹窗改为日文，页面操作代次不变、旧中文字幕保留，后续批次可能读取新配置，造成语言混用。

**复现：** Node VM 执行真实监听器，发送日文目标语言后得到 `{running:true, operationId:42, target:'ja-JP', translation:'你好'}`。

**修复方向：** 两个入口复用同一设置变更处理逻辑；翻译输入变化时使旧任务和字幕失效，音色/导出输入变化时使对应音频任务失效。

### 4. [P2] 取消生成时尚未收到 jobId，晚到任务会继续后台运行

位置：`extension/content.js:2902–2933`、`:3006–3022`；完整转写同类路径位于 `:2679–2720`、`:2836–2851`。

创建音轨请求返回前按取消，页面还没有 jobId，因此不会发送 Engine 取消请求。创建响应晚到时，主播放 operationId 仍有效，旧 jobId 被写回；轮询因 rendering=false 退出，Engine 的合成/混音继续。重新开始任务时，旧响应还可能覆盖新任务身份。

**复现：** 阻塞真实创建函数的消息响应，先取消，再返回 jobId；结果保留晚到 jobId、rendering=false，取消消息数量为 0。

**修复方向：** 整轨及完整转写各使用自己的任务代次；取消使其失效，晚到的创建响应必须主动取消对应 Engine 作业；每次轮询回包都核对自身 jobId。

### 5. [P2] 一个标签页取消转写会停止另一个标签页录音

位置：`extension/background.js:2006–2026`、`extension/offscreen.js:1–5`。

`cancelTabAudioRecording(requestId)` 在取消请求后，无条件发送不含 requestId/tabId 的 offscreen 全局停止消息；offscreen 只保存一个全局 activeRecording。A 页停止本地转写时，会取消 B 页正在使用 tabCapture 的录音，即使 A 不拥有该录音。

**复现：** VM 中请求 A 取消后发出 `{type:'localtube.offscreenCancelTabAudio'}`，没有录音身份；真实 offscreen 监听器无条件停止当前录音。本次未做双标签真实浏览器录音测试。

**修复方向：** 录音开始、结束、取消全程携带并核对拥有者身份；第二个录音请求明确排队或拒绝，避免静默抢占。

### 6. [P2] 多标签并发保存字幕缓存会丢更新

位置：`extension/background.js:548–594`。

字幕缓存以单一 storage key 保存整个数组，保存、查询裁剪、清空之间没有串行协调。两次读取相同旧快照后分别写回，后者覆盖前者；查缓存的写回也可能覆盖刚保存的新条目。

**复现：** 同时保存 video-A、video-B，屏障让两次读取都拿到空缓存；两者都报告 `saved=true`，最终只剩 video-B。用户下次打开视频会重复翻译，可能增加等待和外部服务调用。

**修复方向：** 在后台用同一个 Promise 队列串行执行该 key 的全部读改写及清空；查询未产生裁剪变化时不写回。用并发保存和保存/查询交错测试覆盖。

### 7. [P2] 字幕入口没有验证 YouTube URL

位置：`server/local_dub_server.py:825–835`、`:884`、`:2552–2554`。

字幕入口只验证 URL 非空，随后传入 yt-dlp 提取层；同项目的视频转写已有 `is_supported_youtube_url` 边界。当前代码会接受与产品范围无关的地址。

**复现：** 将回环地址作为 videoUrl，确认该地址原样到达提取函数；在提取层用替身中止，没有访问实际内网或第三方服务。因此这是已确认的输入校验缺失，尚未证明可读取任意内网内容。

**修复方向：** 在缓存及提取前复用现有 YouTube URL 校验，明确拒绝非预期协议和域名；命令行 URL 参数使用明确的位置参数边界。

### 8. [P2] 自动更新发布校验发生在资产公开之后

位置：`.github/workflows/publish-engine-update.yml:3–9`、`:40–48`；`server/engine_updates.py:25–26`、`:326–348`；`tools/sign_engine_update.py:35–96`。

工作流仅在 `release.published` 后运行，只有读权限。发现对应提交没有成功 CI 时只是让工作流失败；客户端已经能从 latest 下载合法签名清单并接受兼容包。签名工具本身也不验证远端 CI。

**证据：** 工作流触发时机、权限及更新器接受条件的源码链路一致。没有创建/发布故障 Release。这不是签名绕过；发布文档虽要求提前验证，自动化本身仍只有事后检测，不能防止遗漏手工步骤。

**修复方向：** 在稳定 Release 对外可见或更新清单进入可信源之前完成精确提交的 CI、包及签名校验，再晋升发布；保留发布后的复核作为补充。

### 9. [P2] macOS 安装冒烟可能把能力检查失败判成成功

位置：`tools/smoke_release_macos.sh:184–194`。

轮询要求协议 ≥2 且 ytDlp、edgeTts 可用，但循环耗尽后只检查 HTTP 请求成功。一个一直返回 200、但能力不满足要求的服务仍会通过最后判断；固定 18787 端口且没有核对实例和运行目录，也可能检查到无关进程。

**证据：** Shell 分支控制流检查；没有把完整发行包重新安装到用户环境。

**修复方向：** 保存严格健康检查成功标记，耗尽后明确失败；验证版本、运行目录和实例身份，复用现有安装器健康校验要求。

## 优化空间

1. **优先减少健康检查的重复目录遍历。** `build_health_payload` 分别读取模型服务和推理运行时状态，两者再次验证并统计模型文件。包装真实 `_active_payload_stats` 的隔离测试测得单次 health 调用遍历 **4 次**；生产模型清单为 377 个文件。先复用一次状态快照；若进一步缓存，安装/卸载/失败时必须失效，不能丢掉完整性检查。尚未测量实际 CPU 或延迟收益。
2. **给字幕失败缓存增加过期清理和上限。** `server/local_dub_server.py:992–1010` 只在同一键再次查询时删除过期条目。写入 1,000 个失败、推进时钟再写一个，仍有 **1,001 条**。成功缓存已有 24 条上限，可复用该策略；Engine 默认空闲退出使实际风险较低。
3. **长视频预取从当前段开始。** `extension/content.js:4540–4557` 在动画帧中从头扫描音段；可复用现有二分定位或当前位置游标。`hasTranslatedCue` 在 `:3638–3639` 的重复线性查询也可在分析确认瓶颈后改为 cueKey Set。这两项仅有复杂度依据，尚无生产性能测量。
4. **补行为测试，避免继续增加源码字符串断言。** 现有测试大量覆盖 helper 和源码接线，遗漏上述配置切换及并发时序。先为这些复现补最小行为回归；真实 Chrome 媒体验收和 Windows 安装验收仍要保留。

待进一步确认：HTTP TTS 超时后直接走 Native 的回退可能重复执行昂贵合成；尚未完成端到端复现，不计入上述 9 项缺陷。

## 本次验证与边界

现有 **14 项检查最终通过**：

| 类别 | 执行检查 |
| --- | --- |
| JavaScript | `verify_extension_flows.js`、`verify_provider_registry.js`、`verify_translation_integrity.js`、`verify_engine_lifecycle.js` |
| Python | `verify_kokoro_engine.py`、`verify_local_engine.py`、`verify_engine_lifecycle.py`、`verify_engine_updates.py`、`verify_update_integration.py`、`verify_update_publication.py`、`verify_native_messaging.py`、`verify_release_packages.py --self-test`、`verify_open_source_compliance.py`、`verify_windows_package.py --source` |

另完成 22 项 JS/Python/Shell 语法检查。需要真实回环监听的 Native 和生命周期测试在获准的隔离环境复测成功；FFmpeg 已存在，相关真实混音/编码路径没有因为缺少 FFmpeg 被跳过。

定向复现输出：

```text
CACHE_COLLISION requested=zh-TW returned=zh-CN extractCalls=[zh-CN]
CROSS_ORIGIN_UNINSTALL status=200 modelDeleted=true ACAO=*
CAPTION_URL_NOT_VALIDATED: non-YouTube URL reached extraction
UNBOUNDED_FAILURE_CACHE 1001
MODEL_TREE_WALKS_PER_HEALTH 4
cache: both saves report success; final cache only has video-B
popup: Japanese target retains running operation and Chinese translations
export cancellation: late-created job retained; no cancel message
cross-tab: request A cancellation sends unowned global offscreen stop
```

临时复现脚本为本机 `/private/tmp/localtube-frontend-repro.cjs` 和 `/private/tmp/localtube-engine-review-repros.py`，分别用 Node/Python 执行；后者需要临时回环端口权限。断言是为了证明当前缺陷存在，不是修复成功的测试。模型、缓存、数据目录均隔离；原始测试日志位于 `/private/tmp/localtube-audit-pj6343q5/` 和 `/private/tmp/localtube-audit-loopback-h6fcbxp0/`。这些临时文件可能被系统清理，应在修复时将相应场景纳入现有测试脚本。

没有执行真实 Chrome + YouTube 全链路、生产模型推理、付费 Provider、Windows 实机安装、三平台真实发行包重建或商店验收。`--self-test` 不等于验证当前 dist 中的发行包，`--source` 不等于 Windows 实机通过。当前已有检查全绿仍不足以否定本轮发现的缺陷。

## 后续开发顺序

先修共享 HTTP 请求边界并收紧字幕 URL，然后修语言身份及任务取消/设置切换，再处理缓存并发；下次发行前补齐发布门禁和冒烟严格判定。健康状态重复扫描可顺手优化；其余性能改动以实际长视频测量为依据，无需拆分大型模块或引入新依赖。

## 后续优化与修复结果（2026-09-30，未发布）

按用户要求先完成优化及定向检查，再复查、修复并交叉审阅。保留版本 0.2.8，没有生成或安装新发行包。

| 已完成优化 | 验证依据 |
| --- | --- |
| health 共用一次模型状态快照，目录遍历由 4 次降为 1 次 | 真实合成模型覆盖安装中、安装完成、损坏、恢复及卸载；没有跨请求缓存，完整性验证仍执行 |
| 字幕失败缓存清理过期项并复用容量上限 | 验证容量淘汰、过期清理和不应缓存的错误；默认最多 24 条 |
| 已译字幕键使用 WeakMap/Set，按新时间轴数组失效 | 3,000 条逐项查询约 900 万次键计算降为 6,000 次；生产写入均替换数组 |
| Kokoro 预取填满 2/3 个槽位即停止扫描 | 5,000 段开头只检查 3 段，覆盖重叠、静音借用及反向跳转；没有对 end 不单调的数据强行二分 |

这些是操作次数及行为验证，不是生产视频 CPU、延迟或听感测量。

| 原问题 | 修复与回归 |
| --- | --- |
| #1 HTTP 来源边界 | 派发前验证回环客户端、唯一 Host/真实端口、授权扩展 Origin；POST 必须为 JSON，拒绝含糊请求体及过大请求；真实临时 HTTP 测试确认恶意请求不删除模型、不延长 Engine 生命周期。保留 Native、动态扩展注册及 YouTube 音轨 Range/HEAD 下载 |
| #2 地区字幕串缓存 | 统一缓存/并发合并/失败退避键保留完整语言地区身份；简繁、葡语地区、英语地区及并发路径均测试 |
| #3 设置变更失效 | 弹窗/浮层共用设置过渡；变更翻译输入停止旧任务，按旧端点取消；旧保存响应不覆盖新设置，语音参数改变丢弃旧播放 |
| #4 创建前取消 | 完整转写/整轨各自代次，迟到可见 jobId 主动取消；轮询绑定作业，旧回包/异常不能覆盖新任务；已知 job 的轮询失败也发取消 |
| #5 跨标签取消 | offscreen 开始/取消携带 requestId，仅拥有者能取消；第二个录音明确拒绝；等待 getUserMedia 时取消也会清理晚到流 |
| #6 缓存并发覆盖 | 同一队列串行读取裁剪、保存和清空，存储失败不阻断后续请求；正常读取不重复写回；并发保存和清空次序有行为回归 |
| #7 字幕 URL | 共享入口复用强化后的 YouTube URL 守卫，拒绝伪造域名、userinfo、非法端口及控制字符 |
| #8 发布门禁 | 新增草稿晋升工具：精确提交的最新 CI、三平台归档及签名验证成功，二次核对草稿/资产/提交后才发布为 latest；14 类隔离场景及 5 个非法标签验证，无实际 GitHub 发布 |
| #9 冒烟假通过 | 临时端口和随机实例，严格核对能力/版本/运行目录/实例；6 个真实临时 HTTP 场景验证 HTTP 200 的错误能力或身份不能通过 |

复查额外修复了五个相邻问题：TTS 的 HTTP 业务错误/超时不再经 Native 重放（保留连接不可用回退及 `ENGINE_UPDATING` 提示）；旧翻译任务的 finally 不再释放新任务的字幕预约；取消完整字幕翻译后旧异常不再恢复视频；完整字幕有一个并发翻译失败时，淘汰整轮并取消其他请求，迟到回复不再写回或继续发新批次；撤回 Microsoft 配音同意会取消 Edge 整轨并丢弃旧播放。录音测试另加真实超时失败保护，已用旧 offscreen 实现验证测试会失败，避免 pending Promise 让 Node 静默退出成功。

修复后原 14 项检查均通过，新增回归融入原脚本；Python 使用项目 `.venv/bin/python`（3.14），16 个变更 JS/Python/Shell 文件语法及 diff 检查通过。需要监听的测试使用获准的临时回环端口、模型与安装目录。AOCI 在全部修改稳定后增量维护，新增发布工具也纳入索引。

使用与验证边界：源码直接启动 HTTP Engine 时，应按 `companion/README.md` 用 `LOCAL_DUB_EXTENSION_ID` 绑定当前解压扩展；已注册的同运行时 Native 扩展 ID 可热读取。管理员仍能绕过工作流手工发布，仓库权限是独立边界；本轮未改远端设置。没有真实 Chrome/YouTube 或 Windows 实机验收，也未运行生产模型。若底层 HTTP 断连使客户端始终拿不到已创建作业的 jobId，仍无法确认远端取消；本轮修复的是可见迟到响应和已知作业的取消竞态，没有新增分布式任务幂等协议。

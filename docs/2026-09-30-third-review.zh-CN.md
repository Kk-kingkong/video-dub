# 第三轮复查与修复

范围：LocalTube Dub 0.2.8 工作区，基线提交 `5f8884a`，包含此前两轮尚未提交的修复。本轮新增七处 P2 发现，六处通过隔离生产函数复现，Windows 目录锁问题通过实际 Native 分派与平台契约确认；随后完成以下源码修复。

| 问题与原始证据 | 修复行为 | 回归位置 |
| --- | --- | --- |
| 旧标签页 Kokoro 回退音色后，把其他页面保存的 English/DeepSeek 恢复为中文/Native | 自动纠正仅提交音色/引擎字段，核对当前目标语言、引擎和原音色；与用户保存及安装初始化串行。后台拒绝过期纠正，保留授权、凭证和其他偏好 | `verify_translation_integrity.js`：实际页面函数→后台消息→模拟 sync 存储；跨标签冲突、匹配补丁及交错保存 |
| 平台自动纠正的迟到响应覆盖用户新选的语言、引擎和音色 | 页面不再合并自动纠正返回的整份设置，持久化也使用条件字段补丁 | `verify_extension_flows.js`：真实平台纠正与 settingsChanged 交错 |
| 已取消启动的 loadSettings 仍先赋值再检查任务代次 | 先校验任务代次，再采用读取结果；期间已变更的页面设置保留 | `verify_extension_flows.js`：取消启动后的迟到读取 |
| 字幕 `[0,10]、[1.82,2]、[3,4]` 在第 5 秒误报无字幕 | 按开始时间定位，再利用结束时间前缀最大值查找仍生效的重叠字幕；索引按不可变时间轴缓存 | `verify_extension_flows.js`：生产 VTT 解析、边界与替换时间轴、10,000 条字幕的稳定查询成本；另做 37,400 个独立对照查询 |
| Kokoro 一次暂时装载失败后，同进程 API 持续拒绝，重装模型也不能恢复 | 临时异常冷却 30 秒，连续最多 3 次装载；健康查询不加载模型；真实不兼容继续拒绝；卸载重装清理失败状态并丢弃卸载前迟到结果 | `verify_kokoro_engine.py`：生产合成入口、排队请求、重装恢复、迟到加载及版本/配置不兼容 |
| 更新器持续慢流让 response.read 阻塞，300 秒总期限迟迟无法检查 | 独立 Python 下载进程覆盖 DNS、响应头及正文的总期限；超时终止并回收子进程，失败清理 partial，成功才替换目标；保留地址、大小和签名信任边界 | `verify_engine_updates.py`：真实 HTTPResponse/socketpair 与下载子进程、慢流/闲置、大小检查、超时后的工作线程排空 |
| Windows Native 同步修复时，以运行目录作为工作目录，安装器却移动该目录 | 仅已安装同目录的手动 `-Repair` 原地修复；保留合同验证、注册快照、绑定、健康验证及失败恢复；包安装和自动更新继续走替换路径 | `verify_windows_package.py`：新增实际 Native 成功与注入失败的 Windows 安装用例；本机只验证源码和分派 |

## 验证结果

本轮以下 14 项检查全部通过：

- Node：`verify_extension_flows.js`、`verify_translation_integrity.js`、`verify_engine_lifecycle.js`、`verify_provider_registry.js`。
- Python：`verify_local_engine.py`、`verify_kokoro_engine.py`、`verify_native_messaging.py`、`verify_engine_lifecycle.py`、`verify_engine_updates.py`、`verify_update_integration.py`、`verify_update_publication.py`、`verify_open_source_compliance.py`。
- 打包：`verify_release_packages.py --self-test`、`verify_windows_package.py --source`。

前端修复经过独立交叉复查，未发现确定的新缺陷。普通字幕间隙查询保持对数成本；极端长字幕覆盖大量短字幕时，仍可能回扫多个重叠候选。

## 验收边界

- 回归使用临时目录、模拟外部服务/模型和必要的本机随机回环端口；未调用生产云端服务或下载生产模型。
- 未进行真实 Chrome/YouTube 端到端或生产神经模型听感验收。
- 新增 Windows Native 安装用例需要 Windows CI 执行；macOS 的源码和分派验证不能替代 Windows 实机结果。
- 本轮只更新工作区源码、验证与 AOCI 认知，不提升版本、不提交、不发布安装包。

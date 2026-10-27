<h1>❗ 纯 AI 产物，有需求建议去原版仓库</h1>

**本仓库是 [breezeblue-ai/breeze-tts](https://github.com/breezeblue-ai/breeze-tts) 的第三方本地化分支，仅额外增加网页控制台与音色库，上游代码未作修改。功能建议、问题反馈与模型相关疑问，请优先前往原版仓库或[官方模型页](https://huggingface.co/BreezeBlue/breeze-tts-2)；模型权重不随本仓库分发。**

---

# Breeze TTS 2 · 网页控制台（本仓库新增）

本仓库是 [breezeblue-ai/breeze-tts](https://github.com/breezeblue-ai/breeze-tts) 的**本地化增强分支**：
上游代码（`breeze_infer/`、`models/`、`tests/`、`docker/`）一行未改，只在其 FastAPI 实例上**额外挂载**了一套网页控制台与音色库接口。

- 上游源码：https://github.com/breezeblue-ai/breeze-tts
- 模型权重：https://huggingface.co/BreezeBlue/Breeze-TTS-2 （需单独下载，仓库不含权重）
- 许可证：源码 Apache-2.0；**权重与生成结果仅限研究/非商业用途**，见下方「许可」

---

## 1. 这个分支多了什么

| 能力 | 说明 |
| --- | --- |
| 网页控制台 | 单文件前端，无外部依赖、无 CDN，离线可用 |
| 三种模式 | 音色设计（文字造音）/ 声音克隆（参考音频）/ 声音导演（参考音频 + 指令） |
| 音色预设 | 8 个常用音色描述，一键填入 |
| 副语言事件 | `[笑]` `[叹气]` `[咳嗽]` `[清嗓子]` `[喘气]` `[哭]` `[开心]` 等一键插入光标处 |
| 参考音频 | 拖拽、文件选择、**浏览器内直接录音**（自动转 WAV），可试听、可清除 |
| 流式播放 | Web Audio API 边下发边播，首包即可发声，无爆音 |
| 波形与统计 | 实时波形、TTFA、总耗时、音频时长、RTF、seed |
| 批量合成 | 每行一条文本，一次请求出多条，逐条试听/下载 |
| 音色库 | 把「描述 + 参考音频 + cfg + seed + 试听样本」存成可复用音色，一键套用 |
| 确定性复刻 | 勾选后所有生成走 `/batch`，**同参数逐字节可复现** |
| 结果处理 | 播放、换 seed 重生、落盘到 `outputs/`、下载 WAV、复制可复现的 curl 命令、历史记录 |

## 2. 目录结构

```
.
├─ infer.py                 上游：命令行推理入口
├─ breeze_infer/            上游：FastAPI 流式服务（未改动）
├─ models/                  上游：模型实现（Python 包，勿在此放权重）
├─ tests/  docker/  configs/  assets/   上游
├─ webui/                   ★ 本分支新增
│  ├─ index.html            单文件前端
│  └─ server.py             在官方 app 上挂载页面 / 保存接口 / 音色库接口
├─ start-webui.bat          ★ Windows 一键启动（网页控制台）
├─ start-api.bat            ★ Windows 一键启动（仅 REST）
├─ WEBUI.md                 ★ 本文档
├─ checkpoints/             模型权重（.gitignore，需自行下载）
├─ voices/                  音色库数据（.gitignore，个人数据）
└─ outputs/                 生成结果（.gitignore）
```

## 3. 安装（Windows / Linux 通用）

上游声明支持 Linux + Python 3.10+；本分支已在 **Windows 11 + Python 3.12.3 + torch 2.9.1+cu128** 上实测通过。

```bash
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux 把 `Scripts` 换成 `bin`，`--index-url` 按自己的 CUDA 版本调整（cu121 / cu124 / cu126 / cu128）。

下载权重（约 7.2 GB）：

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download BreezeBlue/Breeze-TTS-2 --local-dir checkpoints/Breeze-TTS-2
```

国内网络可先设置镜像：`set HF_ENDPOINT=https://hf-mirror.com`（PowerShell 用 `$env:HF_ENDPOINT=...`）。

## 4. 启动

```bash
# 网页控制台（推荐）：浏览器打开 http://127.0.0.1:7860/
python -m webui.server checkpoints/Breeze-TTS-2 --host 127.0.0.1 --port 7860

# 仅 REST 接口
python -m breeze_infer.api checkpoints/Breeze-TTS-2 --host 127.0.0.1 --port 7860
```

Windows 下可直接双击 `start-webui.bat` / `start-api.bat`（脚本用 `%~dp0` 定位，可整体挪目录）。
首次启动约 15 秒加载权重，日志出现 `Uvicorn running on http://127.0.0.1:7860` 即就绪。
换端口加 `--port 7861`。

## 5. 接口

上游接口保持不变，返回**裸 PCM**（单声道 24 kHz、s16le），需要自己加 44 字节 WAV 头。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 就绪探针，加载中返回 503 |
| GET | `/v1/model` | 模型信息（frame_rate / digest / 上限） |
| POST | `/v1/audio/speech` | 流式合成（multipart） |
| POST | `/v1/audio/speech/batch` | 批量合成（`texts` 传 JSON 数组，≤128） |

`/v1/audio/speech` 表单字段：`text`、`instruction`、`cfg_scale`、`seed`、`ref_audio` + `ref_text`（必须成对）。
同一时刻只允许 1 个推理请求，第二个并发请求返回 **409**。

### 本分支新增的辅助接口（`webui/server.py`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/` | 网页控制台 |
| GET | `/webui/*` | 前端静态资源 |
| POST | `/api/save?name=` | 把 WAV 落盘到 `outputs/`（文件名白名单 + 路径穿越校验 + 64 MB 上限） |
| GET | `/api/voices` | 列出音色库 |
| POST | `/api/voices` | 新建音色（multipart） |
| DELETE | `/api/voices/{id}` | 删除音色及其 ref/sample 文件 |
| GET | `/api/voices/{id}/ref` | 取回该音色的参考音频 |
| GET | `/api/voices/{id}/sample` | 取回该音色的试听样本 |

这些路由都带 `include_in_schema=False`，不会污染 `/docs`。

## 6. 两个关键坑（重要）

### 6.1 纯克隆必须 `cfg_scale=1.0`

上游只有「带 instruction 的模板」定义了 negative prompt。因此**参考音频 + 无描述**会走到 `ref_clone_tata`，此时设 `cfg_scale>1` 直接 500：

```
Template 'ref_clone_tata' does not define a negative prompt but cfg_scale=4.0
```

网页已自动处理：描述为空时 CFG 滑块锁定为 `1.0`，填了描述（= 声音导演）才解禁。

### 6.2 只有 `/batch` 可复现

| 接口 | 同参数重复生成 | 结论 |
| --- | --- | --- |
| `POST /v1/audio/speech`（流式） | 每次 SHA256 都不同 | ❌ 不可复现 |
| `POST /v1/audio/speech/batch` | **逐字节完全相同** | ✅ 可复现，且 seed 真实生效 |

实测（固定 instruction，`seed 42` 连跑三次）：流式三次基频 291.8 / 292.0 / 292.4 Hz、MFCC 相似度 0.9999；`/batch` 三次基频全为 274.6 Hz、相似度 1.0000。
换 seed（42 → 7 → 1234）基频从 274.6 Hz 漂到 260.6 / 259.8 Hz，相似度降到 0.806–0.937 ——**同 seed 就是同一个音色，换 seed 就是换音色**。

所以想要可复用的固定音色：勾「🔒 确定性复刻」→ 收藏到音色库。

## 7. 音色复刻（音色库）

模型本身不吃「音色文件」，音色由**四个量**共同决定，把这四个量存下来就等于复刻：

| 量 | 说明 |
| --- | --- |
| `instruction` | 音色描述（音色设计必填）或导演指令（克隆模式可选） |
| `ref_audio` + `ref_text` | 克隆/导演模式需要，成对提交，文本必须与音频逐字一致 |
| `cfg_scale` | 纯克隆必须 1.0 |
| `seed` | 决定随机起点 |

用法：

1. 调出满意的一条音色。
2. 勾选 **🔒 确定性复刻**（之后全走 `/batch`）。
3. 点 **＋ 收藏当前**，起个名字 —— 描述、参考音频、CFG、种子、试听样本一起存进 `voices/`。
4. 以后在「我的音色」点「套用」，参数与参考音频全部还原，再生成即得同一个声音；点「▶」可不加载模型直接试听样本。

`voices/` 是明文 JSON + WAV，整个目录拷走即完成备份/迁移。

## 8. 实测性能（RTX 4070 Ti 12 GB，eager 模式）

| 用例 | 音频时长 | 首包 TTFA | 总耗时 | RTF |
| --- | --- | --- | --- | --- |
| 音色设计 中文 | 2.96 s | 3256 ms | 19.0 s | 6.42 |
| 音色设计 英文 | 3.84 s | 1009 ms | 21.5 s | 5.61 |
| 声音克隆（ref 3.5 s，cfg=1） | 4.00 s | 1130 ms | 24.0 s | 5.99 |
| 声音导演（ref + 指令，cfg=3.5） | 3.68 s | 1330 ms | 22.9 s | 6.21 |
| 批量 3 条（合计 9.28 s 音频） | 9.28 s | — | 11.8 s | ~1.27 |
| 确定性复刻 单条（走 `/batch`） | 4.00 s | — | 9.8 s | 2.46 |

RTF>1 是正常的：官方 0.32 RTF / <40 ms TTFA 是 H100 开 `--fast-all` 的数据，而 `--fast-all` 约需 14.4 GiB 显存，12 GB 卡跑不了快路径。单条约实时的 1/6，适合离线配音；**长文本/多条务必走 `/batch`**，吞吐接近实时。

## 9. 已知提示（都不是错误）

- `Warning: flash-attn is not installed` —— eager 路径不需要它，可忽略。
- `'sox' is not recognized` —— 只是 librosa 的可选命令行工具检查，pipeline 未使用。
- 中文控制台在 CP936 代码页下可能显示乱码，不影响文件与音频（`start-webui.bat` 已 `chcp 65001`）。

## 10. 测试

```bash
python -m pytest tests -q
```

上游自带 102 个用例；本分支未修改上游代码，测试全部通过。

## 11. 许可与致谢

- 本分支新增的 `webui/`、启动脚本与本文件同样以 **Apache-2.0** 发布，欢迎自取。
- 上游源码：© BreezeBlue，Apache-2.0。
- 音频 tokenizer 基于 [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)（阿里巴巴通义千问团队），Apache-2.0。
- **模型权重**、检查点、衍生模型与自托管输出受 [BreezeBlue Research and Non-Commercial License](https://huggingface.co/BreezeBlue/Breeze-TTS-2/blob/main/LICENSE) 约束，**不可商用**；Apache-2.0 不授予模型商用权利。本仓库不包含任何权重文件。

# 自动小说生成脚本

这是一个基于 OpenAI-compatible 接口的 Python 脚本，用来按章节自动生成小说。正文写作和修订默认走火山 Ark Agent Plan 的 `kimi2.6`；审阅默认保留 DeepSeek，避免把超长审阅上下文发给 Kimi。各阶段也可以随时切换 provider。

主要文件：

- `deepseek_novel_writer.py`：主流程编排
- `prompts.py`：写作 / 审阅 / 修订 prompt
- `novel_utils.py`：文件、状态、JSON 解析等工具函数
- `llm_client.py`：OpenAI-compatible LLM 调用封装，声明式管理 provider / base_url / model / API Key
- `deepseek_client.py`：兼容旧代码的 DeepSeek 调用包装
- `merge_chapter_contents.py`：把多个章节正文文件合并成一个完整文本
- `outline_agent.py`：交互式大纲 agent 的命令行入口
- `outline_gradio_app.py`：交互式大纲 agent 的 Gradio 页面
- `writing_context.py`：正文写作 agent 的分块大纲上下文读取

## 功能

- 读取小说大纲，支持旧版合并大纲 `Abstract.txt`，也支持新版分块大纲
- 按章节调用 LLM 生成正文和创作笔记
- 每章分别保存为：
  - `chapter_1_content.txt`
  - `chapter_1_notes.txt`
- 每章生成后会自动审阅，并保存为：
  - `chapter_1_review_result.txt`
- 每章审阅后会自动修订，并保存为：
  - `chapter_1_revision_result.txt`
- 支持断点续跑：如果某一章已经生成过，就自动跳过
- 支持把已生成的 `chapter_N_content.txt` 按章节号合并成整本文稿

## 准备

### 1. 填写 API Key

推荐不改脚本，直接在当前运行目录放 `.env` 文件。火山 Ark Agent Plan 默认配置如下：

```env
VOLCENGINE_API_KEY=你的火山APIKey
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
VOLCENGINE_MODELS=["kimi2.6"]
```

也可以使用通用变量，适合后续切换 provider 时统一管理：

```env
LLM_API_KEY=你的APIKey
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
LLM_MODELS=["kimi2.6"]
```

如果要继续使用 DeepSeek，可配置：

```env
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_MODELS=["deepseek-v4-pro"]
```

如果要使用阿里云百炼 Token Plan，可配置：

```env
ALIYUN_API_KEY=你的百炼TokenPlanKey
ALIYUN_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ALIYUN_MODELS=["你的模型名"]
```

`*_MODELS` 支持 JSON 数组格式，也兼容逗号分隔字符串；Gradio 大纲页会按所选 provider 从对应变量加载模型下拉列表。

所有 provider 都走同一套 OpenAI-compatible Chat Completions 调用逻辑；DeepSeek、火山和百炼只是 `llm_client.py` 里的不同 `ProviderSpec`。

Abstract/大纲 agent 和 review agent 是最容易吃满上下文的两个环节：前者可能读整本原文，后者可能读大量前文和当前章，推荐优先选择百万上下文或足够长上下文模型。

比如你在项目目录运行脚本：

```text
/Users/fangzhou/Workspace/qufafa/automatic_novel_writer/.env
```

脚本会按这个优先级取 key：

1. 阶段专用参数：`--writer-api-key` / `--review-api-key` / `--revision-api-key`
2. 通用参数：`--api-key`
3. 当前运行目录下的 `.env`
4. 系统环境变量

### 2. 准备小说工作目录

比如你准备一个目录：

```text
my_novel/
├── Abstract.txt
```

其中 `Abstract.txt` 里放你的小说大纲。

## 用法

命令格式：

```bash
python3 deepseek_novel_writer.py <workspace> [total_chapters]
```

- `workspace`：小说工作目录
- `total_chapters`：小说总章节数；旧版合并大纲模式必填，新版分块大纲模式可从 `outline_state.json` 自动读取

### 示例 1：最常用

```bash
python3 deepseek_novel_writer.py ./my_novel 20
```

意思是：

- 在 `./my_novel/Abstract.txt` 里读取小说大纲
- 总共生成 20 章

### 示例 1B：使用新版分块大纲

如果工作目录中已经有交互式大纲 agent 生成的这些文件：

```text
my_novel/
├── Abstract_global.txt
├── outline_state.json
├── outlines/
│   ├── chapter_1_outline.txt
│   └── chapter_2_outline.txt
├── module9_foreshadowing.txt
└── module10_pacing.txt
```

可以直接运行：

```bash
python3 deepseek_novel_writer.py ./my_novel --outline-mode split
```

`split` 模式会按章节读取：

- `Abstract_global.txt`
- `outlines/chapter_N_outline.txt`
- 所有不超过目标总章数的模块5章节大纲
- `module9_foreshadowing.txt`
- `module10_pacing.txt`
- 前文创作笔记
- 最近几章正文

如果不写 `--outline-mode`，默认 `auto` 会优先检测分块大纲；检测不到时回退到旧版 `Abstract.txt`。

如果想限制目标章数，例如只写 70 章：

```bash
python3 deepseek_novel_writer.py ./my_novel --outline-mode split --total-chapters 70
```

### 示例 2：命令行传 API Key

```bash
python3 deepseek_novel_writer.py ./my_novel 20 --api-key sk-xxxx
```

### 示例 3：指定别的大纲文件

```bash
python3 deepseek_novel_writer.py ./my_novel 20 --outline-file outline_v2.txt
```

这时脚本会读取：

```text
./my_novel/outline_v2.txt
```

### 示例 4：使用 `.env`

先在当前运行目录的 `.env` 写入：

```env
VOLCENGINE_API_KEY=你的火山APIKey
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
VOLCENGINE_MODELS=["kimi2.6"]
```

然后直接运行：

```bash
python3 deepseek_novel_writer.py ./my_novel 20
```

### 示例 5：临时切换 provider

写作和修订默认 provider 是 `volcengine`，默认模型是 `kimi2.6`；审阅默认 provider 是 `deepseek`。如果要让全部阶段临时切到 DeepSeek：

```bash
python3 deepseek_novel_writer.py ./my_novel 20 \
  --provider deepseek \
  --model deepseek-v4-pro
```

也可以只切某个阶段，例如显式指定写作和修订用 Kimi，审阅用 DeepSeek：

```bash
python3 deepseek_novel_writer.py ./my_novel 20 \
  --provider volcengine \
  --model kimi2.6 \
  --review-provider deepseek \
  --review-model deepseek-v4-pro
```

切换写作和修订到阿里云百炼 Token Plan：

```bash
python3 deepseek_novel_writer.py ./my_novel 20 \
  --writer-provider aliyun \
  --writer-model 你的模型名 \
  --revision-provider aliyun \
  --revision-model 你的模型名
```

为 Abstract/大纲 agent 指定 provider/model（强烈建议百万上下文或足够长上下文模型，因为它会读取整篇原文）：

```bash
python3 outline_agent.py ./my_novel_outline \
  --generate-global \
  --provider aliyun \
  --model kimi-k2.6
```

为审阅 agent 指定 provider/model（同样建议百万上下文或足够长上下文模型，因为 review 会读取大量前文和当前章节）：

```bash
python3 deepseek_novel_writer.py ./my_novel 20 \
  --review-provider aliyun \
  --review-model kimi-k2.6
```

## 生成结果

假设你要生成 3 章，执行后目录可能会变成这样：

```text
my_novel/
├── Abstract.txt
├── chapter_1_content.txt
├── chapter_1_notes.txt
├── chapter_1_review_result.txt
├── chapter_1_revision_result.txt
├── chapter_2_content.txt
├── chapter_2_notes.txt
├── chapter_2_review_result.txt
├── chapter_2_revision_result.txt
├── chapter_3_content.txt
├── chapter_3_notes.txt
├── chapter_3_review_result.txt
└── chapter_3_revision_result.txt
```

其中：

- `chapter_N_content.txt`：第 N 章正文
- `chapter_N_notes.txt`：第 N 章创作笔记，供下一章继续生成时使用
- `chapter_N_review_result.txt`：第 N 章审阅报告
- `chapter_N_revision_result.txt`：第 N 章修订 agent 的结构化 JSON 结果，包含是否采纳 review、拒绝原因、实际改动点等

## 合并章节正文

`merge_chapter_contents.py` 用来把某个小说工作目录中的章节正文文件合并成一个完整文本。

它会查找目标目录下所有符合下面命名格式的文件：

```text
chapter_1_content.txt
chapter_2_content.txt
chapter_3_content.txt
```

然后按章节数字从小到大排序，并在每章前自动加入章节分隔标题：

```text
----------第1章----------
第 1 章正文内容

----------第2章----------
第 2 章正文内容
```

### 用法

命令格式：

```bash
python3 merge_chapter_contents.py <workspace>
```

- `workspace`：包含 `chapter_N_content.txt` 文件的小说工作目录

### 示例

假设章节正文都在 `./my_novel` 目录中：

```bash
python3 merge_chapter_contents.py ./my_novel
```

执行成功后，会在同一个目录下生成合并文件，例如：

```text
my_novel/all_chapters_1_to_3_merged.txt
```

文件名里的 `1_to_3` 会根据实际找到的最小章节号和最大章节号自动变化。

### 注意事项

- 只会合并文件名严格匹配 `chapter_N_content.txt` 的文件，例如 `chapter_10_content.txt`
- 会忽略 `chapter_N_notes.txt`、`chapter_N_review_result.txt`、`chapter_N_revision_result.txt` 等其他文件
- 如果目录不存在、传入的不是目录，或目录里没有可合并的章节正文文件，脚本会报错并退出
- 合并结果会写入目标目录下的 `all_chapters_<起始章节>_to_<结束章节>_merged.txt`


## 交互式大纲 Agent

项目新增了一个基于 Gradio 的交互式大纲生成页面，用来先生成全局大纲，再逐章生成“模块5：逐章连载执行大纲”。

### 启动页面

```bash
python3 outline_gradio_app.py
```

如果本地没有 Gradio，需要先安装：

```bash
pip install gradio
```

### 工作目录结构

页面会把每个小说项目保存到一个独立 workspace，例如：

```text
my_novel_outline/
├── source_novel.txt
├── Abstract_global.txt
├── outline_state.json
├── outlines/
│   ├── chapter_1_outline.txt
│   ├── chapter_2_outline.txt
│   └── chapter_3_outline.txt
├── module9_foreshadowing.txt
├── module10_pacing.txt
└── Abstract.txt
```

其中：

- `source_novel.txt`：页面输入的小说原文备份
- `Abstract_global.txt`：除了模块5之外的全局大纲
- `outlines/chapter_N_outline.txt`：第 N 章的模块5逐章连载执行大纲
- `module9_foreshadowing.txt`：模块9伏笔库当前状态，会随每章更新
- `module10_pacing.txt`：模块10节拍分布当前状态，会随每章更新
- `outline_state.json`：当前生成进度、目标章节数、原文统计结果等状态
- `Abstract.txt`：兼容旧流程的合并大纲；新版正文写作脚本可直接读取分块大纲，不再依赖它

### 页面流程

1. 在页面填写 workspace，并粘贴小说原文。
2. 点击“保存原文并统计”，程序会自动统计有效字符数和章节数。
3. 点击“生成全局大纲”，生成模块0-4、模块6-8、模块9空表、模块10空表和写作约束摘要。
4. 在“模块5 逐章大纲”页点击“确认/生成下一章”，每次生成一章。
5. 可选择：
   - `手动`：每次点击只生成下一章
   - `自动生成接下来 N 章`：一次连续生成 N 章
   - `自动直到完成`：从当前进度生成到目标终章
6. 如需修改，可直接编辑当前章、模块9或模块10，并点击对应保存按钮。
7. 全部完成后点击“合并为 Abstract.txt”。

如果使用新版正文写作脚本，合并 `Abstract.txt` 不是必须步骤；正文脚本可以直接使用 `--outline-mode split` 读取分块文件。

### 命令行用法

也可以不启动页面，直接用命令行：

```bash
python3 outline_agent.py ./my_novel_outline --source-file ./source.txt --generate-global
python3 outline_agent.py ./my_novel_outline --next-chapter
python3 outline_agent.py ./my_novel_outline --batch 3
python3 outline_agent.py ./my_novel_outline --build-abstract
```

## 断点续跑

如果脚本中途停了，重新执行同样的命令即可。

脚本会先检查每一章对应的两个文件：

- `chapter_N_content.txt`
- `chapter_N_notes.txt`

如果这两个文件都存在且不是空文件，就跳过这一章，继续生成下一章。

如果正文和笔记已经存在，但 `chapter_N_review_result.txt` 不存在，脚本会自动补做这一章的审阅。

如果审阅结果已经存在，但 `chapter_N_revision_result.txt` 不存在，脚本会自动补做这一章的修订，并回写正文与创作笔记。

## 常用参数

```bash
python3 deepseek_novel_writer.py --help
```

可查看全部参数。

常用参数包括：

- `--api-key`：临时传入 API Key
- `--env-file`：指定 `.env` 文件名或路径，默认是当前运行目录下的 `.env`
- `--provider`：通用 provider；不传时写作/修订默认 `volcengine`，审阅默认 `deepseek`；支持 `volcengine` / `ark` / `kimi` / `deepseek` / `aliyun` / `bailian` / `qwen` / `custom`
- `--base-url`：通用 OpenAI-compatible base_url；火山默认 `https://ark.cn-beijing.volces.com/api/plan/v3`
- `--outline-file`：指定大纲文件
- `--outline-mode`：大纲读取模式，`auto` / `merged` / `split`
- `--total-chapters`：覆盖目标章节数，`split` 模式下优先级高于 `outline_state.json`
- `--recent-chapters`：`split` 模式写作 / 修订时额外提供最近 N 章正文，默认 `3`
- `--include-all-previous-text`：`split` 模式下向写作 / 修订提供所有前文章节正文
- `--no-context-debug`：`split` 模式下不保存 `chapter_N_writing_context.txt`
- `--model`：指定通用模型；不传时读取 `.env`，否则使用各 provider 默认值（火山默认 `kimi2.6`）
- `--writer-provider` / `--writer-model`：覆盖写作阶段 provider / 模型
- `--review-provider` / `--review-model`：覆盖审阅阶段 provider / 模型；审阅上下文通常很长，建议使用百万上下文或长上下文模型
- `--revision-provider` / `--revision-model`：覆盖修订阶段 provider / 模型
- `outline_agent.py --provider` / `--model`：覆盖 Abstract/大纲 agent provider / 模型；会读取整篇原文，建议使用百万上下文模型
- `--max-tokens`：控制单章或审阅报告的最大输出长度，默认 `12000`
- `--temperature`：控制创意程度
- `--timeout`：单次请求超时时间
- `--retries`：失败重试次数

## Provider 抽象

`llm_client.py` 现在只有一个通用调用路径：`resolve_llm_config()` 解析配置，`call_llm_text()` / `call_llm_json()` 发起 OpenAI-compatible `/chat/completions` 请求。

新增兼容 OpenAI 协议的 provider 时，通常只需要在 `PROVIDER_SPECS` 增加一条 `ProviderSpec`：

```python
"new_provider": ProviderSpec(
    name="new_provider",
    base_url="https://example.com/v1",
    default_model="your-default-model",
    aliases=("new",),
    env_prefixes=("NEW_PROVIDER",),
    supports_json_response_format=False,
)
```

对应 `.env` 会自动支持：

```env
NEW_PROVIDER_API_KEY=...
NEW_PROVIDER_BASE_URL=https://example.com/v1
NEW_PROVIDER_MODELS=["your-model"]
```

如果这个 provider 支持 OpenAI JSON mode，就把 `supports_json_response_format=True`；否则脚本不传 `response_format`，只依赖 prompt 与本地 JSON 修复解析。

## 一个最小可运行流程

### 1. 创建目录和大纲

```bash
mkdir -p my_novel
```

在 `my_novel/Abstract.txt` 写入你的小说大纲。

### 2. 运行脚本

```bash
python3 deepseek_novel_writer.py ./my_novel 10
```

### 3. 查看生成结果

```bash
ls my_novel
```

## 注意事项

- `Abstract.txt` 不能为空
- 请确认 API Key 正确可用
- 火山 Ark Agent Plan 和阿里云百炼默认不发送 `response_format=json_object`，脚本会依赖 prompt 和本地 JSON 修复逻辑解析输出
- 章节越长、章节数越多，API 调用时间和费用也会增加
- 如果模型偶尔返回格式不规范，比如字符串里的换行没有正确转义，脚本会先尝试自动修复；修复失败后再按重试逻辑处理

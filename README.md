# DeepSeek 自动小说生成脚本

这是一个基于 DeepSeek API 的 Python 脚本，用来按章节自动生成小说。

主要文件：

- `deepseek_novel_writer.py`：主流程编排
- `prompts.py`：写作 / 审阅 / 修订 prompt
- `novel_utils.py`：文件、状态、JSON 解析等工具函数
- `deepseek_client.py`：DeepSeek API 调用封装
- `merge_chapter_contents.py`：把多个章节正文文件合并成一个完整文本

## 功能

- 读取小说大纲，默认读取工作目录下的 `Abstract.txt`
- 按章节调用 DeepSeek 生成正文和创作笔记
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

打开 `deepseek_novel_writer.py`，找到这一行：

```python
DEFAULT_API_KEY = "YOUR_DEEPSEEK_API_KEY"
```

把它改成你自己的 DeepSeek API Key。

也可以不改脚本，运行时通过 `--api-key` 传入。

还支持在当前运行目录里放一个 `.env` 文件，例如：

```env
DEEPSEEK_API_KEY=sk-xxxx
```

比如你在项目目录运行脚本：

```text
/Users/fangzhou/Workspace/qufafa/automatic_novel_writer/.env
```

脚本会按这个优先级取 key：

1. `--api-key`
2. 当前运行目录下的 `.env`
3. 环境变量 `DEEPSEEK_API_KEY`
4. 脚本里的 `DEFAULT_API_KEY`

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
python3 deepseek_novel_writer.py <workspace> <total_chapters>
```

- `workspace`：小说工作目录
- `total_chapters`：小说总章节数

### 示例 1：最常用

```bash
python3 deepseek_novel_writer.py ./my_novel 20
```

意思是：

- 在 `./my_novel/Abstract.txt` 里读取小说大纲
- 总共生成 20 章

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
DEEPSEEK_API_KEY=sk-xxxx
```

然后直接运行：

```bash
python3 deepseek_novel_writer.py ./my_novel 20
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
- `--outline-file`：指定大纲文件
- `--model`：指定模型，默认是 `deepseek-v4-flash`
- `--max-tokens`：控制单章或审阅报告的最大输出长度，默认 `12000`
- `--temperature`：控制创意程度
- `--timeout`：单次请求超时时间
- `--retries`：失败重试次数

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
- 章节越长、章节数越多，API 调用时间和费用也会增加
- 如果模型偶尔返回格式不规范，比如字符串里的换行没有正确转义，脚本会先尝试自动修复；修复失败后再按重试逻辑处理

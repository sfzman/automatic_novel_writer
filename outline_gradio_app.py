"""Gradio UI for the interactive outline agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import gradio as gr
except ImportError as exc:  # pragma: no cover - shown when launched without gradio.
    raise SystemExit("请先安装 gradio: pip install gradio") from exc

from novel_utils import DEFAULT_API_KEY
from outline_agent import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TEMPERATURE,
    LONG_CONTEXT_MODEL_HINT,
    generate_chapters_batch,
    generate_global_outline,
    generate_next_chapter_outline,
    rebuild_final_abstract,
    resolve_outline_llm_config,
    save_source_only,
)
from outline_workspace import (
    init_from_source,
    list_chapter_outlines,
    read_chapter_outline,
    read_global_outline,
    read_module9,
    read_module10,
    read_source_novel,
    read_state,
    state_summary,
    write_chapter_outline,
    write_global_outline,
    write_module9,
    write_module10,
    write_state,
)


def _workspace(value: str) -> Path:
    if not value.strip():
        raise gr.Error("请填写 workspace 路径。")
    return Path(value).expanduser().resolve()


def _resolve_config(provider: str, api_key: str, env_file: str, base_url: str, model: str):
    return resolve_outline_llm_config(
        provider=provider or DEFAULT_PROVIDER,
        api_key=api_key or DEFAULT_API_KEY,
        env_file=env_file or ".env",
        base_url=base_url or "",
        model=model or DEFAULT_MODEL,
    )


def _chapter_choices(workspace: Path) -> list[str]:
    return [f"第{idx}章" for idx in list_chapter_outlines(workspace)]


def _choice_to_index(choice: str) -> int:
    digits = "".join(char for char in str(choice) if char.isdigit())
    return int(digits or 0)


def _status_text(workspace: Path) -> str:
    summary = state_summary(workspace)
    return "\n".join(
        [
            f"有效字符数: {summary['source_meaningful_chars']}",
            f"检测章节数: {summary['detected_source_chapters'] or '无显式章节'}",
            f"目标总字数: {summary['target_total_chars']}",
            f"目标章节数: {summary['total_chapters']}",
            f"已生成章节: {summary['generated_count']} / {summary['total_chapters']}",
            f"下一章: 第{summary['next_chapter']}章",
        ]
    )


def _refresh_outputs(workspace_value: str) -> tuple[Any, ...]:
    workspace = _workspace(workspace_value)
    choices = _chapter_choices(workspace)
    selected = choices[-1] if choices else None
    selected_text = read_chapter_outline(workspace, _choice_to_index(selected)) if selected else ""
    return (
        read_source_novel(workspace),
        read_global_outline(workspace),
        gr.update(choices=choices, value=selected),
        selected_text,
        read_module9(workspace),
        read_module10(workspace),
        _status_text(workspace),
    )


def save_source_callback(workspace_value: str, source_text: str) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    save_source_only(workspace, source_text)
    return _status_text(workspace), "原文已保存，统计结果已更新。"


def generate_global_callback(
    workspace_value: str,
    source_text: str,
    provider: str,
    api_key: str,
    env_file: str,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
) -> tuple[Any, ...]:
    workspace = _workspace(workspace_value)
    if not source_text.strip():
        raise gr.Error("请先粘贴小说原文。")
    llm_config = _resolve_config(provider, api_key, env_file, base_url, model)
    result = generate_global_outline(
        workspace=workspace,
        source_text=source_text,
        llm_config=llm_config,
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        timeout=int(timeout),
        retries=int(retries),
        retry_interval=int(retry_interval),
    )
    return (
        result["global_outline"],
        result["module9"],
        result["module10"],
        _status_text(workspace),
        (result.get("summary") or "全局大纲已生成。") + f"\n模型: {llm_config.provider}/{llm_config.model}",
    )


def save_global_callback(
    workspace_value: str,
    global_outline: str,
    module9: str,
    module10: str,
) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    write_global_outline(workspace, global_outline)
    write_module9(workspace, module9)
    write_module10(workspace, module10)
    return _status_text(workspace), "全局大纲、模块9、模块10已保存。"


def generate_next_callback(
    workspace_value: str,
    provider: str,
    api_key: str,
    env_file: str,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
    auto_mode: str,
    auto_count: int,
) -> tuple[Any, ...]:
    workspace = _workspace(workspace_value)
    llm_config = _resolve_config(provider, api_key, env_file, base_url, model)
    count = 1
    if auto_mode == "自动生成接下来 N 章":
        count = max(1, int(auto_count))
    elif auto_mode == "自动直到完成":
        state = read_state(workspace)
        current_next = state_summary(workspace)["next_chapter"]
        count = max(0, state.total_chapters - current_next + 1)

    if count == 1:
        result = generate_next_chapter_outline(
            workspace=workspace,
            llm_config=llm_config,
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            timeout=int(timeout),
            retries=int(retries),
            retry_interval=int(retry_interval),
        )
        message = result.get("progress_summary") or f"第 {result['chapter_index']} 章已生成。"
    else:
        results = generate_chapters_batch(
            workspace=workspace,
            llm_config=llm_config,
            count=count,
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            timeout=int(timeout),
            retries=int(retries),
            retry_interval=int(retry_interval),
        )
        message = f"自动生成完成: {len(results)} 章。"

    choices = _chapter_choices(workspace)
    selected = choices[-1] if choices else None
    selected_text = read_chapter_outline(workspace, _choice_to_index(selected)) if selected else ""
    return (
        gr.update(choices=choices, value=selected),
        selected_text,
        read_module9(workspace),
        read_module10(workspace),
        _status_text(workspace),
        message,
    )


def select_chapter_callback(workspace_value: str, chapter_choice: str) -> str:
    workspace = _workspace(workspace_value)
    chapter_index = _choice_to_index(chapter_choice)
    if chapter_index <= 0:
        return ""
    return read_chapter_outline(workspace, chapter_index)


def save_chapter_callback(
    workspace_value: str,
    chapter_choice: str,
    chapter_outline: str,
) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    chapter_index = _choice_to_index(chapter_choice)
    if chapter_index <= 0:
        raise gr.Error("请选择要保存的章节。")
    write_chapter_outline(workspace, chapter_index, chapter_outline)
    return _status_text(workspace), f"第 {chapter_index} 章大纲已保存。"


def save_module_state_callback(
    workspace_value: str,
    module9: str,
    module10: str,
) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    write_module9(workspace, module9)
    write_module10(workspace, module10)
    return _status_text(workspace), "模块9和模块10已保存。"


def build_abstract_callback(workspace_value: str) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    output_path = rebuild_final_abstract(workspace)
    return _status_text(workspace), f"已合并为 {output_path}"


def load_workspace_callback(workspace_value: str) -> tuple[Any, ...]:
    return _refresh_outputs(workspace_value) + ("工作区已加载。",)


def override_total_chapters_callback(workspace_value: str, total_chapters: int) -> tuple[str, str]:
    workspace = _workspace(workspace_value)
    if int(total_chapters) <= 0:
        raise gr.Error("目标章节数必须大于 0。")
    state = read_state(workspace)
    state.total_chapters = int(total_chapters)
    write_state(workspace, state)
    return _status_text(workspace), f"目标章节数已改为 {int(total_chapters)}。"


def create_app() -> gr.Blocks:
    with gr.Blocks(title="交互式小说大纲 Agent") as app:
        gr.Markdown("# 交互式小说大纲 Agent")
        gr.Markdown("先生成全局大纲，再按确认/自动模式逐章生成模块5；模块9和模块10会随每章更新。")
        gr.Markdown(f"⚠️ {LONG_CONTEXT_MODEL_HINT}")

        with gr.Row():
            workspace = gr.Textbox(
                label="Workspace",
                value="./outputs/my_novel_outline",
                scale=3,
            )
            load_workspace = gr.Button("加载工作区", scale=1)

        with gr.Accordion("Abstract/大纲 Agent 设置（建议百万上下文模型）", open=False):
            with gr.Row():
                provider = gr.Textbox(label="Provider", value=DEFAULT_PROVIDER)
                api_key = gr.Textbox(label="API Key", value=DEFAULT_API_KEY, type="password")
                env_file = gr.Textbox(label=".env 文件", value=".env")
            with gr.Row():
                base_url = gr.Textbox(label="base_url", value="")
                model = gr.Textbox(label="模型", value=DEFAULT_MODEL, placeholder="建议使用百万上下文模型")
            with gr.Row():
                max_tokens = gr.Number(label="max_tokens", value=DEFAULT_MAX_TOKENS, precision=0)
                temperature = gr.Number(label="temperature", value=DEFAULT_TEMPERATURE)
                timeout = gr.Number(label="timeout 秒", value=300, precision=0)
                retries = gr.Number(label="retries", value=3, precision=0)
                retry_interval = gr.Number(label="retry_interval 秒", value=5, precision=0)

        with gr.Row():
            status = gr.Textbox(label="状态", lines=7, interactive=False)
            log = gr.Textbox(label="日志", lines=7, interactive=False)

        with gr.Tab("1. 原文与全局大纲"):
            source_text = gr.Textbox(label="小说原文", lines=16)
            with gr.Row():
                save_source = gr.Button("保存原文并统计")
                generate_global = gr.Button("生成全局大纲", variant="primary")
            global_outline = gr.Textbox(label="除了模块5之外的全局大纲", lines=22)
            with gr.Row():
                target_chapters = gr.Number(label="手动覆盖目标章节数", value=0, precision=0)
                override_chapters = gr.Button("应用目标章节数")
                save_global = gr.Button("保存全局大纲/模块9/模块10")

        with gr.Tab("2. 模块5 逐章大纲"):
            with gr.Row():
                chapter_choice = gr.Dropdown(label="选择章节", choices=[])
                auto_mode = gr.Radio(
                    label="确认模式",
                    choices=["手动", "自动生成接下来 N 章", "自动直到完成"],
                    value="手动",
                )
                auto_count = gr.Number(label="N", value=3, precision=0)
            with gr.Row():
                generate_next = gr.Button("确认/生成下一章", variant="primary")
                save_chapter = gr.Button("保存当前章修改")
            chapter_outline = gr.Textbox(label="当前章节执行大纲", lines=28)

        with gr.Tab("3. 模块9/10 状态文件"):
            module9 = gr.Textbox(label="模块9：伏笔库当前状态", lines=18)
            module10 = gr.Textbox(label="模块10：节拍分布当前状态", lines=18)
            with gr.Row():
                save_module_state = gr.Button("保存模块9/10修改")
                build_abstract_btn = gr.Button("合并为 Abstract.txt", variant="primary")

        load_workspace.click(
            load_workspace_callback,
            inputs=[workspace],
            outputs=[source_text, global_outline, chapter_choice, chapter_outline, module9, module10, status, log],
        )
        save_source.click(save_source_callback, inputs=[workspace, source_text], outputs=[status, log])
        generate_global.click(
            generate_global_callback,
            inputs=[
                workspace,
                source_text,
                provider,
                api_key,
                env_file,
                base_url,
                model,
                max_tokens,
                temperature,
                timeout,
                retries,
                retry_interval,
            ],
            outputs=[global_outline, module9, module10, status, log],
        )
        save_global.click(
            save_global_callback,
            inputs=[workspace, global_outline, module9, module10],
            outputs=[status, log],
        )
        override_chapters.click(
            override_total_chapters_callback,
            inputs=[workspace, target_chapters],
            outputs=[status, log],
        )
        generate_next.click(
            generate_next_callback,
            inputs=[
                workspace,
                provider,
                api_key,
                env_file,
                base_url,
                model,
                max_tokens,
                temperature,
                timeout,
                retries,
                retry_interval,
                auto_mode,
                auto_count,
            ],
            outputs=[chapter_choice, chapter_outline, module9, module10, status, log],
        )
        chapter_choice.change(
            select_chapter_callback,
            inputs=[workspace, chapter_choice],
            outputs=[chapter_outline],
        )
        save_chapter.click(
            save_chapter_callback,
            inputs=[workspace, chapter_choice, chapter_outline],
            outputs=[status, log],
        )
        save_module_state.click(
            save_module_state_callback,
            inputs=[workspace, module9, module10],
            outputs=[status, log],
        )
        build_abstract_btn.click(build_abstract_callback, inputs=[workspace], outputs=[status, log])

    return app


def main() -> None:
    create_app().launch()


if __name__ == "__main__":
    main()

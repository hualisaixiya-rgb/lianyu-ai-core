"""Prompt 管理器。

负责加载、组合、渲染 Prompt 模板。
支持运行时动态注入变量（角色信息、记忆等）。
"""

from pathlib import Path

import yaml
from loguru import logger


class PromptManager:
    """Prompt 管理器。

    从 YAML 模板文件加载各类 Prompt，支持变量占位符替换。

    使用方式：
        pm = PromptManager()
        system_prompt = pm.render("system", character_prompt="...")
        memory_prompt = pm.render("memory", memories="...")
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        """初始化 Prompt 管理器。

        Args:
            templates_dir: Prompt 模板目录，默认为 templates/ 子目录
        """
        if templates_dir is None:
            templates_dir = Path(__file__).resolve().parent / "templates"
        self.templates_dir = Path(templates_dir)
        self._templates: dict[str, str] = {}
        self._load_all()
        logger.info(f"PromptManager 初始化完成，已加载 {len(self._templates)} 个模板")

    def _load_all(self) -> None:
        """加载 templates 目录下所有 YAML 模板文件。"""
        if not self.templates_dir.exists():
            logger.warning(f"Prompt 模板目录不存在: {self.templates_dir}")
            return

        for yaml_file in self.templates_dir.glob("*.yaml"):
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    for key, value in data.items():
                        self._templates[key] = value
                        logger.debug(f"加载模板: {yaml_file.name} -> {key}")

    def get(self, name: str) -> str | None:
        """获取原始模板（不含变量替换）。

        Args:
            name: 模板名称

        Returns:
            原始模板内容，不存在返回 None
        """
        return self._templates.get(name)

    def render(self, name: str, **kwargs: str) -> str:
        """渲染模板，替换其中的占位符变量。

        模板中使用 {variable_name} 标记占位符，
        渲染时替换为 kwargs 中对应的值。

        Args:
            name: 模板名称
            **kwargs: 键值对，用于替换模板中的占位符

        Returns:
            渲染后的文本。模板不存在时返回空字符串。
        """
        template = self._templates.get(name)
        if template is None:
            logger.warning(f"模板不存在: {name}")
            return ""

        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(f"模板 {name} 缺少变量: {e}")
            # 返回未渲染的模板，保留缺失的占位符便于调试
            return template

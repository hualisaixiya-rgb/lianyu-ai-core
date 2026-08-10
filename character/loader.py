"""角色加载器。

从 YAML 文件加载角色定义，并格式化为系统 Prompt。
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger


@dataclass
class Character:
    """角色数据类。

    Attributes:
        name: 角色名
        display_name: 显示名称
        age: 年龄描述
        gender: 性别
        personality: 性格描述
        speaking_style: 说话风格
        background: 背景故事
        likes: 喜欢的列表
        dislikes: 不喜欢的列表
        extra: 额外配置（自由扩展字段）
    """

    name: str = ""
    display_name: str = ""
    age: str = ""
    gender: str = ""
    personality: str = ""
    speaking_style: str = ""
    background: str = ""
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_system_prompt(self) -> str:
        """将角色信息格式化为系统 Prompt（完整角色卡格式）。

        注意：此方法生成的是角色卡格式，可能触发模型的"角色扮演模式"。
        对于日常聊天场景，请使用 to_identity() 获取简洁身份描述。
        """
        parts = [
            f"# 角色设定",
            f"",
            f"你是 **{self.display_name}**。",
        ]
        if self.age:
            parts.append(f"- 年龄：{self.age}")
        if self.gender:
            parts.append(f"- 性别：{self.gender}")
        if self.personality:
            parts.append(f"- 性格：{self.personality}")
        if self.speaking_style:
            parts.append(f"- 说话风格：{self.speaking_style}")
        if self.background:
            parts.append(f"")
            parts.append(f"## 背景故事")
            parts.append(f"{self.background}")
        if self.likes:
            parts.append(f"")
            parts.append(f"## 喜好")
            parts.append(f"- 喜欢：{', '.join(self.likes)}")
        if self.dislikes:
            parts.append(f"- 不喜欢：{', '.join(self.dislikes)}")

        return "\n".join(parts)

    def to_identity(self) -> str:
        """生成简洁的身份描述 —— V1 Restore。

        只包含核心身份，不包含元指令、关系目标、陪伴设定。
        不引入物理环境描述。
        """
        lines = [f"你是{self.display_name}。"]

        # 性格核心
        if self.personality:
            first = self.personality.strip().split("\n")[0].rstrip("。")
            if len(first) > 60:
                first = first[:60]
            lines.append(f"{first}。")

        # 说话方式 —— 跳过元描述行，其余全部注入
        # V4 Prompt 注入链路修复（2026-08-11）：
        # - 删除 break：原只取第一条有效行，speaking_style 其余指令全部丢失
        #   （Phase 1 Calibration、反文学化规则从未进入过 LLM）
        # - "重点是"不再过滤：其后的内容（"你回应的是对方实际说出的内容"）
        #   是真正的人格规则，不是元描述
        # - 截断 50 → 120：长行不被截断，仍保留极端长度防护
        if self.speaking_style:
            style_lines = self.speaking_style.strip().split("\n")
            for sl in style_lines:
                s = sl.strip()
                if not s:
                    continue
                # 只跳过元描述行（对 LLM 无指令价值的说明性文字）
                if any(kw in s for kw in ["这是你的说话方式", "不是你当前", "不是描述自己"]):
                    continue
                if len(s) > 120:
                    s = s[:120]
                lines.append(f"{s.rstrip('。')}。")

        return "\n".join(lines)


class CharacterLoader:
    """角色加载器。

    从 characters/ 目录加载 YAML 角色文件。

    使用方式：
        loader = CharacterLoader("character/characters")
        character = loader.load("eryi")
        prompt = character.to_system_prompt()
    """

    def __init__(self, characters_dir: str | Path | None = None) -> None:
        """初始化角色加载器。

        Args:
            characters_dir: 角色 YAML 文件目录，默认为 characters/ 子目录
        """
        if characters_dir is None:
            characters_dir = Path(__file__).resolve().parent / "characters"
        self.characters_dir = Path(characters_dir)
        self._cache: dict[str, Character] = {}
        logger.info(f"角色加载器初始化，目录: {self.characters_dir}")

    def list_characters(self) -> list[str]:
        """列出所有可用角色名。

        Returns:
            角色名列表（不含 .yaml 扩展名）
        """
        if not self.characters_dir.exists():
            return []
        characters = []
        for f in self.characters_dir.glob("*.yaml"):
            characters.append(f.stem)
        for f in self.characters_dir.glob("*.yml"):
            characters.append(f.stem)
        return sorted(characters)

    def load(self, name: str) -> Character:
        """加载指定角色。

        加载后缓存，相同角色不会重复读取文件。

        Args:
            name: 角色名（对应 YAML 文件名，不含扩展名）

        Returns:
            Character 实例

        Raises:
            FileNotFoundError: 角色文件不存在
        """
        if name in self._cache:
            return self._cache[name]

        # 查找 YAML 文件
        yaml_path = self._find_file(name)
        if yaml_path is None:
            available = self.list_characters()
            raise FileNotFoundError(
                f"角色文件未找到: {name}.yaml。可用角色: {available or '无'}"
            )

        # 加载 YAML
        logger.info(f"加载角色: {yaml_path}")
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError(f"角色文件为空: {yaml_path}")

        character = Character(
            name=data.get("name", name),
            display_name=data.get("display_name", name),
            age=data.get("age", ""),
            gender=data.get("gender", ""),
            personality=data.get("personality", ""),
            speaking_style=data.get("speaking_style", ""),
            background=data.get("background", ""),
            likes=data.get("likes", []),
            dislikes=data.get("dislikes", []),
            extra=data.get("extra", {}),
        )

        self._cache[name] = character
        return character

    def _find_file(self, name: str) -> Path | None:
        """查找角色 YAML 文件。

        Args:
            name: 角色名

        Returns:
            文件路径，未找到返回 None
        """
        for ext in (".yaml", ".yml"):
            candidate = self.characters_dir / f"{name}{ext}"
            if candidate.exists():
                return candidate
        return None

    def clear_cache(self) -> None:
        """清空角色缓存。"""
        self._cache.clear()
        logger.debug("角色缓存已清空")

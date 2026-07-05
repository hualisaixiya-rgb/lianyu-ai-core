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
        """生成简洁的身份描述——用于注入短信聊天场景的 System Prompt。

        返回纯文本短段落，不包含角色卡格式（无 # 标题、无列表标记）。
        这种格式不会触发模型的"角色扮演模式"。

        Returns:
            2-4 句纯文本身份描述
        """
        lines = []

        # 第一句：名字 + 核心特征
        name_part = f"你叫{self.display_name}。"
        if self.age and self.gender:
            gender_text = "女孩" if self.gender == "女" else "男孩"
            name_part = f"你叫{self.display_name}，一个{self.age}的{gender_text}。"
        lines.append(name_part)

        # 第二句：性格（取第一行）
        if self.personality:
            first_line = self.personality.strip().split("\n")[0].rstrip("。")
            if len(first_line) > 50:
                first_line = first_line[:50]
            lines.append(f"{first_line}。")

        # 第三句：说话方式（取第一行）
        if self.speaking_style:
            first_line = self.speaking_style.strip().split("\n")[0].rstrip("。")
            if len(first_line) > 50:
                first_line = first_line[:50]
            lines.append(f"{first_line}。")

        # 第四句：关键喜好
        if self.likes:
            top_likes = self.likes[:3]
            lines.append(f"你喜欢{', '.join(top_likes)}。")

        # 第五句：关键背景（Sakura、身份认知等）
        if self.background:
            # 取背景中最重要的身份信息行
            bg_lines = [l.strip() for l in self.background.strip().split("\n") if l.strip()]
            # 优先取提到名字的行（如 Sakura/路明非）
            key_lines = [l for l in bg_lines if "Sakura" in l or "路明非" in l or "不是AI" in l]
            if key_lines:
                lines.append(key_lines[0].rstrip("。") + "。")
            elif bg_lines:
                # 取最后一行（通常是身份总结）
                last = bg_lines[-1].rstrip("。")
                if len(last) > 50:
                    last = last[:50]
                lines.append(f"{last}。")

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

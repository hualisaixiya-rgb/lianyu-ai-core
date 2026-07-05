"""角色系统。

通过 YAML 文件定义角色，不修改 Python 代码即可切换角色。
支持角色的姓名、性格、说话风格、背景故事等全方位定义。
"""

from character.loader import CharacterLoader, Character

__all__ = ["CharacterLoader", "Character"]

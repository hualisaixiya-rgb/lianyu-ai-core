"""测试角色加载器。"""

from character.loader import CharacterLoader


class TestCharacterLoader:
    """测试角色加载器。"""

    def test_list_characters_empty(self, tmp_path):
        """测试空目录时列出角色。"""
        loader = CharacterLoader(tmp_path)
        chars = loader.list_characters()
        assert chars == []

    def test_load_nonexistent_character(self, tmp_path):
        """测试加载不存在的角色。"""
        loader = CharacterLoader(tmp_path)
        try:
            loader.load("nonexistent")
            assert False, "应该抛出 FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_character_to_system_prompt(self):
        """测试角色转系统 Prompt。"""
        from character.loader import Character

        c = Character(
            name="test",
            display_name="测试角色",
            age="18岁",
            personality="温柔善良",
            background="来自异世界的旅人",
        )
        prompt = c.to_system_prompt()
        assert "测试角色" in prompt
        assert "18岁" in prompt
        assert "温柔善良" in prompt
        assert "异世界" in prompt

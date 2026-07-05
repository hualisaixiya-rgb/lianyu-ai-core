"""测试计算器工具。"""

import pytest

from tools.builtin.calculator import calculator


class TestCalculator:
    """测试计算器。"""

    def test_simple_addition(self):
        """测试简单加法。"""
        result = calculator("1 + 2")
        assert result == "3"

    def test_multiplication(self):
        """测试乘法。"""
        result = calculator("3 * 4")
        assert result == "12"

    def test_complex_expression(self):
        """测试复合表达式。"""
        result = calculator("1 + 2 * 3")
        assert result == "7"

    def test_parentheses(self):
        """测试括号优先级。"""
        result = calculator("(1 + 2) * 3")
        assert result == "9"

    def test_negative_number(self):
        """测试负数。"""
        result = calculator("-5 + 3")
        assert result == "-2"

    def test_division(self):
        """测试除法。"""
        result = calculator("10 / 3")
        assert "3.33" in result

    def test_division_by_zero(self):
        """测试除以零的情况。"""
        result = calculator("1 / 0")
        assert "错误" in result or "error" in result.lower()

    def test_unsafe_expression(self):
        """测试不安全的表达式被拒绝。"""
        result = calculator("__import__('os').system('ls')")
        assert "错误" in result or "不支持" in result

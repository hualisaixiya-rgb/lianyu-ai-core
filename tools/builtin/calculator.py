"""计算器工具。

提供安全的基本数学运算。
"""

import ast
import operator
from typing import Any


# 允许的安全运算符
_SAFE_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> Any:
    """安全地计算 AST 节点。

    只允许基本算术运算，禁止函数调用、变量访问等。

    Args:
        node: AST 语法树节点

    Returns:
        计算结果

    Raises:
        ValueError: 遇到不安全的操作
    """
    match node:
        case ast.Constant(value):
            return value
        case ast.BinOp(left=left, op=op, right=right):
            left_val = _safe_eval(left)
            right_val = _safe_eval(right)
            op_type = type(op)
            if op_type in _SAFE_OPS:
                return _SAFE_OPS[op_type](left_val, right_val)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        case ast.UnaryOp(op=op, operand=operand):
            operand_val = _safe_eval(operand)
            op_type = type(op)
            if op_type in _SAFE_OPS:
                return _SAFE_OPS[op_type](operand_val)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        case _:
            raise ValueError(f"不支持的语法: {type(node).__name__}")


def calculator(expression: str) -> str:
    """安全地计算数学表达式。

    只支持基本算术运算（+, -, *, /, **, 负号），
    禁止任何函数调用或变量访问。

    Args:
        expression: 数学表达式字符串，如 "1 + 2 * 3"

    Returns:
        计算结果字符串，如 "7"

    Raises:
        ValueError: 表达式不合法
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree.body)
        return str(result)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        return f"计算错误: {e}"

"""每日世界状态生成器。

每天生成一组固定的天气 + 小观察，注入 System Prompt。
让绘梨衣拥有"今天的生活"，而不是每句话都现场编造。

用法：
    from utils.world_state import get_world_context
    context = get_world_context()
"""

import random
from datetime import date

# 天气池
WEATHERS = [
    "今天是个晴天。阳光在榻榻米上画了金色的格子。",
    "今天阴天。云层很厚，空气里有要下雨的味道。",
    "今天下雨。雨滴打在屋檐上，声音很轻。",
    "今天傍晚有风。窗帘被吹起来又落下去。",
    "今天是夏夜。蝉鸣从窗外涌进来。",
    "今天闷热。空气像被水泡过的棉花。",
    "今天凉爽。风里有秋天的预感。",
]

# 小事池
OBSERVATIONS = [
    "下午有一只白猫从院墙边走过。",
    "今天蝉一直叫。从早上叫到现在。",
    "风铃响了好几次。今天风挺大的。",
    "窗台上落了一片叶子。不知道从哪里吹来的。",
    "今天捡到一片很好看的树叶。放在窗台上了。",
    "傍晚有鸟从电线杆上飞走了。",
    "今天院子里的花开了。白色的那种。",
    "月亮出来得早。还没天黑就挂在天上了。",
]


def get_world_context() -> str:
    """获取今日世界状态——一天内保持不变。

    用日期做随机种子，同一天返回相同内容。

    Returns:
        格式化的世界描述文本
    """
    today = date.today()
    seed = today.toordinal()
    rng = random.Random(seed)

    weather = rng.choice(WEATHERS)
    obs = rng.choice(OBSERVATIONS)

    return f"今天是你生活里普通的一天。{weather} {obs}"

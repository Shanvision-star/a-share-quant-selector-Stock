"""
阿尔忒弥斯 I 环月轨迹数据生成器
坐标系：地月旋转参考系，地球在原点(0,0)，月球在(1,0)
单位：地月距离 = 1（实际约 384,400 km）

任务阶段（参考 Artemis I，2022年11月）：
  Phase 1 — 出地球轨道 / TLI（Trans-Lunar Injection）
  Phase 2 — 月球近旁飞掠（Outbound Lunar Flyby）
  Phase 3 — 远距逆行轨道（DRO，Distant Retrograde Orbit，顺时针）
  Phase 4 — 月球近旁返回飞掠（Return Lunar Flyby）
  Phase 5 — 返回地球 / TEI（Trans-Earth Injection）
"""

import random
import numpy as np


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _bezier3(p0, p1, p2, p3, n: int):
    """三阶贝塞尔曲线，返回 n 个点 [[x, y], ...]"""
    t = np.linspace(0, 1, n)
    b = ((1 - t) ** 3)[:, None] * np.array(p0) \
        + (3 * (1 - t) ** 2 * t)[:, None] * np.array(p1) \
        + (3 * (1 - t) * t ** 2)[:, None] * np.array(p2) \
        + (t ** 3)[:, None] * np.array(p3)
    return b.tolist()


def _arc(cx, cy, r, start_deg, end_deg, n: int, clockwise=False):
    """从 start_deg 到 end_deg 的圆弧（角度制）"""
    if clockwise:
        angles = np.linspace(np.radians(start_deg), np.radians(end_deg), n)
    else:
        angles = np.linspace(np.radians(start_deg), np.radians(end_deg), n)
    return [[cx + r * np.cos(a), cy + r * np.sin(a)] for a in angles]


# ── 主函数 ────────────────────────────────────────────────────────────────────

def _build_trajectory():
    """生成五阶段轨迹坐标列表，返回 (all_points, phase_boundaries)"""
    # --- Phase 1: 地球出发 → 月球近旁 (TLI) ---
    # 从地球附近 (0.08, 0) 贝塞尔弯向月球 (0.85, 0.22)
    p1 = _bezier3(
        [0.08, 0.02],
        [0.30, 0.40],
        [0.60, 0.38],
        [0.85, 0.22],
        n=80,
    )

    # --- Phase 2: 月球近旁飞掠 → DRO 插入 ---
    # 从 (0.85, 0.22) 开始绕月球后侧弧入 DRO 起点
    # DRO 中心在月球 (1.0, 0)，半径 0.17
    dro_cx, dro_cy, dro_r = 1.0, 0.0, 0.17
    # 飞掠弧：从月球左上方绕到 DRO 的 90° 位置（顶部）
    p2 = _bezier3(
        [0.85, 0.22],
        [0.92, 0.10],
        [0.96, 0.08],
        [dro_cx + dro_r * np.cos(np.radians(90)),
         dro_cy + dro_r * np.sin(np.radians(90))],
        n=30,
    )

    # --- Phase 3: DRO（逆行轨道，顺时针，约 1.5 圈）---
    # 顺时针：角度从 90° → 90° - 540° = -450°
    p3 = _arc(dro_cx, dro_cy, dro_r, 90, 90 - 540, n=200, clockwise=True)
    # DRO 结束在 90° - 540° mod 360 = 90° - 180° = -90° → 即 (1.0, -0.17)

    # --- Phase 4: DRO 离开 → 月球近旁返回飞掠 ---
    end_dro = [dro_cx + dro_r * np.cos(np.radians(-90)),
               dro_cy + dro_r * np.sin(np.radians(-90))]
    p4 = _bezier3(
        end_dro,
        [0.96, -0.08],
        [0.90, -0.18],
        [0.84, -0.22],
        n=30,
    )

    # --- Phase 5: 返回地球 (TEI) ---
    p5 = _bezier3(
        [0.84, -0.22],
        [0.55, -0.38],
        [0.28, -0.36],
        [0.07, -0.03],
        n=80,
    )

    all_pts = p1 + p2[1:] + p3[1:] + p4[1:] + p5[1:]
    phase_ends = [
        len(p1) - 1,
        len(p1) + len(p2) - 2,
        len(p1) + len(p2) + len(p3) - 3,
        len(p1) + len(p2) + len(p3) + len(p4) - 4,
        len(all_pts) - 1,
    ]
    return all_pts, phase_ends


def _build_moon_orbit(n=200):
    """月球公转轨道（背景线）"""
    t = np.linspace(0, 2 * np.pi, n)
    return [[float(np.cos(a)), float(np.sin(a))] for a in t]


def _build_stars(n=300, seed=42):
    """随机背景星点"""
    rng = random.Random(seed)
    return [[round(rng.uniform(-2.0, 2.5), 4), round(rng.uniform(-1.8, 1.8), 4)] for _ in range(n)]


# ── 对外接口 ──────────────────────────────────────────────────────────────────

def _get_moon_position(t: float) -> list:
    """根据时间 t 计算月球的位置"""
    return [float(np.cos(t)), float(np.sin(t))]


def get_trajectory_data(t: float = 0.0) -> dict:
    """
    返回前端 ECharts 动画所需的全部数据：
    - trajectory:   轨迹坐标列表 [[x,y], ...]
    - phase_ends:   各阶段最后一个点的索引
    - moon_orbit:   月球公转背景轨道
    - stars:        背景星点
    - earth:        地球位置 [x, y]
    - moon:         月球位置 [x, y]
    - phases:       阶段说明列表
    - axis_range:   建议的显示范围
    """
    traj, phase_ends = _build_trajectory()
    return {
        "trajectory": traj,
        "phase_ends": phase_ends,
        "moon_orbit": _build_moon_orbit(),
        "stars": _build_stars(),
        "earth": [0.0, 0.0],
        "moon": _get_moon_position(t),  # 动态计算月球位置
        "phases": [
            {"idx": 0, "name": "TLI 出发",          "color": "#4fc3f7"},
            {"idx": 1, "name": "月球飞掠（去）",     "color": "#81c784"},
            {"idx": 2, "name": "远距逆行轨道 (DRO)", "color": "#ffb74d"},
            {"idx": 3, "name": "月球飞掠（返）",     "color": "#ce93d8"},
            {"idx": 4, "name": "TEI 返回",           "color": "#ef9a9a"},
        ],
        "axis_range": {
            "x": [-2.5, 2.5],
            "y": [-2.0, 2.0],
        },
    }

# 下界の抜け道（合成 800 台×48 時間。LP 緩和と、最良の解の起動停止を固定した LP の費用の差）
#   1 文目: 差 9.94 億を費用ごとに分けると、ほぼ全部（99.6%）が起動の費用
#   2 文目: LP では運転 u が 0.5 のような値を取れ、止めていないのに温起動の条件（直前 4 時間の Σu ≥ 1）を満たす
#   3 文目: 「直前 4 時間に停止 w があるときだけ温起動」と数え直すと Σw = 0 で、温起動にならない
# 2・3 文目の 0.5 × 4 時間は、仕組みを見せるための説明用の値（実測では LNG 機の 3,178 機・時間が半端な値）
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()

DIFF = [("燃料", 0.02), ("無負荷", -0.03), ("停止", 0.04), ("起動", 9.90)]   # 億、最良の解 − LP


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height

        # 1 文目: 費用ごとの差の棒
        scale = FW * 0.05                       # 1 億あたりの長さ
        x0 = -FW * 0.18
        rows = VGroup()
        for i, (name, d) in enumerate(DIFF):
            yy = FH * 0.27 - i * 0.62
            lab = Text(name, font=JP, color=C.INK, font_size=26).move_to([x0 - 0.9, yy, 0])
            color = C.ORANGE if name == "起動" else C.SUB
            bar = Rectangle(width=max(abs(d) * scale, 0.04), height=0.36, fill_color=color, fill_opacity=0.9,
                            stroke_width=0)
            bar.move_to([x0 + (abs(d) * scale) / 2 * (1 if d >= 0 else -1), yy, 0])
            val = Text(f"{d:+.2f} 億", font=JP, color=color, font_size=24).next_to(bar, RIGHT, buff=0.15)
            rows.add(VGroup(lab, bar, val))
        zero = Line([x0, FH * 0.27 + 0.4, 0], [x0, FH * 0.27 - 3 * 0.62 - 0.4, 0], color=C.INK, stroke_width=2)
        self.play(Create(zero), run_time=0.5)
        self.play(LaggedStart(*[FadeIn(r[0]) for r in rows], lag_ratio=0.15), run_time=0.8)
        self.play(LaggedStart(*[AnimationGroup(GrowFromEdge(r[1], LEFT), FadeIn(r[2])) for r in rows],
                              lag_ratio=0.3), run_time=1.8)
        share = Text("差のほぼ全部（99.6%）が起動の費用", font=JP, color=C.ORANGE, font_size=26)
        share.next_to(rows, DOWN, buff=0.45)
        self.play(Indicate(rows[3], color=C.ORANGE, scale_factor=1.05), FadeIn(share), run_time=1.2)
        beat.until(1)

        # 2 文目: 半端な運転で温起動の条件を満たす
        chart = VGroup(zero, rows, share)
        self.play(FadeOut(chart), run_time=0.6)
        cell = 0.9
        left = -cell * 2.5
        hours = VGroup(*[Text(t, font=JP, color=C.SUB, font_size=20).move_to([left + k * cell, FH * 0.3, 0])
                         for k, t in enumerate(["4時間前", "3", "2", "1", "起動"])])
        u_name = Text("運転 u", font=JP, color=C.INK, font_size=24).move_to([left - 1.3, FH * 0.12, 0])
        w_name = Text("停止 w", font=JP, color=C.INK, font_size=24).move_to([left - 1.3, -FH * 0.08, 0])
        u_boxes, w_boxes = VGroup(), VGroup()
        for k in range(4):
            box = Square(cell * 0.8, color=C.INK, stroke_width=2).move_to([left + k * cell, FH * 0.12, 0])
            fill = Rectangle(width=cell * 0.8, height=cell * 0.4, fill_color=C.BLUE, fill_opacity=0.7, stroke_width=0)
            fill.align_to(box, DOWN).align_to(box, LEFT)
            num = Text("0.5", font=JP, color=C.INK, font_size=20).move_to(box)
            u_boxes.add(VGroup(box, fill, num))
            wbox = Square(cell * 0.8, color=C.INK, stroke_width=2).move_to([left + k * cell, -FH * 0.08, 0])
            w_boxes.add(VGroup(wbox, Text("0", font=JP, color=C.INK, font_size=20).move_to(wbox)))
        start = Arrow([left + 4 * cell, FH * 0.12 - 0.6, 0], [left + 4 * cell, FH * 0.12 + 0.3, 0],
                      color=C.INK, buff=0, stroke_width=5)
        old = Text("Σu = 2 ≥ 1 → 温起動にしてよい？", font=JP, color=C.RED, font_size=26).move_to([0, -FH * 0.3, 0])
        self.play(FadeIn(hours), FadeIn(u_name), LaggedStart(*[FadeIn(b) for b in u_boxes], lag_ratio=0.2),
                  run_time=1.6)
        self.play(GrowArrow(start), run_time=0.6)
        self.play(Write(old), Indicate(u_boxes, color=C.RED, scale_factor=1.03), run_time=1.4)
        beat.until(2)

        # 3 文目: 停止の記録で数え直す
        new = Text("Σw = 0 → 止めていないので温起動はできない", font=JP, color=C.GREEN, font_size=26).move_to(old)
        self.play(FadeIn(w_name), LaggedStart(*[FadeIn(b) for b in w_boxes], lag_ratio=0.2), run_time=1.2)
        self.play(Indicate(w_boxes, color=C.GREEN, scale_factor=1.05), run_time=0.8)
        self.play(FadeOut(old, shift=UP * 0.2), FadeIn(new, shift=UP * 0.2), run_time=1.0)
        self.play(Create(SurroundingRectangle(VGroup(w_name, w_boxes), color=C.GREEN, buff=0.12)), run_time=0.8)
        beat.finish()

# 上界と下界の挟み撃ち（合成 800 台×48 時間の実測。gpu3060・1 スレッド・各 900 秒）
#   1 文目: 見つけた計画の費用が上界（最適値はこれより高くない）
#   2 文目: 下界（どんな計画でもこれより安くできない保証）
#   3 文目: 最適値は 736.25〜744.44 億の間、幅 1.1%
#   4 文目: ローリングで作った解 745.27 億は、最適値から多くても 1.2%
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()

UB, LB, ROLL = 744.44, 736.25, 745.27
LO, HI = 730, 750


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height
        height = FH * 0.78
        ax_x = -FW * 0.36
        y = lambda v: -height / 2 + height * (v - LO) / (HI - LO)
        axis = Line([ax_x, y(LO), 0], [ax_x, y(HI), 0], color=C.INK, stroke_width=3)
        ticks = VGroup(*[Line([ax_x - 0.08, y(v), 0], [ax_x + 0.08, y(v), 0], color=C.INK, stroke_width=2)
                         for v in range(LO, HI + 1, 5)])
        nums = VGroup(*[Text(str(v), font=JP, color=C.SUB, font_size=20).next_to([ax_x - 0.1, y(v), 0], LEFT, buff=0.1)
                        for v in range(LO, HI + 1, 5)])
        unit = Text("費用（億）", font=JP, color=C.SUB, font_size=20).next_to(axis, UP, buff=0.15)
        x0, x1 = ax_x + 0.2, ax_x + FW * 0.2

        def level(v, color, dashed=False):
            cls = DashedLine if dashed else Line
            return cls([x0, y(v), 0], [x1, y(v), 0], color=color, stroke_width=4 if dashed else 6)

        def label(text, line, color, dy=0.0):
            return Text(text, font=JP, color=color, font_size=22).next_to(line, RIGHT, buff=0.2).shift(UP * dy)

        # 1 文目: 上界の線が上から降りてくる
        ub = level(UB, C.BLUE)
        ub_lab = label(f"上界 {UB:.2f}（見つけた解の費用）", ub, C.BLUE, -0.17)
        self.play(Create(axis), Create(ticks), FadeIn(nums), FadeIn(unit), run_time=1.0)
        self.play(TransformFromCopy(ub.copy().shift(UP * (y(HI) - y(UB))), ub),
                  FadeIn(ub_lab, shift=DOWN * 0.2), run_time=1.4)
        beat.until(1)

        # 2 文目: 下界の線が下から上がってくる
        lb = level(LB, C.GREEN)
        lb_lab = label(f"下界 {LB:.2f}（これより安くならない）", lb, C.GREEN)
        self.play(TransformFromCopy(lb.copy().shift(DOWN * (y(LB) - y(LO))), lb),
                  FadeIn(lb_lab, shift=UP * 0.2), run_time=1.4)
        beat.until(2)

        # 3 文目: 間を塗り、幅を言う
        band = Rectangle(width=x1 - x0, height=y(UB) - y(LB), fill_color=C.ORANGE, fill_opacity=0.18,
                         stroke_width=0).move_to([(x0 + x1) / 2, (y(UB) + y(LB)) / 2, 0])
        gap = Text("最適値は\nこの間\n幅 1.1%", font=JP, color=C.ORANGE, font_size=24, line_spacing=0.8).move_to(band)
        self.play(FadeIn(band), run_time=0.8)
        self.play(Write(gap), run_time=1.0)
        beat.until(3)

        # 4 文目: ローリングの解は上界のすぐ上
        roll = level(ROLL, C.SUB, dashed=True)
        roll_lab = label(f"ローリングの解 {ROLL:.2f}", roll, C.SUB, 0.17)
        self.play(Create(roll), FadeIn(roll_lab), run_time=1.0)
        self.play(Indicate(roll_lab, color=C.INK, scale_factor=1.05), run_time=0.8)
        beat.finish()

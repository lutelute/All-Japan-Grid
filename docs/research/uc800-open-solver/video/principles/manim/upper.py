# 上界は、0 と 1 で成り立つ計画を 1 つ見つければ出る（3 台の例）
#   1 文目: A と C を動かす計画（A 200 MW・C 50 MW）は費用 4700 → 上界
#   2 文目: 最適値は 4100 と 4700 の間
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()

INTEGER = [(4550, "A+B"), (4700, "A+C"), (5750, "A+B+C"), (6500, "B+C")]
LO, HI = 4000, 6700


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height
        x0, x1 = -FW * 0.40, FW * 0.40
        xv = lambda v: x0 + (x1 - x0) * (v - LO) / (HI - LO)
        line = Line([x0, -0.6, 0], [x1, -0.6, 0], color=C.INK, stroke_width=3)
        ticks = VGroup(*[VGroup(Line([xv(v), -0.68, 0], [xv(v), -0.52, 0], color=C.INK, stroke_width=2),
                                Text(str(v), font=JP, color=C.SUB, font_size=20).move_to([xv(v), -0.95, 0]))
                         for v in range(4000, 6701, 500)])
        dots = VGroup(*[Dot([xv(v), -0.6, 0], radius=0.09, color=C.SUB) for v, _ in INTEGER])
        lp = Dot([xv(4100), -0.6, 0], radius=0.12, color=C.GREEN)
        lp_lab = Text("下界 4100", font=JP, color=C.GREEN, font_size=26).next_to(lp, DOWN, buff=0.6).shift(LEFT * 1.0)
        self.add(line, ticks, dots, lp, lp_lab)

        # 1 文目: A+C の計画を見つける
        plan = VGroup(
            Text("A を 200MW、C を 50MW で動かす", font=JP, color=C.INK, font_size=26),
            Text("0 と 1 だけで、需要 250MW を満たす", font=JP, color=C.SUB, font_size=22),
        ).arrange(DOWN, buff=0.15).move_to([xv(4700), 1.9, 0])
        ub = Dot([xv(4700), -0.6, 0], radius=0.13, color=C.BLUE)
        ub_lab = Text("上界 4700", font=JP, color=C.BLUE, font_size=26).next_to(ub, UP, buff=0.35)
        self.play(FadeIn(plan, shift=DOWN * 0.2), run_time=1.0)
        self.play(TransformFromCopy(plan[0], ub), FadeIn(ub_lab), run_time=1.2)
        self.play(Indicate(ub_lab, color=C.BLUE, scale_factor=1.1), run_time=0.8)
        beat.until(1)

        # 2 文目: 最適値は 4100 と 4700 の間
        band = Rectangle(width=xv(4700) - xv(4100), height=0.5, fill_color=C.ORANGE, fill_opacity=0.25,
                         stroke_width=0).move_to([(xv(4100) + xv(4700)) / 2, -0.6, 0])
        tag = Text("最適値はこの間", font=JP, color=C.ORANGE, font_size=26).next_to(band, DOWN, buff=1.1)
        self.play(FadeIn(band), FadeIn(tag), run_time=1.0)
        self.play(Create(SurroundingRectangle(VGroup(band, tag), color=C.ORANGE, buff=0.12)), run_time=0.8)
        beat.finish()

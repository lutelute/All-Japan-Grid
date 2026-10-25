# 緩めると下界が出る（3 台・1 時間・需要 250 MW の例。値は HiGHS の LP で確かめた）
#   1 文目: 動かす(1)か止める(0)かを、0〜1 の好きな値に緩める
#   2 文目: A=1・B=1/3・C=0、費用 4100
#   3 文目: 選べる範囲を広げた最安値なので、本当の最安値はこれより安くならない → 下界
# 0 と 1 で成り立つ計画の費用: A+B 4550、A+C 4700、A+B+C 5750、B+C 6500（ほかの組は需要を満たせない）
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()

U = {"A": 1.0, "B": 1 / 3, "C": 0.0}
LABEL = {"A": "1", "B": "1/3", "C": "0"}
INTEGER = [(4550, "A+B"), (4700, "A+C"), (5750, "A+B+C"), (6500, "B+C")]
LO, HI = 4000, 6700


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height
        left = -FW * 0.36
        bars = VGroup()
        for i, name in enumerate("ABC"):
            x = left + i * 2.0
            frame = Rectangle(width=0.8, height=2.4, color=C.INK, stroke_width=2).move_to([x, 0.2, 0])
            lab = Text(name, font=JP, color=C.INK, font_size=30).next_to(frame, DOWN, buff=0.2)
            sw = Text("0 か 1", font=JP, color=C.SUB, font_size=22).next_to(frame, UP, buff=0.2)
            bars.add(VGroup(frame, lab, sw))
        title = Text("動かす(1)か、止める(0)か", font=JP, color=C.INK, font_size=26).move_to([left + 2.0, FH / 2 - 0.5, 0])

        # 1 文目: 二択を 0〜1 に緩める
        self.play(FadeIn(title), LaggedStart(*[FadeIn(b) for b in bars], lag_ratio=0.2), run_time=1.4)
        new_sw = VGroup(*[Text("0〜1", font=JP, color=C.BLUE, font_size=22).move_to(b[2]) for b in bars])
        self.play(*[Transform(b[2], n) for b, n in zip(bars, new_sw)], run_time=1.0)
        beat.until(1)

        # 2 文目: A=1・B=1/3・C=0、費用 4100
        fills, vals = VGroup(), VGroup()
        for b, name in zip(bars, "ABC"):
            frame = b[0]
            h = max(U[name] * 2.4, 0.001)
            fill = Rectangle(width=0.8, height=h, fill_color=C.BLUE, fill_opacity=0.75, stroke_width=0)
            fill.align_to(frame, DOWN).align_to(frame, LEFT)
            fills.add(fill)
            vals.add(Text(f"u = {LABEL[name]}", font=JP, color=C.BLUE, font_size=22).next_to(frame, RIGHT, buff=0.1).shift(DOWN * 0.9))
        cost = Text("費用 4100", font=JP, color=C.GREEN, font_size=30).move_to([left + 2.0, -FH / 2 + 0.55, 0])
        self.play(LaggedStart(*[GrowFromEdge(f, DOWN) for f in fills], lag_ratio=0.3), run_time=1.5)
        self.play(FadeIn(vals), Write(cost), run_time=1.0)
        self.play(Indicate(vals[1], color=C.ORANGE, scale_factor=1.2), run_time=0.8)
        beat.until(2)

        # 3 文目: 数直線に、0 と 1 で成り立つ計画の費用と 4100 を並べる
        x0, x1 = FW * 0.04, FW * 0.45
        xv = lambda v: x0 + (x1 - x0) * (v - LO) / (HI - LO)
        line = Line([x0, -0.4, 0], [x1, -0.4, 0], color=C.INK, stroke_width=3)
        ticks = VGroup(*[VGroup(Line([xv(v), -0.48, 0], [xv(v), -0.32, 0], color=C.INK, stroke_width=2),
                                Text(str(v), font=JP, color=C.SUB, font_size=18).move_to([xv(v), -0.75, 0]))
                         for v in range(4000, 6701, 500)])
        cap = Text("費用", font=JP, color=C.SUB, font_size=20).move_to([x1 + 0.4, -0.4, 0])
        dots = VGroup()
        for i, (v, name) in enumerate(INTEGER):
            d = Dot([xv(v), -0.4, 0], radius=0.09, color=C.INK)
            t = Text(f"{name}\n{v}", font=JP, color=C.INK, font_size=18, line_spacing=0.8).next_to(d, UP, buff=0.2 + (i % 2) * 0.55)
            dots.add(VGroup(d, t))
        note = Text("0 と 1 で成り立つ計画", font=JP, color=C.SUB, font_size=20).move_to([(xv(4550) + xv(6500)) / 2, 1.9, 0])
        lp = Dot([xv(4100), -0.4, 0], radius=0.12, color=C.GREEN)
        lp_lab = Text("下界 4100", font=JP, color=C.GREEN, font_size=26).next_to(lp, DOWN, buff=0.55)
        arrow = Arrow([xv(4100), -1.5, 0], [xv(4550) - 0.05, -1.5, 0], color=C.GREEN, buff=0, stroke_width=4)
        arrow_lab = Text("本当の最安値は、ここより右", font=JP, color=C.GREEN, font_size=20).next_to(arrow, DOWN, buff=0.1)
        self.play(Create(line), FadeIn(ticks), FadeIn(cap), run_time=0.8)
        self.play(FadeIn(note), LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.2), run_time=1.4)
        self.play(TransformFromCopy(cost, lp), FadeIn(lp_lab), run_time=1.0)
        self.play(GrowArrow(arrow), FadeIn(arrow_lab), run_time=1.0)
        beat.finish()

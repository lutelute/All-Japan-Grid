# 強い書き方 = 0 と 1 の答えを残したまま、緩めた範囲を小さくする（説明用の 2 変数の図）
#   1 文目: 点（0 と 1 で成り立つ答え）は全部残し、ゆるい範囲（三角形）を点に沿った範囲に縮める
#   2 文目: 費用が下がる向きに線を動かすと、緩めた問題の最安値が上がる → 下界が上がる
#   3 文目: 800 台・48 時間では、起動の数え方を直す式で幅が 1.1% → 0.57%
# 費用は x + y（左下ほど安い）。ゆるい範囲の最安は (0.5, 0.5)、点に沿った範囲の最安は (1, 1)
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()

POINTS = [(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (1, 3)]
LOOSE = [(0.5, 0.5), (3.9, 0.5), (0.5, 3.9)]
TIGHT = [(1, 1), (3, 1), (2, 2), (1, 3)]


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height
        ox, oy, sx, sy = -FW * 0.40, -FH / 2 + 0.55, 1.25, 1.15
        P = lambda x, y: [ox + sx * x, oy + sy * y, 0]
        axes = VGroup(Arrow(P(0, 0), P(4.4, 0), buff=0, color=C.SUB, stroke_width=2),
                      Arrow(P(0, 0), P(0, 4.4), buff=0, color=C.SUB, stroke_width=2))
        dots = VGroup(*[Dot(P(*q), radius=0.08, color=C.INK) for q in POINTS])
        loose = Polygon(*[P(*q) for q in LOOSE], color=C.ORANGE, fill_color=C.ORANGE, fill_opacity=0.15, stroke_width=3)
        tight = Polygon(*[P(*q) for q in TIGHT], color=C.GREEN, fill_color=C.GREEN, fill_opacity=0.2, stroke_width=3)
        note = Text("説明用の図（2 変数）", font=JP, color=C.SUB, font_size=18).next_to(P(4.4, 0), UP, buff=0.15).shift(LEFT * 0.6)
        tx = 0.4
        say1 = Text("● 0 と 1 で成り立つ答えは、全部残す", font=JP, color=C.INK, font_size=22).move_to([tx, 1.9, 0], aligned_edge=LEFT)
        say1.align_to([tx, 0, 0], LEFT)

        # 1 文目: ゆるい範囲を、点に沿った範囲に縮める
        self.play(Create(axes), FadeIn(dots), FadeIn(note), run_time=1.0)
        self.play(Create(loose), run_time=0.8)
        lab_loose = Text("ゆるい書き方", font=JP, color=C.ORANGE, font_size=22).next_to(P(3.2, 1.4), RIGHT, buff=0.1)
        self.play(FadeIn(lab_loose), FadeIn(say1), run_time=0.8)
        self.play(TransformFromCopy(loose, tight), run_time=1.4)
        lab_tight = Text("強い書き方", font=JP, color=C.GREEN, font_size=22).move_to(P(2.1, 0.75))
        self.play(FadeIn(lab_tight), run_time=0.6)
        beat.until(1)

        # 2 文目: 費用の線を左下へ動かすと、最安値の位置が上がる
        iso_loose = DashedLine(P(0, 1.0), P(1.0, 0), color=C.ORANGE, stroke_width=3)
        iso_tight = DashedLine(P(0, 2.0), P(2.0, 0), color=C.GREEN, stroke_width=3)
        best_loose = Dot(P(0.5, 0.5), radius=0.12, color=C.ORANGE)
        best_tight = Dot(P(1, 1), radius=0.12, color=C.GREEN)
        arrow = Arrow(P(3.7, 3.0), P(3.0, 2.3), buff=0, color=C.SUB, stroke_width=4)
        cheap = Text("費用が下がる向き", font=JP, color=C.SUB, font_size=20).next_to(arrow.get_start(), UP, buff=0.1)
        say2 = Text("● 緩めた問題の最安値が上がる ＝ 下界が上がる", font=JP, color=C.INK, font_size=22)
        say2.next_to(say1, DOWN, buff=0.45, aligned_edge=LEFT)
        self.play(GrowArrow(arrow), FadeIn(cheap), run_time=0.8)
        self.play(Create(iso_loose), FadeIn(best_loose), run_time=0.8)
        self.play(TransformFromCopy(iso_loose, iso_tight), TransformFromCopy(best_loose, best_tight), run_time=1.2)
        self.play(FadeIn(say2), run_time=0.6)
        beat.until(2)

        # 3 文目: 800 台の結果
        say3 = Text("● 800 台・48 時間：幅 1.1% → 0.57%", font=JP, color=C.GREEN, font_size=26)
        say3.next_to(say2, DOWN, buff=0.6, aligned_edge=LEFT)
        self.play(Write(say3), run_time=1.0)
        self.play(Create(SurroundingRectangle(say3, color=C.GREEN, buff=0.15)), run_time=0.8)
        beat.finish()

# 枝分かれして、切っていく（3 台の例。各節点の値は HiGHS の LP で確かめた）
#   根 4100（B=1/3）→ B=0: 4600（C=1/2）／ B=1: 4425（A=7/8）
#   B=1 の下 → A=1: 4550（0 と 1 がそろった計画）／ A=0: 6500
#   1 文目: 半端な B を 0 と 1 に分け、それぞれを緩めて解く
#   2 文目: 4600 と 4425、下界は 4425 に上がる
#   3 文目: 4425 の側で A を分けると 4550 の計画が出て、上界が 4700 → 4550
#   4 文目: 6500 と 4600 は 4550 より高いので切る
#   5 文目: 下界も 4550 になり、上界と一致 → 最適の証明
import os
import sys

sys.path.insert(0, os.environ.get("VK_LIB", "/opt/video-kit/lib"))
from vkmanim import *  # noqa: E402,F403

setup()


def node(text, pos, color=None):
    box = RoundedRectangle(width=2.6, height=0.95, corner_radius=0.12, color=color or C.INK, stroke_width=2.5).move_to(pos)
    lab = Text(text, font=JP, color=color or C.INK, font_size=22, line_spacing=0.8).move_to(pos)
    return VGroup(box, lab)


def edge(a, b, text):
    line = Line(a.get_bottom(), b.get_top(), color=C.SUB, stroke_width=2.5)
    lab = Text(text, font=JP, color=C.SUB, font_size=20).next_to(line.get_center(), LEFT if b.get_x() < a.get_x() else RIGHT, buff=0.15)
    return VGroup(line, lab)


class Main(Scene):
    def construct(self):
        beat = Beats(self)
        FW, FH = config.frame_width, config.frame_height
        y0, y1, y2 = FH / 2 - 0.85, 0.05, -FH / 2 + 0.85
        P_ROOT, P_B0, P_B1 = [-2.6, y0, 0], [-5.8, y1, 0], [0.4, y1, 0]
        P_A1, P_A0 = [-1.4, y2, 0], [2.2, y2, 0]
        px = FW / 2 - 1.9

        def panel_value(label, value, color, y):
            return VGroup(Text(label, font=JP, color=color, font_size=24),
                          Text(f"{value}", font=JP, color=color, font_size=40)).arrange(RIGHT, buff=0.3).move_to([px, y, 0])

        ub = panel_value("上界", 4700, C.BLUE, 1.2)
        lb = panel_value("下界", 4100, C.GREEN, 0.0)
        root = node("根　4100\nB = 1/3", P_ROOT)
        self.add(ub, lb)
        self.play(FadeIn(root), run_time=0.6)

        # 1 文目: B を 0 と 1 に分ける
        b0, b1 = node("?", P_B0), node("?", P_B1)
        e_b0, e_b1 = edge(root, b0, "B = 0"), edge(root, b1, "B = 1")
        self.play(Indicate(root[1], color=C.ORANGE, scale_factor=1.1), run_time=0.8)
        self.play(Create(e_b0), Create(e_b1), FadeIn(b0), FadeIn(b1), run_time=1.2)
        beat.until(1)

        # 2 文目: 4600 と 4425、下界は 4425 に上がる
        b0_new, b1_new = node("4600\nC = 1/2", P_B0), node("4425\nA = 7/8", P_B1)
        self.play(Transform(b0, b0_new), Transform(b1, b1_new), run_time=1.0)
        self.play(Transform(lb, panel_value("下界", 4425, C.GREEN, 0.0)), run_time=0.8)
        beat.until(2)

        # 3 文目: A を分けると 4550 の計画、上界が下がる
        a1, a0 = node("4550\n0 と 1 がそろった", P_A1, C.BLUE), node("6500", P_A0)
        e_a1, e_a0 = edge(b1, a1, "A = 1"), edge(b1, a0, "A = 0")
        self.play(Create(e_a1), Create(e_a0), FadeIn(a1), FadeIn(a0), run_time=1.2)
        self.play(Transform(ub, panel_value("上界", 4550, C.BLUE, 1.2)), Indicate(a1, color=C.BLUE, scale_factor=1.05), run_time=1.0)
        beat.until(3)

        # 4 文目: 4550 より高い枝を切る
        cut = Text("4550 より高い → 切る", font=JP, color=C.RED, font_size=22).move_to([px, -1.4, 0])
        crosses = VGroup(*[Cross(n[0], stroke_color=C.RED, stroke_width=5) for n in (a0, b0)])
        self.play(Create(crosses), FadeIn(cut), a0.animate.set_opacity(0.35), b0.animate.set_opacity(0.35), run_time=1.4)
        beat.until(4)

        # 5 文目: 下界も 4550、上界と一致
        self.play(Transform(lb, panel_value("下界", 4550, C.GREEN, 0.0)), run_time=0.8)
        proof = Text("下界 ＝ 上界\n→ 4550 が最適", font=JP, color=C.GREEN, font_size=26, line_spacing=0.85).move_to([px, -2.4, 0])
        self.play(FadeOut(cut), Write(proof), run_time=1.0)
        self.play(Create(SurroundingRectangle(VGroup(ub, lb), color=C.GREEN, buff=0.2)), run_time=0.8)
        beat.finish()

"""Toy UC for the explainer: 3 units, 1 hour, demand 250. Solve the LP at each branch-and-bound node."""
import itertools
import highspy
import numpy as np

UNITS = {"A": (200, 1000, 10), "B": (150, 300, 20), "C": (100, 200, 30)}   # cap, no-load, marginal
D = 250
names = list(UNITS)


def solve(fix):
    h = highspy.Highs(); h.setOptionValue("output_flag", False)
    # columns: u_A,u_B,u_C,p_A,p_B,p_C
    cost, lo, hi = [], [], []
    for n in names:
        cap, nl, mc = UNITS[n]
        cost.append(nl); lo.append(fix.get(n, 0.0)); hi.append(fix.get(n, 1.0))
    for n in names:
        cost.append(UNITS[n][2]); lo.append(0.0); hi.append(UNITS[n][0])
    h.addVars(6, np.array(lo), np.array(hi))
    h.changeColsCost(6, np.arange(6, dtype=np.int32), np.array(cost, dtype=float))
    h.addRow(D, D, 3, np.array([3, 4, 5], dtype=np.int32), np.ones(3))            # balance
    for i, n in enumerate(names):
        cap = UNITS[n][0]
        h.addRow(-np.inf, 0, 2, np.array([3 + i, i], dtype=np.int32), np.array([1.0, -cap]))        # p <= cap*u
        h.addRow(0, np.inf, 2, np.array([3 + i, i], dtype=np.int32), np.array([1.0, -cap / 2]))     # p >= pmin*u
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        return None, None
    x = h.getSolution().col_value
    return h.getInfo().objective_function_value, {n: round(x[i], 3) for i, n in enumerate(names)} | {"p" + n: round(x[3 + i], 1) for i, n in enumerate(names)}


for fix in [{}, {"B": 0}, {"B": 1}, {"B": 1, "A": 1}, {"B": 1, "A": 0}, {"A": 1, "C": 1, "B": 0}]:
    print(fix, *solve(fix))
best = None
for combo in itertools.product([0, 1], repeat=3):
    obj, _ = solve(dict(zip(names, combo)))
    print("integer", combo, obj)

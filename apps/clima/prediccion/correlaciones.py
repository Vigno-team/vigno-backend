import numpy as np
from scipy.stats import spearmanr


def calcular_spearman_holm(df, col_x, col_y, n_perm=999):
    valid = df[[col_x, col_y]].dropna()
    n = len(valid)
    if n < 5:
        return None, None, n

    x, y = valid[col_x].values, valid[col_y].values
    rho, _ = spearmanr(x, y)
    if np.isnan(rho):
        return None, None, n

    # Cálculo de P-value por permutaciones
    count = 0
    y_perm = np.copy(y)
    for _ in range(n_perm):
        np.random.shuffle(y_perm)
        r_perm, _ = spearmanr(x, y_perm)
        if abs(r_perm) >= abs(rho):
            count += 1

    p_val = (count + 1) / (n_perm + 1)
    return float(rho), float(p_val), n


def aplicar_holm(resultados):
    res_sorted = sorted(resultados, key=lambda x: x["p"])
    m = len(res_sorted)
    for k, r in enumerate(res_sorted):
        r["p_holm"] = min(1.0, r["p"] * (m - k))
    # Forzar la monotonicidad de Holm
    for k in range(1, m):
        res_sorted[k]["p_holm"] = max(res_sorted[k]["p_holm"], res_sorted[k - 1]["p_holm"])
    return res_sorted

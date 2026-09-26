"""主脑开仓的"顺势浮盈加仓"闸门判定（B3 抽取第十四块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 的**长/空两个分支**各搬出
一段同构判定并合并为一处。

## 这块在解决什么

金字塔加仓（pyramiding）是唯一允许"在已有持仓上再加一张"的路径，因此门禁必须严：
一旦放宽，就会在趋势尾部反复加仓，把单标的敞口堆到远超预算。原实现的长/空两份
判定**同构、方向相反、各自演化**，是"改了一边忘了另一边"的典型温床。

## 五条门禁，抽后只剩一份权威实现

| # | 门禁 | 判定 |
|---|---|---|
| 1 | 底仓已盈利或已无风险 | `(upl > 0 and uplRatio >= min_scale_in_profit_ratio)` 或止损已推过入场价 |
| 2 | 每仓最多加仓次数 | `scale_count < max_scale_in_count` |
| 3 | 合并保证金不超单标的封顶 | `(curr_margin + planned_margin) <= asset_margin_cap` |
| 4 | AI 置信度门禁 | `ai_conf >= min_scale_in_confidence` |
| 5 | 数理动能/概率门禁 | 见下 |

## 调用方保留的"方向无关前段"

下列取值在长/空两侧**逐字相同**（只有 tracker 后缀差方向），故留在调用方，
避免为纯搬运多传参数：`pos_upl` / `pos_upl_ratio` / `pos_avg_px` / `curr_margin` /
`scale_count` / `trailing_sl` / `c_dyn` / `c_accel` / `p_th`。

## ⚠️ 两处方向必须各测一侧（翻转方式不同）

- **第 1 条**：比较方向**反转** —— 做多 `trailing_sl >= pos_avg_px`，
  做空 `trailing_sl <= pos_avg_px`。
- **第 5 条**：**换用完全不同的概率指标** —— 做多看 `continuation_prob_pct`
  且加速度下限 `-0.25`；做空看 `breakdown_prob_pct` 且加速度上限 `+0.25`。

任一处写反 = 在趋势衰竭处放行加仓。差分测试因此对长/空两侧分别逐点覆盖。

## 打印语句是行为的一部分

`[Pyramiding] …` / `[Pyramiding 拦截] …` 会进 `executed_actions` 与巡检日志，
是事后审计加仓决策的唯一凭据。这些 print **原样搬入**，差分测试把 stdout 一并对拍。

## 返回值

`(allow_entry, is_scale_in)`；调用方的 `allow_entry = False` / `is_scale_in = False`
初值保持不变，本函数只回答"是否放行、是否是加仓"。
"""


def pyramiding_gate(*, is_long, f, pos_upl, pos_upl_ratio, pos_avg_px, curr_margin,
                    trailing_sl, scale_count, c_accel, p_th, ai_margin, actual_sz,
                    ct_val, ai_lever, ai_conf, min_scale_in_profit_ratio,
                    max_scale_in_count, min_scale_in_confidence, asset_margin_cap):
    """五条加仓门禁；返回 `(allow_entry, is_scale_in)`。

    依赖全部入参 —— 门面会被 `pin_baseline_risk_env()` 原地重载，
    子模块 import 期绑定风控常量会变成过期快照（`astra_backend/README.md` §5）。
    """
    # 调用方原本在分支入口置 `allow_entry = False` / `is_scale_in = False`；
    # 那段初始化随内联代码一起搬走，这里补回 —— 否则两条 else-if 链都没命中时
    # 会 `UnboundLocalError`（长/空两处 facade 仍各自保留同名初值，行为不变）。
    allow_entry = False
    is_scale_in = False
    if is_long:
        is_profit_or_breakeven = (pos_upl > 0 and pos_upl_ratio >= min_scale_in_profit_ratio) or (trailing_sl > 0 and trailing_sl >= pos_avg_px)
        planned_margin = ai_margin if ai_margin > 0 else (actual_sz * ct_val * f["price"] / max(1.0, ai_lever))
        within_margin_cap = (curr_margin + planned_margin) <= asset_margin_cap

        p_cont = float(p_th.get("continuation_prob_pct", 50.0) or 50.0)
        calculus_accel_ok = (c_accel >= -0.25 and p_cont >= 40.0)

        if is_profit_or_breakeven and scale_count < max_scale_in_count and within_margin_cap and ai_conf >= min_scale_in_confidence and calculus_accel_ok:
            allow_entry = True
            is_scale_in = True
            print(f"[Pyramiding] {f['name']} 满足顺势浮盈加多条件: 底仓浮盈={pos_upl:+.2f}U ({pos_upl_ratio*100:+.1f}%), 已加仓{scale_count}次, 微积分加速度={c_accel:+.2f}, 延续概率={p_cont:.1f}%, 计划加仓{actual_sz}张")
        else:
            if not is_profit_or_breakeven:
                print(f"[Pyramiding 拦截] {f['name']} 底仓未达浮盈保本门禁 (浮盈={pos_upl:+.2f}U ROI={pos_upl_ratio*100:+.1f}%), 严禁逆势加仓")
            elif scale_count >= max_scale_in_count:
                print(f"[Pyramiding 拦截] {f['name']} 已达最大加仓次数 ({scale_count}/{max_scale_in_count})")
            elif not within_margin_cap:
                print(f"[Pyramiding 拦截] {f['name']} 加仓后总保证金将超限 ({curr_margin + planned_margin:.1f} > {asset_margin_cap}U)")
            elif ai_conf < min_scale_in_confidence:
                print(f"[Pyramiding 拦截] {f['name']} AI加仓置信度不足 ({ai_conf:.0f}% < {min_scale_in_confidence}%)")
            elif not calculus_accel_ok:
                print(f"[Pyramiding 拦截] {f['name']} 数理动能衰竭或延续概率偏低 (加速度={c_accel:+.2f}, 概率={p_cont:.1f}%)，禁止追多加仓")

    else:
        is_profit_or_breakeven = (pos_upl > 0 and pos_upl_ratio >= min_scale_in_profit_ratio) or (trailing_sl > 0 and trailing_sl <= pos_avg_px)
        planned_margin = ai_margin if ai_margin > 0 else (actual_sz * ct_val * f["price"] / max(1.0, ai_lever))
        within_margin_cap = (curr_margin + planned_margin) <= asset_margin_cap

        # c_dyn 由调用方给出
        # c_accel 由调用方给出
        # p_th 由调用方给出
        p_break = float(p_th.get("breakdown_prob_pct", 50.0) or 50.0)
        calculus_accel_ok = (c_accel <= 0.25 and p_break >= 40.0)

        if is_profit_or_breakeven and scale_count < max_scale_in_count and within_margin_cap and ai_conf >= min_scale_in_confidence and calculus_accel_ok:
            allow_entry = True
            is_scale_in = True
            print(f"[Pyramiding] {f['name']} 满足顺势浮盈加空条件: 底仓浮盈={pos_upl:+.2f}U ({pos_upl_ratio*100:+.1f}%), 已加仓{scale_count}次, 微积分加速度={c_accel:+.2f}, 击穿概率={p_break:.1f}%, 计划加仓{actual_sz}张")
        else:
            if not is_profit_or_breakeven:
                print(f"[Pyramiding 拦截] {f['name']} 底仓未达浮盈保本门禁 (浮盈={pos_upl:+.2f}U ROI={pos_upl_ratio*100:+.1f}%), 严禁逆势加仓")
            elif scale_count >= max_scale_in_count:
                print(f"[Pyramiding 拦截] {f['name']} 已达最大加仓次数 ({scale_count}/{max_scale_in_count})")
            elif not within_margin_cap:
                print(f"[Pyramiding 拦截] {f['name']} 加仓后总保证金将超限 ({curr_margin + planned_margin:.1f} > {asset_margin_cap}U)")
            elif ai_conf < min_scale_in_confidence:
                print(f"[Pyramiding 拦截] {f['name']} AI加仓置信度不足 ({ai_conf:.0f}% < {min_scale_in_confidence}%)")
            elif not calculus_accel_ok:
                print(f"[Pyramiding 拦截] {f['name']} 数理动能失速企稳或击穿概率偏低 (加速度={c_accel:+.2f}, 概率={p_break:.1f}%)，禁止追空加仓")
    return allow_entry, is_scale_in

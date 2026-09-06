// SPDX-License-Identifier: AGPL-3.0-or-later
import type { FiscalLossCandidate } from '../api/queries';
import type { Broker } from '../types';
import { computeCommission } from './commission';

export interface LossHarvestingLine {
  ticker: string;
  product_name: string;
  account_id: number;
  qty: number;
  estimated_loss: number;
}

export interface LossHarvestingPlan {
  lines: LossHarvestingLine[];
  covered: number;
  shortfall: number;
}

/** Real disposal commission for selling `amount` € on the given account's broker.
 * 0 when the broker has no schedule on record (better to under-estimate the fee
 * than crash or silently invent one). */
function saleFee(amountEur: number, broker: Broker | undefined): number {
  if (!broker?.commission_schedule) return 0;
  return computeCommission(Math.abs(amountEur), broker.commission_schedule);
}

/**
 * Greedy sell-then-immediately-rebuy plan to neutralize `target` € of taxable
 * gain using the fewest possible lines. `candidates` must already be sorted
 * worst-first (most negative unrealized_pv first) — the API guarantees this,
 * and using the biggest available loss per line first is what minimizes the
 * number of lines touched when the last line can be partially sold.
 *
 * Each full line's estimated loss is net of that account's real disposal
 * commission (via `commission.ts`, the same logic used for manual transaction
 * entry) — not just the raw unrealized P&L, which by this app's own Degiro/IBKR
 * convention excludes fees entirely. The cutoff/partial line solves for the
 * exact quantity whose *post-fee* loss matches the remaining target: since the
 * fee itself can depend on the trade amount (e.g. IBKR's tiered schedule), this
 * is an iterative refinement rather than a single division — it converges in
 * 1 pass for a flat fee (Degiro) and typically 2-3 for a tiered one.
 */
export function computeLossHarvestingPlan(
  candidates: FiscalLossCandidate[],
  target: number,
  fractionable: boolean,
  brokersById: Map<number, Broker>,
): LossHarvestingPlan {
  if (target <= 0) return { lines: [], covered: 0, shortfall: 0 };

  const lines: LossHarvestingLine[] = [];
  let remaining = target;

  for (const candidate of candidates) {
    if (remaining <= 0) break;

    const broker = brokersById.get(candidate.account_id);
    const availableLossGross = Math.abs(candidate.unrealized_pv);
    const fullSaleFee = saleFee(candidate.current_value_eur, broker);
    const availableLossNet = availableLossGross + fullSaleFee;
    const perUnitLossGross = availableLossGross / candidate.qty_held;

    if (availableLossNet <= remaining) {
      // Whole position needed (or exactly enough) — its own real fee included.
      lines.push({
        ticker: candidate.ticker,
        product_name: candidate.product_name,
        account_id: candidate.account_id,
        qty: candidate.qty_held,
        estimated_loss: availableLossNet,
      });
      remaining -= availableLossNet;
      continue;
    }

    // Cutoff line: solve qty so that (qty * perUnitLossGross) + fee(qty * price) == remaining.
    // Iterate: guess qty ignoring the fee, price it, fold the fee back into the
    // target, re-derive qty — repeat until qty stabilizes.
    const pricePerUnit = candidate.current_value_eur / candidate.qty_held;
    let exactQty = remaining / perUnitLossGross;
    for (let i = 0; i < 5; i++) {
      const qtyForFee = Math.min(exactQty, candidate.qty_held);
      const fee = saleFee(qtyForFee * pricePerUnit, broker);
      const nextQty = (remaining - fee) / perUnitLossGross;
      if (Math.abs(nextQty - exactQty) < 1e-9) { exactQty = nextQty; break; }
      exactQty = nextQty;
    }
    exactQty = Math.max(0, exactQty);
    const qty = fractionable ? exactQty : Math.ceil(exactQty);

    if (qty >= candidate.qty_held) {
      // Rounding (or a fee bigger than the residual gross loss) pushed the
      // cutoff to the whole position — take it all, real fee included, and
      // keep going in case a true residual still needs another line.
      lines.push({
        ticker: candidate.ticker,
        product_name: candidate.product_name,
        account_id: candidate.account_id,
        qty: candidate.qty_held,
        estimated_loss: availableLossNet,
      });
      remaining -= availableLossNet;
    } else {
      const fee = saleFee(qty * pricePerUnit, broker);
      const actualLossNet = qty * perUnitLossGross + fee;
      lines.push({
        ticker: candidate.ticker,
        product_name: candidate.product_name,
        account_id: candidate.account_id,
        qty,
        estimated_loss: actualLossNet,
      });
      remaining -= actualLossNet;
      break; // this was the cutoff line
    }
  }

  const shortfall = Math.max(0, remaining);
  const covered = target - shortfall;
  return { lines, covered, shortfall };
}

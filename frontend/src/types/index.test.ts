/**
 * Minimal test to ensure the types module is importable.
 * TypeScript interfaces compile to empty JS, so there's nothing to test at runtime.
 */
import { describe, it, expect } from 'vitest';
import type {
  User, Product, Broker, AccountPosition, AccountSummary,
  Transaction, Pool, DailySnapshot, PoolValue, DailyWithPools,
  MonthlySnapshot, PoolDashboard, Dashboard, Holding,
  AssetPrice, CreatePricePayload, HoldingValueEntry, DailyHoldingValues,
  RebalancingPoolResult, RebalancingResult,
} from './index';

describe('types/index', () => {
  it('is importable', () => {
    expect(true).toBe(true);
  });

  it('types are structurally valid when used', () => {
    const user: User = { id: 1, name: 'Test', created_at: null };
    expect(user.id).toBe(1);

    const product: Product = { ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false };
    expect(product.ticker).toBe('AAPL');

    const account: Broker = { id: 1, portfolio_ids: [1], name: 'PEA', currency: 'EUR', commission_schedule: null, allowed_tickers: null, withdrawal_fee_eur: 0, withdrawal_first_free: false, commission_profile: null, commission_sale_rate: 0, include_fees_in_cump: true, monthly_free_eur: null, above_monthly_rate: 0, weekend_rate: null };
    expect(account.id).toBe(1);

    const accountPosition: AccountPosition = {
      ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10,
      last_price: 150, last_price_date: '2024-01-01',
      last_price_source: 'yahoo', value_eur: 1500, currency: 'USD',
    };
    expect(accountPosition.ticker).toBe('AAPL');

    const accountSummary: AccountSummary = {
      id: 1, name: 'PEA', currency: 'EUR', cash_balance_eur: 100,
      positions: [], positions_value_eur: 0, total_eur: 100,
    };
    expect(accountSummary.total_eur).toBe(100);

    const tx: Transaction = {
      id: 1, portfolio_id: 1, account_id: 1, date: '2024-01-01',
      type: 'Actif', ticker: 'AAPL', currency: 'EUR', exchange_rate: 1,
      quantity: -10, unit_price: 150, unit_price_eur: 150,
      total_amount: -1500, total_amount_eur: -1500,
      balance_currency: null, balance_eur: null, linked_transaction_id: null, fractional_parent_id: null,
    };
    expect(tx.id).toBe(1);

    const pool: Pool = {
      id: 1, portfolio_id: 1, name: 'Asie', strategy: 'Offensive',
      target_pct: 0.25, is_active: true,
    };
    expect(pool.name).toBe('Asie');

    const snap: DailySnapshot = {
      id: 1, portfolio_id: 1, date: '2024-01-01',
      total_eur: 10000, offensive_eur: 5000, defensive_eur: 5000,
    };
    expect(snap.total_eur).toBe(10000);

    const poolValue: PoolValue = {
      pool_id: 1, pool_name: 'Asie', strategy: 'Offensive', value_eur: 5000,
    };
    expect(poolValue.pool_name).toBe('Asie');

    const dailyWithPools: DailyWithPools = {
      date: '2024-01-01', total_eur: 10000,
      offensive_eur: 5000, defensive_eur: 5000, pools: [],
    };
    expect(dailyWithPools.date).toBe('2024-01-01');

    const monthly: MonthlySnapshot = {
      id: 1, portfolio_id: 1, date: '2024-01-01',
      total_eur: 10000, offensive_eur: 5000, defensive_eur: 5000,
      contributions_eur: 0, performance_pct: 0, performance_index: 100,
    };
    expect(monthly.performance_index).toBe(100);

    const poolDashboard: PoolDashboard = {
      id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25,
      current_value_eur: 5000, current_pct: 25, gap_pct: 0,
    };
    expect(poolDashboard.gap_pct).toBe(0);

    const dashboard: Dashboard = {
      total_eur: 10000, offensive_eur: 5000, defensive_eur: 5000,
      pools: [], liquidity_eur: 0, last_updated: null,
    };
    expect(dashboard.total_eur).toBe(10000);

    const holding: Holding = {
      ticker: 'AAPL', product_name: 'Apple', category: 'Actif', pool_id: null, pool_name: null,
      quantity: 10, last_price: 150, last_price_date: null,
      last_price_source: 'yahoo', value_eur: 1500, currency: 'USD',
    };
    expect(holding.ticker).toBe('AAPL');

    const assetPrice: AssetPrice = {
      id: 1, ticker: 'AAPL', date: '2024-01-01',
      price: 150, currency: 'USD', source: 'yahoo',
    };
    expect(assetPrice.price).toBe(150);

    const createPricePayload: CreatePricePayload = {
      ticker: 'AAPL', date: '2024-01-01', price: 150, currency: 'USD', source: 'manual',
    };
    expect(createPricePayload.source).toBe('manual');

    const holdingEntry: HoldingValueEntry = {
      unit_price: 150, ticker: 'AAPL', product_name: 'Apple', value_eur: 1500,
    };
    expect(holdingEntry.unit_price).toBe(150);

    const dailyHoldingVal: DailyHoldingValues = {
      date: '2024-01-01', positions: [],
    };
    expect(dailyHoldingVal.date).toBe('2024-01-01');

    const rebalPool: RebalancingPoolResult = {
      id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25,
      current_value: 25000, current_pct: 25, target_value_after: 27500,
      injection_amount: 2500, rebalance_amount: 0, hybrid_amount: 2500,
      injection_fee: 12.5, rebalance_fee: 0, hybrid_fee: 12.5,
      injection_net: 2487.5, rebalance_net: 0, hybrid_net: 2487.5,
    };
    expect(rebalPool.injection_fee).toBe(12.5);
    expect(rebalPool.hybrid_net).toBe(2487.5);

    const rebalResult: RebalancingResult = {
      total_current: 100000, total_apport: 10000, total_after: 110000,
      liquidity_available: 1000, external_injection: 9000,
      pools: [rebalPool],
    };
    expect(rebalResult.pools.length).toBe(1);
  });
});

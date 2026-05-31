export interface User {
  id: number;
  name: string;
  created_at?: string | null;
}

export interface ExecutionItemType {
  date: string;
  quantity: number;
  unit_price: number;
  exchange_rate: number;
}

export interface CommissionTier {
  up_to: number | null;
  type: "flat" | "percent";
  value: number;
}

export interface Product {
  ticker: string;
  name: string;
  category: string;
  currency: string;
  isin?: string | null;
  notes?: string | null;
  is_ttf_eligible: boolean;
}

export interface Broker {
  id: number;
  portfolio_ids: number[];
  name: string;
  currency: string;
  commission_schedule: CommissionTier[] | null;
  allowed_tickers: string[] | null;
  withdrawal_fee_eur: number;
  withdrawal_first_free: boolean;
  commission_profile: string | null;
  commission_sale_rate: number;
  include_fees_in_cump: boolean;
  monthly_free_eur: number | null;
  above_monthly_rate: number;
  weekend_rate: number | null;
  color?: string | null;
}

export interface AccountPosition {
  ticker: string;
  product_name: string;
  category: string | null;
  quantity: number;
  last_price: number;
  last_price_date: string | null;
  last_price_source: string;
  value_eur: number;
  currency: string;
}

export interface AccountSummary {
  id: number;
  name: string;
  currency: string;
  cash_balance_eur: number;
  positions: AccountPosition[];
  positions_value_eur: number;
  total_eur: number;
}

export interface Transaction {
  id: number;
  portfolio_id: number;
  account_id: number;
  date: string;
  type: string;
  ticker: string;
  currency: string;
  exchange_rate: number;
  quantity: number;
  unit_price: number;
  unit_price_eur: number;
  total_amount: number;
  total_amount_eur: number;
  balance_currency: number | null;
  balance_eur: number | null;
  linked_transaction_id: number | null;
  fractional_parent_id: number | null;
}

export interface Pool {
  id: number;
  portfolio_id: number;
  name: string;
  strategy: string;
  target_pct: number;
  is_active: boolean;
  color?: string | null;
}

export interface DailySnapshot {
  id: number;
  portfolio_id: number;
  date: string;
  total_eur: number;
  offensive_eur: number;
  defensive_eur: number;
}

export interface PoolValue {
  pool_id: number;
  pool_name: string;
  strategy: string;
  value_eur: number;
}

export interface DailyWithPools {
  date: string;
  total_eur: number;
  offensive_eur: number;
  defensive_eur: number;
  pools: PoolValue[];
}

export interface MonthlySnapshot {
  id: number;
  portfolio_id: number;
  date: string;
  total_eur: number;
  offensive_eur: number;
  defensive_eur: number;
  contributions_eur: number;
  performance_pct: number;
  performance_index: number;
}

export interface PoolDashboard {
  id: number;
  name: string;
  strategy: string;
  target_pct: number;
  current_value_eur: number;
  current_pct: number;
  gap_pct: number;
  color?: string | null;
}

export interface Dashboard {
  total_eur: number;
  offensive_eur: number;
  defensive_eur: number;
  pools: PoolDashboard[];
  liquidity_eur: number;
  last_updated: string | null;
}

export interface Holding {
  ticker: string;
  product_name: string;
  category: string | null;
  pool_id: number | null;
  pool_name: string | null;
  quantity: number;
  last_price: number;
  last_price_date: string | null;
  last_price_source: string;
  value_eur: number;
  currency: string;
}

export interface AssetPrice {
  id: number;
  ticker: string;
  date: string;
  price: number;
  currency: string;
  source: string;
}

export interface CreatePricePayload {
  ticker: string;
  date: string;
  price: number;
  currency: string;
  source: string;
}

export interface HoldingValueEntry {
  unit_price: number;
  ticker: string;
  product_name: string;
  value_eur: number;
}

export interface DailyHoldingValues {
  date: string;
  positions: HoldingValueEntry[];
}

export interface RebalancingPoolResult {
  id: number;
  name: string;
  strategy: string;
  target_pct: number;
  current_value: number;
  current_pct: number;
  target_value_after: number;
  injection_amount: number;
  rebalance_amount: number;
  hybrid_amount: number;
  injection_fee: number;
  rebalance_fee: number;
  hybrid_fee: number;
  injection_net: number;
  rebalance_net: number;
  hybrid_net: number;
}

export interface RebalancingResult {
  total_current: number;
  total_apport: number;
  total_after: number;
  liquidity_available: number;
  external_injection: number;
  pools: RebalancingPoolResult[];
}

// ── Capital Gains (Plus-Values) ────────────────────────────────────────────

export interface CapitalGainsEvent {
  date: string;
  ticker: string;
  product_name: string;
  qty_sold: number;
  cump_at_sell: number;
  sell_price_eur: number;
  realized_pv: number;
  account_id: number;
}

export interface TickerCapitalGains {
  ticker: string;
  product_name: string;
  cump: number;
  qty_held: number;
  cost_basis_eur: number;
  current_value_eur: number;
  unrealized_pv: number;
  realized_pv_total: number;
  events: CapitalGainsEvent[];
}

export interface PortfolioCapitalGains {
  portfolio_id: number;
  tickers: TickerCapitalGains[];
  total_unrealized_pv: number;
  total_realized_pv: number;
  total_pv: number;
}

// ── Fiscal Carry-Forward (Moins-Values Reportables) ────────────────────────

export interface FiscalCarryForward {
  id: number;
  portfolio_id: number;
  tax_year: number;
  amount_eur: number;
}

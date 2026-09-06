// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './client';
import type {
  Broker, AccountSummary, AssetPrice, CountryPerfConfig, CountryPerformanceEntry, Dashboard,
  DailySnapshot, DailyWithPools, DailyHoldingValues, EquityPremiumConfig, EquityPremiumEntry,
  EtfComposition, FiscalCarryForward,
  MacroRegionConfig, MonthlySnapshot, Pool, PoolAllocation, PortfolioCapitalGains, Holding,
  Product, RatioIndicator, SectorPerfConfig, SectorPerformanceEntry, Transaction, User,
} from '../types';

/**
 * Shared list/create/update/delete hooks for every "code-keyed universe" CRUD table
 * (macro regions, country/sector-performance/equity-premium universes) — these were
 * hand-copied from each other before being collapsed here, mirroring
 * app/services/code_keyed_crud.py's factory on the backend. Each call site still exports
 * the exact same function names as before, so no caller needed to change.
 */
function makeCrudHooks<T extends { code: string }>(basePath: string, listQueryKey: string) {
  return {
    useList: () => useQuery<T[]>({
      queryKey: [listQueryKey],
      queryFn: async () => (await apiClient.get<T[]>(basePath)).data,
    }),
    create: async (body: T): Promise<T> => (await apiClient.post<T>(basePath, body)).data,
    update: async (code: string, body: Omit<T, 'code'>): Promise<T> =>
      (await apiClient.put<T>(`${basePath}/${code}`, body)).data,
    delete: async (code: string): Promise<void> => {
      await apiClient.delete(`${basePath}/${code}`);
    },
  };
}

// ── Portfolios ─────────────────────────────────────────────────────────────

export function usePortfolios() {
  return useQuery<User[]>({
    queryKey: ['portfolios'],
    queryFn: async () => (await apiClient.get<User[]>('/api/portfolios/')).data,
    retry: 30,
    retryDelay: 2000,
  });
}

export function usePortfolio(portfolioId: number | string) {
  return useQuery<User>({
    queryKey: ['portfolios', portfolioId],
    queryFn: async () => (await apiClient.get<User>(`/api/portfolios/${portfolioId}`)).data,
    enabled: !!portfolioId,
  });
}

export function useCreatePortfolio() {
  const qc = useQueryClient();
  return useMutation<User, Error, { name: string }>({
    mutationFn: async (body) => (await apiClient.post<User>('/api/portfolios/', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolios'] }),
  });
}

export function useRenamePortfolio() {
  const qc = useQueryClient();
  return useMutation<User, Error, { id: number; name: string }>({
    mutationFn: async ({ id, name }) => (await apiClient.put<User>(`/api/portfolios/${id}`, { name })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolios'] }),
  });
}

export function useDeletePortfolio() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => { await apiClient.delete(`/api/portfolios/${id}`); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolios'] }),
  });
}

// ── Brokers ────────────────────────────────────────────────────────────────

export function useBrokers(userId: number | string | undefined) {
  return useQuery<Broker[]>({
    queryKey: ['brokers', userId],
    queryFn: async () =>
      (await apiClient.get<Broker[]>('/api/brokers/', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

export function useAllBrokers() {
  return useQuery<Broker[]>({
    queryKey: ['brokers', 'all'],
    queryFn: async () =>
      (await apiClient.get<Broker[]>('/api/brokers/')).data,
  });
}

export async function createBrokerAPI(body: { name: string; currency: string; color?: string | null; portfolio_ids?: number[] }): Promise<Broker> {
  return (await apiClient.post<Broker>('/api/brokers/', body)).data;
}

export async function updateBrokerPortfoliosAPI(brokerId: number, portfolioIds: number[]): Promise<Broker> {
  return (await apiClient.put<Broker>(`/api/brokers/${brokerId}/portfolios`, { portfolio_ids: portfolioIds })).data;
}

export async function updateBrokerAPI(brokerId: number, body: { name?: string; currency?: string; color?: string | null }): Promise<Broker> {
  return (await apiClient.put<Broker>(`/api/brokers/${brokerId}`, body)).data;
}

export async function deleteBrokerAPI(brokerId: number): Promise<void> {
  await apiClient.delete(`/api/brokers/${brokerId}`);
}

export function useAccountsSummary(userId: number | string | undefined) {
  return useQuery<AccountSummary[]>({
    queryKey: ['accounts-summary', userId],
    queryFn: async () =>
      (await apiClient.get<AccountSummary[]>('/api/brokers/summary', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

// ── Products ───────────────────────────────────────────────────────────────

export function useProducts() {
  return useQuery<Product[]>({
    queryKey: ['products'],
    queryFn: async () => (await apiClient.get<Product[]>('/api/products/')).data,
  });
}

export interface ProductPayload {
  ticker: string;
  name: string;
  category: string;
  instrument_type?: string | null;
  fee_type?: string | null;
  currency: string;
  is_ttf_eligible?: boolean;
}

export async function createProduct(body: ProductPayload): Promise<Product> {
  return (await apiClient.post<Product>('/api/products/', body)).data;
}

export async function updateProduct(ticker: string, body: Partial<Omit<ProductPayload, 'ticker'>>): Promise<Product> {
  return (await apiClient.put<Product>(`/api/products/${ticker}`, body)).data;
}

export async function deleteProduct(ticker: string): Promise<void> {
  await apiClient.delete(`/api/products/${ticker}`);
}

// ── Transactions ───────────────────────────────────────────────────────────

export interface TransactionFilters {
  date_from?: string;
  date_to?: string;
  ticker?: string;
  currency?: string;
  account_id?: number;
  skip?: number;
  limit?: number;
}

export function useTransactions(
  userId: number | string | undefined,
  filters?: TransactionFilters,
  options?: { enabled?: boolean },
) {
  return useQuery<Transaction[]>({
    queryKey: ['transactions', userId, filters],
    queryFn: async () =>
      (await apiClient.get<Transaction[]>('/api/transactions/', {
        params: { portfolio_id: userId, ...filters },
      })).data,
    enabled: !!userId && (options?.enabled ?? true),
  });
}

export interface ExecutionItem {
  date: string;
  quantity: number;
  unit_price: number;
  exchange_rate?: number;
}

export interface TransactionPayload {
  portfolio_id: number;
  account_id: number;
  date: string;
  type: string;
  ticker: string;
  currency: string;
  exchange_rate: number;
  quantity: number;
  unit_price: number;
  balance_currency?: number;
  balance_eur?: number;
  operation?: string;
  courtage_eur?: number;
  ttf_eur?: number;
  additional_executions?: ExecutionItem[];
}

// Helper: invalidate all portfolio-scoped caches after any transaction change.
// Transactions affect balances, holdings, snapshots, dashboard KPIs and TRI.
// IMPORTANT: query keys store portfolioId as a STRING (from useParams), but
// the API returns portfolio_id as a number — use String() to match exactly.
// Exported so useCommitImport (bulk import) can reuse it after a successful commit.
export function invalidatePortfolioQueries(qc: ReturnType<typeof useQueryClient>, portfolioId: number | string) {
  const pid = String(portfolioId);
  qc.invalidateQueries({ queryKey: ['transactions', pid] });
  qc.invalidateQueries({ queryKey: ['accounts-summary', pid] });
  qc.invalidateQueries({ queryKey: ['holdings', pid] });
  qc.invalidateQueries({ queryKey: ['holdings-history', pid] });
  qc.invalidateQueries({ queryKey: ['dashboard', pid] });
  qc.invalidateQueries({ queryKey: ['dashboard', 'daily-holding-values', pid] });
  qc.invalidateQueries({ queryKey: ['tri', pid] });
  qc.invalidateQueries({ queryKey: ['snapshots'] });
}

export function useCreateTransaction() {
  const qc = useQueryClient();
  return useMutation<Transaction, Error, TransactionPayload>({
    mutationFn: async (body) => (await apiClient.post<Transaction>('/api/transactions/', body)).data,
    onSuccess: (data) => invalidatePortfolioQueries(qc, data.portfolio_id),
  });
}

export function useUpdateTransaction() {
  const qc = useQueryClient();
  return useMutation<Transaction, Error, { id: number } & Partial<TransactionPayload>>({
    mutationFn: async ({ id, ...body }) =>
      (await apiClient.put<Transaction>(`/api/transactions/${id}`, body)).data,
    onSuccess: (data) => invalidatePortfolioQueries(qc, data.portfolio_id),
  });
}

export function useDeleteTransaction() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: number; portfolio_id: number }>({
    mutationFn: async ({ id }) => { await apiClient.delete(`/api/transactions/${id}`); },
    onSuccess: (_, vars) => invalidatePortfolioQueries(qc, vars.portfolio_id),
  });
}

// ── Bulk transaction import (Excel) ─────────────────────────────────────────

export interface ImportRowResolved {
  portfolio_id: number;
  account_id: number;
  portfolio_name: string;
  account_name: string;
  date: string;
  type: string;
  operation: string | null;
  ticker: string;
  currency: string;
  exchange_rate: number;
  quantity: number;
  unit_price: number;
  courtage_eur: number;
  ttf_eur: number;
}

export interface ImportDuplicateRef {
  kind: 'db' | 'file';
  transaction_id?: number | null;
  row_number?: number | null;
}

export interface ImportRowResult {
  row_number: number;
  status: 'ok' | 'error' | 'duplicate';
  sens: string | null;
  resolved: ImportRowResolved | null;
  errors: string[];
  warnings: string[];
  duplicate_of: ImportDuplicateRef | null;
}

export interface ImportSummary {
  total_rows: number;
  ok: number;
  errors: number;
  duplicates: number;
}

export interface ImportValidateResponse {
  rows: ImportRowResult[];
  summary: ImportSummary;
}

export interface ImportCommitResponse {
  status: string;
  imported_count: number;
  created_transaction_ids: number[];
}

export function useValidateImport() {
  return useMutation<ImportValidateResponse, Error, File>({
    mutationFn: async (file) => {
      const form = new FormData();
      form.append('file', file);
      return (await apiClient.post<ImportValidateResponse>(
        '/api/transactions/import/validate', form, { headers: { 'Content-Type': 'multipart/form-data' } },
      )).data;
    },
  });
}

export function useCommitImport() {
  const qc = useQueryClient();
  return useMutation<
    ImportCommitResponse, Error,
    { file: File; includeRows: number[]; portfolioId: number | string }
  >({
    mutationFn: async ({ file, includeRows }) => {
      const form = new FormData();
      form.append('file', file);
      form.append('include_rows', JSON.stringify(includeRows));
      return (await apiClient.post<ImportCommitResponse>(
        '/api/transactions/import/commit', form, { headers: { 'Content-Type': 'multipart/form-data' } },
      )).data;
    },
    onSuccess: (_, vars) => invalidatePortfolioQueries(qc, vars.portfolioId),
  });
}

// ── Pools ──────────────────────────────────────────────────────────────────

export function usePools(userId: number | string | undefined) {
  return useQuery<Pool[]>({
    queryKey: ['pools', userId],
    queryFn: async () =>
      (await apiClient.get<Pool[]>('/api/pools/', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

export function usePoolProducts(poolId: number | null) {
  return useQuery<{ pool_id: number; ticker: string }[]>({
    queryKey: ['pool-products', poolId],
    queryFn: async () =>
      (await apiClient.get(`/api/pools/${poolId}/products`)).data,
    enabled: poolId !== null,
  });
}

export function usePoolAllocation(portfolioId: number | string | undefined, poolId: number | null) {
  return useQuery<PoolAllocation>({
    queryKey: ['pool-allocation', portfolioId, poolId],
    queryFn: async () =>
      (await apiClient.get<PoolAllocation>(`/api/pools/${poolId}/allocation`, {
        params: { portfolio_id: portfolioId },
      })).data,
    enabled: !!portfolioId && poolId !== null,
  });
}

export async function createPool(body: Omit<Pool, 'id'>): Promise<Pool> {
  return (await apiClient.post<Pool>('/api/pools/', body)).data;
}

export async function updatePool(poolId: number, body: Partial<Omit<Pool, 'id' | 'portfolio_id'>>): Promise<Pool> {
  return (await apiClient.put<Pool>(`/api/pools/${poolId}`, body)).data;
}

export async function deletePool(poolId: number): Promise<void> {
  await apiClient.delete(`/api/pools/${poolId}`);
}

export async function addTickerToPool(poolId: number, ticker: string): Promise<void> {
  await apiClient.post(`/api/pools/${poolId}/products`, { ticker });
}

export async function removeTickerFromPool(poolId: number, ticker: string): Promise<void> {
  await apiClient.delete(`/api/pools/${poolId}/products/${ticker}`);
}

// ── Prices ─────────────────────────────────────────────────────────────────

export function usePrices(ticker: string | undefined) {
  return useQuery<AssetPrice[]>({
    queryKey: ['prices', ticker],
    queryFn: async () =>
      (await apiClient.get<AssetPrice[]>('/api/prices/', { params: { ticker } })).data,
    enabled: !!ticker,
  });
}

export interface PricePayload {
  ticker: string;
  date: string;
  price: number;
  currency: string;
  source?: string;
}

export function useCreatePrice() {
  const qc = useQueryClient();
  return useMutation<AssetPrice, Error, PricePayload>({
    mutationFn: async (body) =>
      (await apiClient.post<AssetPrice>('/api/prices/', { ...body, source: body.source ?? 'manual' })).data,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['prices', data.ticker] });
      qc.invalidateQueries({ queryKey: ['holdings'] });
      qc.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
}

// ── Holdings ───────────────────────────────────────────────────────────────

export function useHoldings(userId: number | string | undefined) {
  return useQuery<Holding[]>({
    queryKey: ['holdings', userId],
    queryFn: async () =>
      (await apiClient.get<Holding[]>('/api/dashboard/holdings', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

export function useHoldingsAtDate(userId: number | string | undefined, snapDate: string | null) {
  return useQuery<Holding[]>({
    queryKey: ['holdings-history', userId, snapDate],
    queryFn: async () =>
      (await apiClient.get<Holding[]>('/api/dashboard/holdings/history', {
        params: { portfolio_id: userId, snap_date: snapDate },
      })).data,
    enabled: !!userId && !!snapDate,
    staleTime: 10 * 60 * 1000,
  });
}

export function useEtfComposition(ticker: string | undefined) {
  return useQuery<EtfComposition>({
    queryKey: ['etf-composition', ticker],
    queryFn: async () =>
      (await apiClient.get<EtfComposition>(`/api/dashboard/holdings/${ticker}/composition`)).data,
    enabled: !!ticker,
    staleTime: 60 * 60 * 1000, // composition data refreshes weekly server-side
  });
}

// ── Macro indicators (global, portfolio-independent) ────────────────────────

export function useGrowthIndicator(region: string) {
  return useQuery<RatioIndicator>({
    queryKey: ['macro-growth', region],
    queryFn: async () =>
      (await apiClient.get<RatioIndicator>('/api/indicators/growth', { params: { region } })).data,
    staleTime: 60 * 60 * 1000, // refreshed once a day server-side
  });
}

export function useInflationIndicator(region: string) {
  return useQuery<RatioIndicator>({
    queryKey: ['macro-inflation', region],
    queryFn: async () =>
      (await apiClient.get<RatioIndicator>('/api/indicators/inflation', { params: { region } })).data,
    staleTime: 60 * 60 * 1000,
  });
}

const macroRegionCrud = makeCrudHooks<MacroRegionConfig>('/api/indicators/regions', 'macro-regions');
export const useMacroRegions = macroRegionCrud.useList;
export const createMacroRegion = macroRegionCrud.create;
export const updateMacroRegion = macroRegionCrud.update;
export const deleteMacroRegion = macroRegionCrud.delete;

// ── Country performance leaderboard (global, portfolio-independent) ────────

export function useCountryPerformance() {
  return useQuery<CountryPerformanceEntry[]>({
    queryKey: ['country-performance'],
    queryFn: async () =>
      (await apiClient.get<CountryPerformanceEntry[]>('/api/indicators/country-performance')).data,
    staleTime: 60 * 60 * 1000, // refreshed once a day server-side
  });
}

const countryPerfCrud = makeCrudHooks<CountryPerfConfig>(
  '/api/indicators/country-performance/countries', 'country-perf-configs',
);
export const useCountryPerfConfigs = countryPerfCrud.useList;
export const createCountryPerfConfig = countryPerfCrud.create;
export const updateCountryPerfConfig = countryPerfCrud.update;
export const deleteCountryPerfConfig = countryPerfCrud.delete;

// ── Sector performance (global, portfolio-independent) ──────────────────────

export function useSectorPerformance() {
  return useQuery<SectorPerformanceEntry[]>({
    queryKey: ['sector-performance'],
    queryFn: async () =>
      (await apiClient.get<SectorPerformanceEntry[]>('/api/indicators/sector-performance')).data,
    staleTime: 60 * 60 * 1000, // refreshed once a day server-side
  });
}

const sectorPerfCrud = makeCrudHooks<SectorPerfConfig>(
  '/api/indicators/sector-performance/sectors', 'sector-perf-configs',
);
export const useSectorPerfConfigs = sectorPerfCrud.useList;
export const createSectorPerfConfig = sectorPerfCrud.create;
export const updateSectorPerfConfig = sectorPerfCrud.update;
export const deleteSectorPerfConfig = sectorPerfCrud.delete;

// ── Equity risk premium (global, portfolio-independent) ─────────────────────

export function useEquityPremium() {
  return useQuery<EquityPremiumEntry[]>({
    queryKey: ['equity-premium'],
    queryFn: async () =>
      (await apiClient.get<EquityPremiumEntry[]>('/api/indicators/equity-premium')).data,
    staleTime: 60 * 60 * 1000, // refreshed once a day server-side
  });
}

const equityPremiumCrud = makeCrudHooks<EquityPremiumConfig>(
  '/api/indicators/equity-premium/countries', 'equity-premium-configs',
);
export const useEquityPremiumConfigs = equityPremiumCrud.useList;
export const createEquityPremiumConfig = equityPremiumCrud.create;
export const updateEquityPremiumConfig = equityPremiumCrud.update;
export const deleteEquityPremiumConfig = equityPremiumCrud.delete;

// ── Dashboard ──────────────────────────────────────────────────────────────

export interface TRIResult {
  tri_pct: number;
  tri_label: string;
  total_investi: number;
  total_retire: number;
  valeur_actuelle: number;
  nb_flux: number;
}

export function useTRI(userId: number | string | undefined) {
  return useQuery<TRIResult>({
    queryKey: ['tri', userId],
    queryFn: async () =>
      (await apiClient.get<TRIResult>('/api/dashboard/tri', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDashboard(userId: number | string | undefined) {
  return useQuery<Dashboard>({
    queryKey: ['dashboard', userId],
    queryFn: async () =>
      (await apiClient.get<Dashboard>('/api/dashboard/', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

// ── Snapshots ──────────────────────────────────────────────────────────────

export function useDailySnapshots(userId: number | string | undefined, dateFrom?: string, dateTo?: string) {
  return useQuery<DailySnapshot[]>({
    queryKey: ['snapshots', 'daily', userId, dateFrom, dateTo],
    queryFn: async () =>
      (await apiClient.get<DailySnapshot[]>('/api/snapshots/daily', {
        params: { portfolio_id: userId, date_from: dateFrom, date_to: dateTo },
      })).data,
    enabled: !!userId,
  });
}

export function useMonthlySnapshots(userId: number | string | undefined) {
  return useQuery<MonthlySnapshot[]>({
    queryKey: ['snapshots', 'monthly', userId],
    queryFn: async () =>
      (await apiClient.get<MonthlySnapshot[]>('/api/snapshots/monthly', { params: { portfolio_id: userId } })).data,
    enabled: !!userId,
  });
}

export function useDailyWithPools(userId: number | string | undefined, dateFrom?: string) {
  return useQuery<DailyWithPools[]>({
    queryKey: ['snapshots', 'daily-with-pools', userId, dateFrom],
    queryFn: async () =>
      (await apiClient.get<DailyWithPools[]>('/api/snapshots/daily-with-pools', {
        params: { portfolio_id: userId, date_from: dateFrom },
      })).data,
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDailyHoldingValues(userId: number | string | undefined) {
  return useQuery<DailyHoldingValues[]>({
    queryKey: ['dashboard', 'daily-holding-values', userId],
    queryFn: async () =>
      (await apiClient.get<DailyHoldingValues[]>('/api/dashboard/daily-holding-values', {
        params: { portfolio_id: userId },
      })).data,
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

export interface TWRRPoint { date: string; index: number; }
export interface TWRRData {
  total: TWRRPoint[];
  offensive: TWRRPoint[];
  defensive: TWRRPoint[];
  pools: Record<string, TWRRPoint[]>;
  positions: Record<string, TWRRPoint[]>;
}

export function useTWRR(userId: number | string | undefined) {
  return useQuery<TWRRData>({
    queryKey: ['snapshots', 'twrr', userId],
    queryFn: async () =>
      (await apiClient.get<TWRRData>('/api/snapshots/twrr', {
        params: { portfolio_id: userId },
      })).data,
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

export interface TWRRSummaryResult {
  twrr_total_pct: number;
  twrr_annualized_pct: number;
  period_days: number;
  start_date: string;
  end_date: string;
  start_index: number;
  end_index: number;
}

export function useTWRRSummary(userId: number | string | undefined) {
  return useQuery<TWRRSummaryResult>({
    queryKey: ['dashboard', 'twrr-summary', userId],
    queryFn: async () =>
      (await apiClient.get<TWRRSummaryResult>('/api/dashboard/twrr-summary', {
        params: { portfolio_id: userId },
      })).data,
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

// ── Capital Gains (Plus-Values) ────────────────────────────────────────────

export function useCapitalGains(portfolioId: number | string | undefined, accountId?: number) {
  return useQuery<PortfolioCapitalGains>({
    queryKey: ['capital-gains', portfolioId, accountId],
    queryFn: async () =>
      (await apiClient.get<PortfolioCapitalGains>('/api/pv/', {
        params: { portfolio_id: portfolioId, ...(accountId !== undefined ? { account_id: accountId } : {}) },
      })).data,
    enabled: !!portfolioId,
    staleTime: 5 * 60 * 1000,
  });
}

// ── Admin ──────────────────────────────────────────────────────────────────

export interface TaskStatus {
  task_id: string;
  state: 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE';
  current: number;
  total: number;
  date?: string;
  error?: string;
}

export async function triggerRecompute(startDate: string, endDate: string): Promise<string> {
  const res = await apiClient.post<{ task_id: string }>('/api/admin/recompute-snapshots', {
    start_date: startDate,
    end_date: endDate,
  });
  return res.data.task_id;
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const res = await apiClient.get<TaskStatus>(`/api/admin/task/${taskId}`);
  return res.data;
}


// ── Fiscal Carry-Forward ───────────────────────────────────────────────────

export function useFiscalCarryForwards(portfolioId: number | string | undefined) {
  return useQuery<FiscalCarryForward[]>({
    queryKey: ['fiscal-carry-forward', portfolioId],
    queryFn: async () =>
      (await apiClient.get<FiscalCarryForward[]>('/api/fiscal/carry-forward/', {
        params: { portfolio_id: portfolioId },
      })).data,
    enabled: !!portfolioId,
  });
}

export function useCreateCarryForward() {
  const qc = useQueryClient();
  return useMutation<
    FiscalCarryForward,
    Error,
    { portfolio_id: number; tax_year: number; amount_eur: number }
  >({
    mutationFn: async (body) =>
      (await apiClient.post<FiscalCarryForward>('/api/fiscal/carry-forward/', body)).data,
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: ['fiscal-carry-forward', String(vars.portfolio_id)] }),
  });
}

export function useUpdateCarryForward() {
  const qc = useQueryClient();
  return useMutation<
    FiscalCarryForward,
    Error,
    { id: number; portfolio_id: number; amount_eur: number }
  >({
    mutationFn: async ({ id, amount_eur }) =>
      (await apiClient.put<FiscalCarryForward>(`/api/fiscal/carry-forward/${id}`, { amount_eur })).data,
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: ['fiscal-carry-forward', String(vars.portfolio_id)] }),
  });
}

export function useDeleteCarryForward() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: number; portfolio_id: number }>({
    mutationFn: async ({ id }) => {
      await apiClient.delete(`/api/fiscal/carry-forward/${id}`);
    },
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: ['fiscal-carry-forward', String(vars.portfolio_id)] }),
  });
}

// ── Fiscal — current-year realized PV (CTO only, excl. JPYEUR=X) ──────────

export interface FiscalPvDetail {
  date: string;
  ticker: string;
  product_name: string;
  qty_sold: number;
  realized_pv: number;
  account_id: number;
}

export interface FiscalLossCandidate {
  account_id: number;
  ticker: string;
  product_name: string;
  qty_held: number;
  cump: number;
  current_value_eur: number;
  unrealized_pv: number;
}

export interface FiscalCurrentYearPv {
  year: number;
  net_realized_pv: number;
  details: FiscalPvDetail[];
  loss_harvesting_candidates: FiscalLossCandidate[];
}

export function useFiscalCurrentYearPv(portfolioId: number | string | undefined, year?: number) {
  return useQuery<FiscalCurrentYearPv>({
    queryKey: ['fiscal-current-year-pv', portfolioId, year],
    queryFn: async () =>
      (await apiClient.get<FiscalCurrentYearPv>('/api/fiscal/current-year-pv/', {
        params: { portfolio_id: portfolioId, ...(year ? { year } : {}) },
      })).data,
    enabled: !!portfolioId,
    staleTime: 5 * 60 * 1000,
  });
}

// ── GitHub update check ───────────────────────────────────────────────────

export interface GitHubUpdateStatus {
  status: 'never' | 'up_to_date' | 'update_available' | 'no_token' | 'error';
  current_version: string | null;
  latest_version: string | null;
  release_url: string | null;
  checked_at: string | null;
  error: string | null;
}

export function useGitHubUpdateStatus() {
  return useQuery<GitHubUpdateStatus>({
    queryKey: ['github-update-status'],
    queryFn: async () =>
      (await apiClient.get<GitHubUpdateStatus>('/api/admin/github-update-status')).data,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useSystemSetting(key: string) {
  return useQuery<{ key: string; value: string }>({
    queryKey: ['system-setting', key],
    queryFn: async () =>
      (await apiClient.get<{ key: string; value: string }>(`/api/admin/settings/${key}`)).data,
    retry: false,
  });
}

export function useSetSystemSetting() {
  const qc = useQueryClient();
  return useMutation<{ key: string; value: string }, Error, { key: string; value: string }>({
    mutationFn: async ({ key, value }) =>
      (await apiClient.put<{ key: string; value: string }>(`/api/admin/settings/${key}`, { value })).data,
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: ['system-setting', vars.key] }),
  });
}

export function useDeleteSystemSetting() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (key) => {
      await apiClient.delete(`/api/admin/settings/${key}`);
    },
    onSuccess: (_data, key) =>
      qc.invalidateQueries({ queryKey: ['system-setting', key] }),
  });
}

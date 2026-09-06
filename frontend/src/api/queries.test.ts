// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for api/queries.ts
 * Tests the async functions AND React Query hooks by mocking apiClient.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { makeWrapper } from '../../tests/utils/react-query-wrapper';
import apiClient from './client';
import {
  createPool, updatePool, deletePool,
  addTickerToPool, removeTickerFromPool,
  createProduct, updateProduct, deleteProduct,
  triggerRecompute, getTaskStatus,
  usePortfolios, usePortfolio, useCreatePortfolio, useRenamePortfolio, useDeletePortfolio,
  useCreateDemoPortfolio,
  useBrokers, useAccountsSummary, useProducts,
  useTransactions, useCreateTransaction, useUpdateTransaction, useDeleteTransaction,
  useValidateImport, useCommitImport,
  usePools, usePoolProducts,
  usePrices, useCreatePrice,
  useHoldings, useHoldingsAtDate,
  useTRI, useDashboard,
  useDailySnapshots, useMonthlySnapshots, useDailyWithPools, useDailyHoldingValues, useTWRR,
  useCapitalGains,
  useTWRRSummary,
  // New functions added for coverage (lines 61-81, 470-595)
  useAllBrokers,
  createBrokerAPI, updateBrokerPortfoliosAPI, updateBrokerAPI, deleteBrokerAPI,
  useFiscalCarryForwards, useCreateCarryForward, useUpdateCarryForward, useDeleteCarryForward,
  useFiscalCurrentYearPv,
  useGitHubUpdateStatus,
  useSystemSetting, useSetSystemSetting, useDeleteSystemSetting,
  useEtfComposition, usePoolAllocation,
  useGrowthIndicator, useInflationIndicator, useQuadrant,
  useMacroRegions, createMacroRegion, updateMacroRegion, deleteMacroRegion,
  useCountryPerformance, useCountryPerfConfigs,
  createCountryPerfConfig, updateCountryPerfConfig, deleteCountryPerfConfig,
  useSectorPerformance, useSectorPerfConfigs,
  createSectorPerfConfig, updateSectorPerfConfig, deleteSectorPerfConfig,
  useEquityPremium, useEquityPremiumConfigs,
  createEquityPremiumConfig, updateEquityPremiumConfig, deleteEquityPremiumConfig,
  useBondPerformance, useBondPerfConfigs,
  createBondPerfConfig, updateBondPerfConfig, deleteBondPerfConfig,
} from './queries';

vi.mock('./client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
const mockPut = vi.mocked(apiClient.put);
const mockDelete = vi.mocked(apiClient.delete);


describe('api/queries async functions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Pool functions ─────────────────────────────────────────────────────────

  describe('createPool', () => {
    it('POSTs to /api/pools/ and returns pool data', async () => {
      const pool = { id: 1, portfolio_id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, is_active: true };
      mockPost.mockResolvedValueOnce({ data: pool } as any);

      const result = await createPool({ portfolio_id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, is_active: true });

      expect(mockPost).toHaveBeenCalledWith('/api/pools/', expect.objectContaining({ name: 'Asie' }));
      expect(result).toEqual(pool);
    });
  });

  describe('updatePool', () => {
    it('PUTs to /api/pools/:id and returns pool data', async () => {
      const pool = { id: 2, portfolio_id: 1, name: 'Or', strategy: 'Defensive', target_pct: 0.25, is_active: true };
      mockPut.mockResolvedValueOnce({ data: pool } as any);

      const result = await updatePool(2, { name: 'Or' });

      expect(mockPut).toHaveBeenCalledWith('/api/pools/2', { name: 'Or' });
      expect(result).toEqual(pool);
    });
  });

  describe('deletePool', () => {
    it('DELETEs /api/pools/:id', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      await deletePool(3);

      expect(mockDelete).toHaveBeenCalledWith('/api/pools/3');
    });
  });

  describe('addTickerToPool', () => {
    it('POSTs ticker to /api/pools/:id/products', async () => {
      mockPost.mockResolvedValueOnce({} as any);

      await addTickerToPool(1, 'AAPL');

      expect(mockPost).toHaveBeenCalledWith('/api/pools/1/products', { ticker: 'AAPL' });
    });
  });

  describe('removeTickerFromPool', () => {
    it('DELETEs /api/pools/:id/products/:ticker', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      await removeTickerFromPool(1, 'AAPL');

      expect(mockDelete).toHaveBeenCalledWith('/api/pools/1/products/AAPL');
    });
  });

  // ── Product functions ──────────────────────────────────────────────────────

  describe('createProduct', () => {
    it('POSTs to /api/products/ and returns product data', async () => {
      const product = { ticker: 'AAPL', name: 'Apple Inc', category: 'Actif', currency: 'USD' };
      mockPost.mockResolvedValueOnce({ data: product } as any);

      const result = await createProduct({ ticker: 'AAPL', name: 'Apple Inc', category: 'Actif', currency: 'USD' });

      expect(mockPost).toHaveBeenCalledWith('/api/products/', { ticker: 'AAPL', name: 'Apple Inc', category: 'Actif', currency: 'USD' });
      expect(result).toEqual(product);
    });
  });

  describe('updateProduct', () => {
    it('PUTs to /api/products/:ticker and returns updated product', async () => {
      const product = { ticker: 'AAPL', name: 'Apple Updated', category: 'Actif', currency: 'USD' };
      mockPut.mockResolvedValueOnce({ data: product } as any);

      const result = await updateProduct('AAPL', { name: 'Apple Updated' });

      expect(mockPut).toHaveBeenCalledWith('/api/products/AAPL', { name: 'Apple Updated' });
      expect(result).toEqual(product);
    });
  });

  describe('deleteProduct', () => {
    it('DELETEs /api/products/:ticker', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      await deleteProduct('AAPL');

      expect(mockDelete).toHaveBeenCalledWith('/api/products/AAPL');
    });
  });

  // ── Admin functions ────────────────────────────────────────────────────────

  describe('triggerRecompute', () => {
    it('POSTs to /api/admin/recompute-snapshots and returns task_id', async () => {
      mockPost.mockResolvedValueOnce({ data: { task_id: 'abc-123' } } as any);

      const result = await triggerRecompute('2024-01-01', '2024-12-31');

      expect(mockPost).toHaveBeenCalledWith('/api/admin/recompute-snapshots', {
        start_date: '2024-01-01',
        end_date: '2024-12-31',
      });
      expect(result).toBe('abc-123');
    });
  });

  describe('getTaskStatus', () => {
    it('GETs /api/admin/task/:id and returns status', async () => {
      const status = { task_id: 'abc-123', state: 'SUCCESS', current: 10, total: 10 };
      mockGet.mockResolvedValueOnce({ data: status } as any);

      const result = await getTaskStatus('abc-123');

      expect(mockGet).toHaveBeenCalledWith('/api/admin/task/abc-123');
      expect(result).toEqual(status);
    });
  });
});

// ── React Query hooks ─────────────────────────────────────────────────────────

describe('api/queries React Query hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Portfolios ──────────────────────────────────────────────────────────────

  describe('usePortfolios', () => {
    it('fetches GET /api/portfolios/ and returns data', async () => {
      const portfolios = [{ id: 1, name: 'Portfolio 1', created_at: null }];
      mockGet.mockResolvedValueOnce({ data: portfolios } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePortfolios(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(portfolios);
      expect(mockGet).toHaveBeenCalledWith('/api/portfolios/');
    });
  });

  describe('usePortfolio', () => {
    it('fetches GET /api/portfolios/:id when portfolioId is set', async () => {
      const portfolio = { id: 1, name: 'Portfolio 1', created_at: null };
      mockGet.mockResolvedValueOnce({ data: portfolio } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePortfolio(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/portfolios/1');
    });

    it('is disabled when portfolioId is falsy', async () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePortfolio(0), { wrapper });

      // query should remain idle / not called
      expect(result.current.isFetching).toBe(false);
      expect(mockGet).not.toHaveBeenCalled();
    });
  });

  describe('useCreatePortfolio', () => {
    it('exposes mutateAsync that POSTs to /api/portfolios/', async () => {
      const portfolio = { id: 2, name: 'New', created_at: null };
      mockPost.mockResolvedValueOnce({ data: portfolio } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCreatePortfolio(), { wrapper });

      await result.current.mutateAsync({ name: 'New' });
      expect(mockPost).toHaveBeenCalledWith('/api/portfolios/', { name: 'New' });
    });
  });

  describe('useCreateDemoPortfolio', () => {
    it('POSTs to /api/portfolios/demo with no body', async () => {
      const portfolio = { id: 3, name: 'Démo', created_at: null };
      mockPost.mockResolvedValueOnce({ data: portfolio } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCreateDemoPortfolio(), { wrapper });

      const created = await result.current.mutateAsync();
      expect(mockPost).toHaveBeenCalledWith('/api/portfolios/demo');
      expect(created).toEqual(portfolio);
    });
  });

  describe('useRenamePortfolio', () => {
    it('PUTs to /api/portfolios/:id', async () => {
      const portfolio = { id: 1, name: 'Renamed', created_at: null };
      mockPut.mockResolvedValueOnce({ data: portfolio } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useRenamePortfolio(), { wrapper });

      await result.current.mutateAsync({ id: 1, name: 'Renamed' });
      expect(mockPut).toHaveBeenCalledWith('/api/portfolios/1', { name: 'Renamed' });
    });
  });

  describe('useDeletePortfolio', () => {
    it('DELETEs /api/portfolios/:id', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDeletePortfolio(), { wrapper });

      await result.current.mutateAsync(1);
      expect(mockDelete).toHaveBeenCalledWith('/api/portfolios/1');
    });
  });

  // ── Accounts ────────────────────────────────────────────────────────────────

  describe('useBrokers', () => {
    it('fetches accounts when userId is defined', async () => {
      const accounts = [{ id: 1, portfolio_id: 1, name: 'Degiro', currency: 'EUR' }];
      mockGet.mockResolvedValueOnce({ data: accounts } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useBrokers(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/brokers/', expect.objectContaining({ params: { portfolio_id: 1 } }));
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useBrokers(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useAccountsSummary', () => {
    it('fetches /api/accounts/summary when userId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useAccountsSummary(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/brokers/summary', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useAccountsSummary(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  // ── Products ────────────────────────────────────────────────────────────────

  describe('useProducts', () => {
    it('fetches GET /api/products/', async () => {
      const products = [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD' }];
      mockGet.mockResolvedValueOnce({ data: products } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useProducts(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/products/');
    });
  });

  // ── Transactions ────────────────────────────────────────────────────────────

  describe('useTransactions', () => {
    it('fetches transactions when userId is defined', async () => {
      const txns = [{ id: 1, ticker: 'AAPL' }];
      mockGet.mockResolvedValueOnce({ data: txns } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTransactions(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/transactions/', expect.anything());
    });

    it('fetches transactions with filters', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(
        () => useTransactions(1, { ticker: 'AAPL', limit: 10 }),
        { wrapper }
      );

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/transactions/', expect.objectContaining({
        params: expect.objectContaining({ ticker: 'AAPL', limit: 10 }),
      }));
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTransactions(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useCreateTransaction', () => {
    it('POSTs to /api/transactions/ and invalidates portfolio caches with string key', async () => {
      const payload = {
        portfolio_id: 1, account_id: 1, date: '2024-01-01',
        type: 'Actif', ticker: 'AAPL', currency: 'USD',
        exchange_rate: 1.1, quantity: 10, unit_price: 150,
      };
      mockPost.mockResolvedValueOnce({ data: { ...payload, id: 1 } } as any);

      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useCreateTransaction(), { wrapper });

      await result.current.mutateAsync(payload);
      expect(mockPost).toHaveBeenCalledWith('/api/transactions/', payload);

      // Bug fix: portfolio_id must be coerced to STRING to match useParams query keys
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['transactions', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['accounts-summary', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['holdings', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['holdings-history', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['dashboard', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['dashboard', 'daily-holding-values', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['tri', '1'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['snapshots'] });
    });
  });

  describe('useUpdateTransaction', () => {
    it('PUTs to /api/transactions/:id and invalidates caches', async () => {
      const tx = { id: 1, portfolio_id: 2, ticker: 'AAPL' };
      mockPut.mockResolvedValueOnce({ data: tx } as any);

      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useUpdateTransaction(), { wrapper });

      await result.current.mutateAsync({ id: 1, ticker: 'AAPL' } as any);
      expect(mockPut).toHaveBeenCalledWith('/api/transactions/1', { ticker: 'AAPL' });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['transactions', '2'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['snapshots'] });
    });
  });

  describe('useDeleteTransaction', () => {
    it('DELETEs /api/transactions/:id and invalidates caches', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useDeleteTransaction(), { wrapper });

      await result.current.mutateAsync({ id: 5, portfolio_id: 3 });
      expect(mockDelete).toHaveBeenCalledWith('/api/transactions/5');
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['transactions', '3'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['accounts-summary', '3'] });
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['snapshots'] });
    });
  });

  // ── Bulk transaction import ──────────────────────────────────────────────────

  describe('useValidateImport', () => {
    it('POSTs the file as multipart form data to /api/transactions/import/validate', async () => {
      const responseBody = { rows: [], summary: { total_rows: 0, ok: 0, errors: 0, duplicates: 0 } };
      mockPost.mockResolvedValueOnce({ data: responseBody } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useValidateImport(), { wrapper });

      const file = new File(['dummy'], 'import.xlsx');
      const data = await result.current.mutateAsync(file);

      expect(mockPost).toHaveBeenCalledWith(
        '/api/transactions/import/validate',
        expect.any(FormData),
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      const sentForm = mockPost.mock.calls[0][1] as FormData;
      expect(sentForm.get('file')).toBe(file);
      expect(data).toEqual(responseBody);
    });
  });

  describe('useCommitImport', () => {
    it('POSTs the file + include_rows as multipart form data and invalidates portfolio caches', async () => {
      const responseBody = { status: 'ok', imported_count: 2, created_transaction_ids: [10, 11] };
      mockPost.mockResolvedValueOnce({ data: responseBody } as any);

      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useCommitImport(), { wrapper });

      const file = new File(['dummy'], 'import.xlsx');
      const data = await result.current.mutateAsync({ file, includeRows: [2, 3], portfolioId: 7 });

      expect(mockPost).toHaveBeenCalledWith(
        '/api/transactions/import/commit',
        expect.any(FormData),
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      const sentForm = mockPost.mock.calls[0][1] as FormData;
      expect(sentForm.get('file')).toBe(file);
      expect(sentForm.get('include_rows')).toBe('[2,3]');
      expect(data).toEqual(responseBody);
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['transactions', '7'] });
    });
  });

  // ── Pools ───────────────────────────────────────────────────────────────────

  describe('usePools', () => {
    it('fetches pools when userId is defined', async () => {
      const pools = [{ id: 1, portfolio_id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, is_active: true }];
      mockGet.mockResolvedValueOnce({ data: pools } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePools(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/pools/', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePools(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('usePoolProducts', () => {
    it('fetches pool products when poolId is not null', async () => {
      const products = [{ pool_id: 1, ticker: 'AAPL' }];
      mockGet.mockResolvedValueOnce({ data: products } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePoolProducts(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/pools/1/products');
    });

    it('is disabled when poolId is null', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePoolProducts(null), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('usePoolAllocation', () => {
    it('fetches pool allocation when portfolioId and poolId are both set', async () => {
      const allocation = { pool_id: 1, pool_name: 'Energie', total_eur: 0, by_sector: [], by_company: [], unclassified_eur: 0, unclassified_pct: 0, holdings_updated_at: null };
      mockGet.mockResolvedValueOnce({ data: allocation } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePoolAllocation(1, 2), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/pools/2/allocation', expect.objectContaining({
        params: { portfolio_id: 1 },
      }));
    });

    it('is disabled when poolId is null', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePoolAllocation(1, null), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });

    it('is disabled when portfolioId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePoolAllocation(undefined, 2), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  // ── Prices ──────────────────────────────────────────────────────────────────

  describe('usePrices', () => {
    it('fetches prices when ticker is defined', async () => {
      const prices = [{ ticker: 'AAPL', date: '2024-01-01', price: 150, currency: 'USD', source: 'yahoo' }];
      mockGet.mockResolvedValueOnce({ data: prices } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePrices('AAPL'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/prices/', expect.objectContaining({
        params: { ticker: 'AAPL' },
      }));
    });

    it('is disabled when ticker is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => usePrices(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useCreatePrice', () => {
    it('POSTs to /api/prices/ with source defaulting to manual', async () => {
      const priceData = { ticker: 'AAPL', date: '2024-01-01', price: 150, currency: 'USD' };
      mockPost.mockResolvedValueOnce({ data: { ...priceData, source: 'manual' } } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCreatePrice(), { wrapper });

      await result.current.mutateAsync(priceData);
      expect(mockPost).toHaveBeenCalledWith('/api/prices/', expect.objectContaining({
        ticker: 'AAPL',
        source: 'manual',
      }));
    });

    it('POSTs with explicit source', async () => {
      const priceData = { ticker: 'AAPL', date: '2024-01-01', price: 150, currency: 'USD', source: 'yahoo' };
      mockPost.mockResolvedValueOnce({ data: priceData } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCreatePrice(), { wrapper });

      await result.current.mutateAsync(priceData);
      expect(mockPost).toHaveBeenCalledWith('/api/prices/', expect.objectContaining({ source: 'yahoo' }));
    });
  });

  // ── Holdings ──────────────────────────────────────────────────────────────

  describe('useHoldings', () => {
    it('fetches holdings when userId is defined', async () => {
      const holdings = [{ ticker: 'AAPL', quantity: 10 }];
      mockGet.mockResolvedValueOnce({ data: holdings } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useHoldings(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/holdings', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useHoldings(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useHoldingsAtDate', () => {
    it('fetches historical holdings when userId and snapDate are both set', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useHoldingsAtDate(1, '2024-01-01'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/holdings/history', expect.objectContaining({
        params: expect.objectContaining({ snap_date: '2024-01-01' }),
      }));
    });

    it('is disabled when snapDate is null', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useHoldingsAtDate(1, null), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useHoldingsAtDate(undefined, '2024-01-01'), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useEtfComposition', () => {
    it('fetches composition when ticker is defined', async () => {
      const composition = {
        ticker: 'FLXC.DE', name: 'Franklin FTSE China', top_holdings: [], top_holdings_coverage_pct: 0,
        sector_weightings: [], bond_duration: null, bond_maturity: null, holdings_updated_at: null,
      };
      mockGet.mockResolvedValueOnce({ data: composition } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useEtfComposition('FLXC.DE'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/holdings/FLXC.DE/composition');
    });

    it('is disabled when ticker is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useEtfComposition(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  // ── Macro indicators ─────────────────────────────────────────────────────────

  const ratioIndicatorFixture = {
    dates: ['2020-01-01'], ratio: [100], moving_avg: [95], ma_years: 7, status: 'above', latest_date: '2020-01-01',
    numerator_ticker: '^SPXEW', denominator_ticker: 'CL=F',
    numerator_label: 'S&P 500 Equal Weight', denominator_label: 'Pétrole (WTI)',
  };

  describe('useGrowthIndicator', () => {
    it('fetches the growth indicator for the given region', async () => {
      mockGet.mockResolvedValueOnce({ data: ratioIndicatorFixture } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useGrowthIndicator('fr'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/growth', { params: { region: 'fr' } });
      expect(result.current.data).toEqual(ratioIndicatorFixture);
    });
  });

  describe('useInflationIndicator', () => {
    it('fetches the inflation indicator for the given region', async () => {
      mockGet.mockResolvedValueOnce({ data: ratioIndicatorFixture } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useInflationIndicator('world'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/inflation', { params: { region: 'world' } });
    });
  });

  describe('useQuadrant', () => {
    it('fetches the quadrant classification for the given region', async () => {
      const quadrantFixture = {
        quadrant: 'goldilocks', growth_confidence: 0.5, inflation_confidence: 0.5,
        overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above',
        latest_date: '2026-08-01',
      };
      mockGet.mockResolvedValueOnce({ data: quadrantFixture } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useQuadrant('fr'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/quadrant', { params: { region: 'fr' } });
      expect(result.current.data).toEqual(quadrantFixture);
    });
  });

  describe('useMacroRegions', () => {
    it('fetches the region list', async () => {
      const regions = [{
        code: 'us', label: 'États-Unis', equity_ticker: '^SPXEW', bond_ticker: 'GOVT',
        equity_label: 'S&P 500 Equal Weight', bond_label: 'Obligations Trésor américain',
      }];
      mockGet.mockResolvedValueOnce({ data: regions } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useMacroRegions(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/regions');
      expect(result.current.data).toEqual(regions);
    });
  });

  describe('createMacroRegion', () => {
    it('posts a new region', async () => {
      const region = {
        code: 'de', label: 'Allemagne', equity_ticker: '^GDAXI', bond_ticker: 'BUND',
        equity_label: 'DAX 40', bond_label: 'Bund 10 ans',
      };
      mockPost.mockResolvedValueOnce({ data: region } as any);
      const result = await createMacroRegion(region);
      expect(mockPost).toHaveBeenCalledWith('/api/indicators/regions', region);
      expect(result).toEqual(region);
    });
  });

  describe('updateMacroRegion', () => {
    it('puts region changes', async () => {
      const body = {
        label: 'Deutschland', equity_ticker: 'EWG', bond_ticker: 'BUNL',
        equity_label: 'iShares MSCI Germany', bond_label: 'Bund 10-15 ans',
      };
      const updated = { code: 'de', ...body };
      mockPut.mockResolvedValueOnce({ data: updated } as any);
      const result = await updateMacroRegion('de', body);
      expect(mockPut).toHaveBeenCalledWith('/api/indicators/regions/de', body);
      expect(result).toEqual(updated);
    });
  });

  describe('deleteMacroRegion', () => {
    it('deletes a region by code', async () => {
      mockDelete.mockResolvedValueOnce({} as any);
      await deleteMacroRegion('de');
      expect(mockDelete).toHaveBeenCalledWith('/api/indicators/regions/de');
    });
  });

  describe('useCountryPerformance', () => {
    it('fetches the country performance ranking', async () => {
      const entries = [
        { code: 'us', label: 'États-Unis', currency: 'USD', perf_pct: 20.19, latest_date: '2026-07-19', anchor_date: '2025-07-19' },
      ];
      mockGet.mockResolvedValueOnce({ data: entries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCountryPerformance(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/country-performance');
      expect(result.current.data).toEqual(entries);
    });
  });

  describe('useCountryPerfConfigs', () => {
    it('fetches the country configuration list', async () => {
      const countries = [{ code: 'us', label: 'États-Unis', index_ticker: '^GSPC', currency: 'USD' }];
      mockGet.mockResolvedValueOnce({ data: countries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCountryPerfConfigs(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/country-performance/countries');
      expect(result.current.data).toEqual(countries);
    });
  });

  describe('createCountryPerfConfig', () => {
    it('posts a new country', async () => {
      const country = { code: 'de', label: 'Allemagne', index_ticker: '^GDAXI', currency: 'EUR', index_label: 'DAX 40' };
      mockPost.mockResolvedValueOnce({ data: country } as any);
      const result = await createCountryPerfConfig(country);
      expect(mockPost).toHaveBeenCalledWith('/api/indicators/country-performance/countries', country);
      expect(result).toEqual(country);
    });
  });

  describe('updateCountryPerfConfig', () => {
    it('puts country changes', async () => {
      const body = { label: 'Deutschland', index_ticker: 'EWG', currency: 'EUR', index_label: 'DAX ETF' };
      const updated = { code: 'de', ...body };
      mockPut.mockResolvedValueOnce({ data: updated } as any);
      const result = await updateCountryPerfConfig('de', body);
      expect(mockPut).toHaveBeenCalledWith('/api/indicators/country-performance/countries/de', body);
      expect(result).toEqual(updated);
    });
  });

  describe('deleteCountryPerfConfig', () => {
    it('deletes a country by code', async () => {
      mockDelete.mockResolvedValueOnce({} as any);
      await deleteCountryPerfConfig('de');
      expect(mockDelete).toHaveBeenCalledWith('/api/indicators/country-performance/countries/de');
    });
  });

  describe('useSectorPerformance', () => {
    it('fetches the sector performance ranking', async () => {
      const entries = [
        { code: 'or', label: 'Or', currency: 'USD', perf_pct: 20.19, latest_date: '2026-07-19', anchor_date: '2025-07-19' },
      ];
      mockGet.mockResolvedValueOnce({ data: entries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useSectorPerformance(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/sector-performance');
      expect(result.current.data).toEqual(entries);
    });
  });

  describe('useSectorPerfConfigs', () => {
    it('fetches the sector configuration list', async () => {
      const sectors = [{ code: 'or', label: 'Or', index_ticker: 'GC=F', currency: 'USD' }];
      mockGet.mockResolvedValueOnce({ data: sectors } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useSectorPerfConfigs(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/sector-performance/sectors');
      expect(result.current.data).toEqual(sectors);
    });
  });

  describe('createSectorPerfConfig', () => {
    it('posts a new sector', async () => {
      const sector = { code: 'metaux', label: 'Métaux industriels', index_ticker: 'DBB', currency: 'USD', index_label: 'Invesco DB Base Metals Fund' };
      mockPost.mockResolvedValueOnce({ data: sector } as any);
      const result = await createSectorPerfConfig(sector);
      expect(mockPost).toHaveBeenCalledWith('/api/indicators/sector-performance/sectors', sector);
      expect(result).toEqual(sector);
    });
  });

  describe('updateSectorPerfConfig', () => {
    it('puts sector changes', async () => {
      const body = { label: 'Or physique', index_ticker: 'GC=F', currency: 'USD', index_label: 'Gold Futures' };
      const updated = { code: 'or', ...body };
      mockPut.mockResolvedValueOnce({ data: updated } as any);
      const result = await updateSectorPerfConfig('or', body);
      expect(mockPut).toHaveBeenCalledWith('/api/indicators/sector-performance/sectors/or', body);
      expect(result).toEqual(updated);
    });
  });

  describe('deleteSectorPerfConfig', () => {
    it('deletes a sector by code', async () => {
      mockDelete.mockResolvedValueOnce({} as any);
      await deleteSectorPerfConfig('or');
      expect(mockDelete).toHaveBeenCalledWith('/api/indicators/sector-performance/sectors/or');
    });
  });

  describe('useEquityPremium', () => {
    it('fetches the equity risk premium ranking', async () => {
      const entries = [
        { code: 'us', label: 'États-Unis', premium_pct: 2.5, equity_yield_pct: 4.0, bond_yield_pct: 1.5,
          equity_label: 'S&P 500 (SPY)', bond_label: 'Trésor US (IEF)', asof_date: '2026-07-19' },
      ];
      mockGet.mockResolvedValueOnce({ data: entries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useEquityPremium(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/equity-premium');
      expect(result.current.data).toEqual(entries);
    });
  });

  describe('useEquityPremiumConfigs', () => {
    it('fetches the equity premium country list', async () => {
      const countries = [{ code: 'us', label: 'États-Unis', equity_ticker: 'SPY', bond_ticker: 'IEF', equity_label: 'S&P 500', bond_label: 'Trésor US' }];
      mockGet.mockResolvedValueOnce({ data: countries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useEquityPremiumConfigs(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/equity-premium/countries');
      expect(result.current.data).toEqual(countries);
    });
  });

  describe('createEquityPremiumConfig', () => {
    it('posts a new country', async () => {
      const country = { code: 'de', label: 'Allemagne', equity_ticker: 'EWG', bond_ticker: 'EXX6.DE', equity_label: 'Actions allemandes (EWG)', bond_label: 'Bund (EXX6.DE)' };
      mockPost.mockResolvedValueOnce({ data: country } as any);
      const result = await createEquityPremiumConfig(country);
      expect(mockPost).toHaveBeenCalledWith('/api/indicators/equity-premium/countries', country);
      expect(result).toEqual(country);
    });
  });

  describe('updateEquityPremiumConfig', () => {
    it('puts country changes', async () => {
      const body = { label: 'USA', equity_ticker: 'SPY', bond_ticker: 'IEF', equity_label: 'S&P 500 Index', bond_label: 'US Treasury 7-10y' };
      const updated = { code: 'us', ...body };
      mockPut.mockResolvedValueOnce({ data: updated } as any);
      const result = await updateEquityPremiumConfig('us', body);
      expect(mockPut).toHaveBeenCalledWith('/api/indicators/equity-premium/countries/us', body);
      expect(result).toEqual(updated);
    });
  });

  describe('deleteEquityPremiumConfig', () => {
    it('deletes a country by code', async () => {
      mockDelete.mockResolvedValueOnce({} as any);
      await deleteEquityPremiumConfig('us');
      expect(mockDelete).toHaveBeenCalledWith('/api/indicators/equity-premium/countries/us');
    });
  });

  describe('useBondPerformance', () => {
    it('fetches the sovereign bond performance ranking', async () => {
      const entries = [
        { code: 'us', label: 'États-Unis', currency: 'USD', perf_pct: -2.5, latest_date: '2026-09-06', anchor_date: '2025-09-06', index_label: 'Trésor américain 7-10 ans (IEF)' },
      ];
      mockGet.mockResolvedValueOnce({ data: entries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useBondPerformance(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/bond-performance');
      expect(result.current.data).toEqual(entries);
    });
  });

  describe('useBondPerfConfigs', () => {
    it('fetches the bond configuration list', async () => {
      const countries = [{ code: 'us', label: 'États-Unis', index_ticker: 'IEF', currency: 'USD', index_label: 'Trésor américain 7-10 ans (IEF)' }];
      mockGet.mockResolvedValueOnce({ data: countries } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useBondPerfConfigs(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/indicators/bond-performance/countries');
      expect(result.current.data).toEqual(countries);
    });
  });

  describe('createBondPerfConfig', () => {
    it('posts a new bond country', async () => {
      const country = { code: 'kr', label: 'Corée du Sud', index_ticker: '148070.KS', currency: 'KRW', index_label: "Obligations d'État coréennes 10 ans" };
      mockPost.mockResolvedValueOnce({ data: country } as any);
      const result = await createBondPerfConfig(country);
      expect(mockPost).toHaveBeenCalledWith('/api/indicators/bond-performance/countries', country);
      expect(result).toEqual(country);
    });
  });

  describe('updateBondPerfConfig', () => {
    it('puts bond country changes', async () => {
      const body = { label: 'USA', index_ticker: 'IEF', currency: 'USD', index_label: 'US Treasury 7-10y' };
      const updated = { code: 'us', ...body };
      mockPut.mockResolvedValueOnce({ data: updated } as any);
      const result = await updateBondPerfConfig('us', body);
      expect(mockPut).toHaveBeenCalledWith('/api/indicators/bond-performance/countries/us', body);
      expect(result).toEqual(updated);
    });
  });

  describe('deleteBondPerfConfig', () => {
    it('deletes a bond country by code', async () => {
      mockDelete.mockResolvedValueOnce({} as any);
      await deleteBondPerfConfig('us');
      expect(mockDelete).toHaveBeenCalledWith('/api/indicators/bond-performance/countries/us');
    });
  });

  // ── Dashboard ────────────────────────────────────────────────────────────────

  describe('useTRI', () => {
    it('fetches TRI when userId is defined', async () => {
      const tri = { tri_pct: 10, tri_label: '+10%', total_investi: 100000, total_retire: 0, valeur_actuelle: 110000, nb_flux: 5 };
      mockGet.mockResolvedValueOnce({ data: tri } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTRI(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/tri', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTRI(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useDashboard', () => {
    it('fetches dashboard when userId is defined', async () => {
      const dashboard = { total_eur: 100000 };
      mockGet.mockResolvedValueOnce({ data: dashboard } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDashboard(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDashboard(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  // ── Snapshots ────────────────────────────────────────────────────────────────

  describe('useDailySnapshots', () => {
    it('fetches daily snapshots when userId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailySnapshots(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/daily', expect.anything());
    });

    it('passes dateFrom and dateTo params', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailySnapshots(1, '2024-01-01', '2024-12-31'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/daily', expect.objectContaining({
        params: expect.objectContaining({ date_from: '2024-01-01', date_to: '2024-12-31' }),
      }));
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailySnapshots(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useMonthlySnapshots', () => {
    it('fetches monthly snapshots when userId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useMonthlySnapshots(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/monthly', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useMonthlySnapshots(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useDailyWithPools', () => {
    it('fetches daily-with-pools when userId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailyWithPools(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/daily-with-pools', expect.anything());
    });

    it('passes optional dateFrom param', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailyWithPools(1, '2024-01-01'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/daily-with-pools', expect.objectContaining({
        params: expect.objectContaining({ date_from: '2024-01-01' }),
      }));
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailyWithPools(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useDailyHoldingValues', () => {
    it('fetches daily holding values when userId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailyHoldingValues(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/daily-holding-values', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useDailyHoldingValues(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useTWRR', () => {
    it('fetches TWRR when userId is defined', async () => {
      const twrr = { total: [], offensive: [], defensive: [], pools: {}, positions: {} };
      mockGet.mockResolvedValueOnce({ data: twrr } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTWRR(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/snapshots/twrr', expect.anything());
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTWRR(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  // ── TWRR Summary ───────────────────────────────────────────────────────────

  describe('useTWRRSummary', () => {
    it('fetches GET /api/dashboard/twrr-summary when userId is defined', async () => {
      const summary = { twrr_1m: 0.01, twrr_3m: 0.03, twrr_6m: 0.06, twrr_ytd: 0.04, twrr_1y: 0.12, twrr_since_inception: 0.35, period_days: 365, start_date: '2024-01-01', end_date: '2024-12-31', start_index: 100, end_index: 135 };
      mockGet.mockResolvedValueOnce({ data: summary } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTWRRSummary(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(summary);
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/twrr-summary', expect.objectContaining({
        params: { portfolio_id: 1 },
      }));
    });

    it('accepts string userId from useParams', async () => {
      mockGet.mockResolvedValueOnce({ data: {} } as any);
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTWRRSummary('2'), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/dashboard/twrr-summary', expect.objectContaining({
        params: { portfolio_id: '2' },
      }));
    });

    it('is disabled when userId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useTWRRSummary(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
      expect(mockGet).not.toHaveBeenCalled();
    });
  });

  // ── Capital Gains ──────────────────────────────────────────────────────────

  describe('useCapitalGains', () => {
    const mockCapitalGains = {
      portfolio_id: 1,
      tickers: [
        {
          ticker: 'AAPL',
          product_name: 'Apple Inc',
          cump: 140.0,
          qty_held: 10,
          cost_basis_eur: 1400,
          current_value_eur: 1500,
          unrealized_pv: 100,
          realized_pv_total: 50,
          events: [],
        },
      ],
      total_unrealized_pv: 100,
      total_realized_pv: 50,
      total_pv: 150,
    };

    it('fetches GET /api/pv/ when portfolioId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: mockCapitalGains } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockCapitalGains);
      expect(mockGet).toHaveBeenCalledWith('/api/pv/', expect.objectContaining({
        params: expect.objectContaining({ portfolio_id: 1 }),
      }));
    });

    it('passes optional accountId param when provided', async () => {
      mockGet.mockResolvedValueOnce({ data: mockCapitalGains } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains(1, 42), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/pv/', expect.objectContaining({
        params: expect.objectContaining({ portfolio_id: 1, account_id: 42 }),
      }));
    });

    it('does not include account_id param when accountId is undefined', async () => {
      mockGet.mockResolvedValueOnce({ data: mockCapitalGains } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains(1, undefined), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      const callParams = (mockGet.mock.calls[0][1] as any)?.params;
      expect(callParams).not.toHaveProperty('account_id');
    });

    it('is disabled when portfolioId is undefined', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
      expect(mockGet).not.toHaveBeenCalled();
    });

    it('is disabled when portfolioId is falsy (0)', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains(0), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });

    it('accepts string portfolioId (from useParams)', async () => {
      mockGet.mockResolvedValueOnce({ data: mockCapitalGains } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useCapitalGains('1'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockGet).toHaveBeenCalledWith('/api/pv/', expect.objectContaining({
        params: expect.objectContaining({ portfolio_id: '1' }),
      }));
    });
  });
});

// ─── Coverage for lines 61-81: useAllBrokers + broker CRUD ───────────────────

describe('api/queries — useAllBrokers and broker CRUD (lines 61-81)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  describe('useAllBrokers', () => {
    it('GETs /api/brokers/ without params', async () => {
      const brokers = [{ id: 1, name: 'Degiro', currency: 'EUR', portfolio_ids: [] }];
      mockGet.mockResolvedValueOnce({ data: brokers } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useAllBrokers(), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(brokers);
      expect(mockGet).toHaveBeenCalledWith('/api/brokers/');
    });
  });

  describe('createBrokerAPI', () => {
    it('POSTs to /api/brokers/ and returns broker', async () => {
      const broker = { id: 2, name: 'IBKR', currency: 'USD', portfolio_ids: [1] };
      mockPost.mockResolvedValueOnce({ data: broker } as any);

      const result = await createBrokerAPI({ name: 'IBKR', currency: 'USD', portfolio_ids: [1] });

      expect(mockPost).toHaveBeenCalledWith('/api/brokers/', expect.objectContaining({ name: 'IBKR' }));
      expect(result).toEqual(broker);
    });
  });

  describe('updateBrokerPortfoliosAPI', () => {
    it('PUTs to /api/brokers/:id/portfolios', async () => {
      const broker = { id: 1, name: 'Degiro', currency: 'EUR', portfolio_ids: [1, 2] };
      mockPut.mockResolvedValueOnce({ data: broker } as any);

      const result = await updateBrokerPortfoliosAPI(1, [1, 2]);

      expect(mockPut).toHaveBeenCalledWith('/api/brokers/1/portfolios', { portfolio_ids: [1, 2] });
      expect(result).toEqual(broker);
    });
  });

  describe('updateBrokerAPI', () => {
    it('PUTs to /api/brokers/:id and returns updated broker', async () => {
      const broker = { id: 1, name: 'Updated', currency: 'EUR', portfolio_ids: [] };
      mockPut.mockResolvedValueOnce({ data: broker } as any);

      const result = await updateBrokerAPI(1, { name: 'Updated', color: '#ff0000' });

      expect(mockPut).toHaveBeenCalledWith('/api/brokers/1', { name: 'Updated', color: '#ff0000' });
      expect(result).toEqual(broker);
    });
  });

  describe('deleteBrokerAPI', () => {
    it('DELETEs /api/brokers/:id', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      await deleteBrokerAPI(5);

      expect(mockDelete).toHaveBeenCalledWith('/api/brokers/5');
    });
  });
});

// ─── Coverage for lines 470-595: fiscal + system settings hooks ───────────────

describe('api/queries — fiscal carry-forward hooks (lines 470-517)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  const mockCarryForward = { id: 1, portfolio_id: 1, tax_year: 2023, amount_eur: -5000 };

  describe('useFiscalCarryForwards', () => {
    it('GETs /api/fiscal/carry-forward/ when portfolioId is defined', async () => {
      mockGet.mockResolvedValueOnce({ data: [mockCarryForward] } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useFiscalCarryForwards(1), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual([mockCarryForward]);
      expect(mockGet).toHaveBeenCalledWith('/api/fiscal/carry-forward/', expect.objectContaining({
        params: expect.objectContaining({ portfolio_id: 1 }),
      }));
    });

    it('is disabled when portfolioId is falsy', () => {
      const wrapper = makeWrapper();
      const { result } = renderHook(() => useFiscalCarryForwards(undefined), { wrapper });
      expect(result.current.isFetching).toBe(false);
    });
  });

  describe('useCreateCarryForward', () => {
    it('POSTs to /api/fiscal/carry-forward/ and invalidates cache', async () => {
      mockPost.mockResolvedValueOnce({ data: mockCarryForward } as any);

      const qc = new QueryClient();
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useCreateCarryForward(), { wrapper });

      await result.current.mutateAsync({ portfolio_id: 1, tax_year: 2023, amount_eur: -5000 });

      expect(mockPost).toHaveBeenCalledWith('/api/fiscal/carry-forward/', expect.objectContaining({ tax_year: 2023 }));
      expect(invalidateSpy).toHaveBeenCalled();
    });
  });

  describe('useUpdateCarryForward', () => {
    it('PUTs to /api/fiscal/carry-forward/:id and invalidates cache', async () => {
      const updated = { ...mockCarryForward, amount_eur: -3000 };
      mockPut.mockResolvedValueOnce({ data: updated } as any);

      const qc = new QueryClient();
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useUpdateCarryForward(), { wrapper });

      await result.current.mutateAsync({ id: 1, portfolio_id: 1, amount_eur: -3000 });

      expect(mockPut).toHaveBeenCalledWith('/api/fiscal/carry-forward/1', { amount_eur: -3000 });
      expect(invalidateSpy).toHaveBeenCalled();
    });
  });

  describe('useDeleteCarryForward', () => {
    it('DELETEs /api/fiscal/carry-forward/:id and invalidates cache', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      const qc = new QueryClient();
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useDeleteCarryForward(), { wrapper });

      await result.current.mutateAsync({ id: 1, portfolio_id: 1 });

      expect(mockDelete).toHaveBeenCalledWith('/api/fiscal/carry-forward/1');
      expect(invalidateSpy).toHaveBeenCalled();
    });
  });
});

describe('api/queries — useFiscalCurrentYearPv (lines 536-546)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  const mockFiscalPv = { year: 2025, net_realized_pv: 1500, details: [], loss_harvesting_candidates: [] };

  it('GETs /api/fiscal/current-year-pv/ with portfolioId', async () => {
    mockGet.mockResolvedValueOnce({ data: mockFiscalPv } as any);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useFiscalCurrentYearPv(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockFiscalPv);
    expect(mockGet).toHaveBeenCalledWith('/api/fiscal/current-year-pv/', expect.objectContaining({
      params: expect.objectContaining({ portfolio_id: 1 }),
    }));
  });

  it('passes year param when provided', async () => {
    mockGet.mockResolvedValueOnce({ data: mockFiscalPv } as any);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useFiscalCurrentYearPv(1, 2024), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockGet).toHaveBeenCalledWith('/api/fiscal/current-year-pv/', expect.objectContaining({
      params: expect.objectContaining({ year: 2024 }),
    }));
  });

  it('is disabled when portfolioId is falsy', () => {
    const wrapper = makeWrapper();
    const { result } = renderHook(() => useFiscalCurrentYearPv(undefined), { wrapper });
    expect(result.current.isFetching).toBe(false);
  });
});

describe('api/queries — useGitHubUpdateStatus (lines 559-567)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('GETs /api/admin/github-update-status', async () => {
    const status = { status: 'up_to_date', current_version: '0.4.0', latest_version: '0.4.0', release_url: null, checked_at: null, error: null };
    mockGet.mockResolvedValueOnce({ data: status } as any);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useGitHubUpdateStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(status);
    expect(mockGet).toHaveBeenCalledWith('/api/admin/github-update-status');
  });
});

describe('api/queries — system settings hooks (lines 569-597)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  describe('useSystemSetting', () => {
    it('GETs /api/admin/settings/:key', async () => {
      const setting = { key: 'ttf_rate', value: '0.004' };
      mockGet.mockResolvedValueOnce({ data: setting } as any);

      const wrapper = makeWrapper();
      const { result } = renderHook(() => useSystemSetting('ttf_rate'), { wrapper });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(setting);
      expect(mockGet).toHaveBeenCalledWith('/api/admin/settings/ttf_rate');
    });
  });

  describe('useSetSystemSetting', () => {
    it('PUTs to /api/admin/settings/:key and invalidates', async () => {
      const setting = { key: 'ttf_rate', value: '0.003' };
      mockPut.mockResolvedValueOnce({ data: setting } as any);

      const qc = new QueryClient();
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useSetSystemSetting(), { wrapper });

      await result.current.mutateAsync({ key: 'ttf_rate', value: '0.003' });

      expect(mockPut).toHaveBeenCalledWith('/api/admin/settings/ttf_rate', { value: '0.003' });
      expect(invalidateSpy).toHaveBeenCalled();
    });
  });

  describe('useDeleteSystemSetting', () => {
    it('DELETEs /api/admin/settings/:key and invalidates', async () => {
      mockDelete.mockResolvedValueOnce({} as any);

      const qc = new QueryClient();
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
      const wrapper = makeWrapper(qc);
      const { result } = renderHook(() => useDeleteSystemSetting(), { wrapper });

      await result.current.mutateAsync('ttf_rate');

      expect(mockDelete).toHaveBeenCalledWith('/api/admin/settings/ttf_rate');
      expect(invalidateSpy).toHaveBeenCalled();
    });
  });
});

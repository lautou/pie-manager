// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => ({ ...pfCoreStubs }));
vi.mock('@patternfly/react-table', () => ({ ...pfTableStubs }));

const mockUseSearchParams = vi.fn();
vi.mock('react-router-dom', () => ({
  useSearchParams: () => mockUseSearchParams(),
}));

const mockUseQuadrant = vi.fn();
const mockUseHoldings = vi.fn();
vi.mock('../api/queries', () => ({
  useQuadrant: (region: string) => mockUseQuadrant(region),
  useHoldings: (userId: string | undefined) => mockUseHoldings(userId),
}));

import QuadrantCard from './QuadrantCard';

const holdings = [
  { ticker: 'A', product_name: 'A', category: 'Actif', instrument_type: 'ETF', pool_id: null, pool_name: null, quantity: 1, last_price: 1, last_price_date: null, last_price_source: 'manual', value_eur: 70, currency: 'EUR' },
  { ticker: 'B', product_name: 'B', category: 'Actif', instrument_type: 'Obligation', pool_id: null, pool_name: null, quantity: 1, last_price: 1, last_price_date: null, last_price_source: 'manual', value_eur: 30, currency: 'EUR' },
];

describe('QuadrantCard', () => {
  beforeEach(() => {
    mockUseSearchParams.mockReturnValue([new URLSearchParams(), vi.fn()]);
    mockUseHoldings.mockReturnValue({ data: undefined });
  });

  it('shows a spinner while loading', () => {
    mockUseQuadrant.mockReturnValue({ data: undefined, isLoading: true });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows the no-data message when the quadrant is null', () => {
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: null, growth_confidence: null, inflation_confidence: null, overall_confidence: null, growth_status: null, inflation_status: null, latest_date: null },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.getByText(/Aucune donnée pour le moment/)).toBeInTheDocument();
  });

  it.each([
    ['goldilocks', 'favorable', 'favorable', 'defavorable', 'defavorable'],
    ['overheating', 'favorable', 'defavorable', 'favorable', 'defavorable'],
    ['disinflationary_slowdown', 'defavorable', 'favorable', 'defavorable', 'favorable'],
    ['stagflation', 'defavorable', 'defavorable', 'favorable', 'favorable'],
  ] as const)('renders the favorability table for quadrant %s', (quadrant, actions, obligations, or_, cash) => {
    mockUseQuadrant.mockReturnValue({
      data: { quadrant, growth_confidence: 0.5, inflation_confidence: 0.5, overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);

    const rows = screen.getAllByRole('row').slice(1); // skip header row
    const cellsOf = (row: HTMLElement) => row.querySelectorAll('td');
    expect(cellsOf(rows[0])[1].textContent).toBe(actions === 'favorable' ? 'Favorable' : 'Défavorable');
    expect(cellsOf(rows[1])[1].textContent).toBe(obligations === 'favorable' ? 'Favorable' : 'Défavorable');
    expect(cellsOf(rows[2])[1].textContent).toBe(or_ === 'favorable' ? 'Favorable' : 'Défavorable');
    expect(cellsOf(rows[3])[1].textContent).toBe(cash === 'favorable' ? 'Favorable' : 'Défavorable');
  });

  it('shows the overall confidence value when present', () => {
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: 'goldilocks', growth_confidence: 0.4, inflation_confidence: 0.6, overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.getByText(/Confiance/)).toHaveTextContent('0.50');
  });

  it('does not show a confidence value when overall_confidence is null', () => {
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: 'goldilocks', growth_confidence: null, inflation_confidence: null, overall_confidence: null, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.queryByText(/Confiance/)).not.toBeInTheDocument();
  });

  it('shows a hint and no allocation column when there is no portfolio context', () => {
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: 'goldilocks', growth_confidence: 0.5, inflation_confidence: 0.5, overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.getByText(/Accède à cette page depuis un portefeuille/)).toBeInTheDocument();
    expect(screen.queryByText('Ton allocation')).not.toBeInTheDocument();
  });

  it('shows the allocation column computed from holdings when a portfolio context is present', () => {
    mockUseSearchParams.mockReturnValue([new URLSearchParams('from=3'), vi.fn()]);
    mockUseHoldings.mockReturnValue({ data: holdings });
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: 'goldilocks', growth_confidence: 0.5, inflation_confidence: 0.5, overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(mockUseHoldings).toHaveBeenCalledWith('3');
    expect(screen.getByText('Ton allocation')).toBeInTheDocument();
    expect(screen.getByText('70.0 %')).toBeInTheDocument();
    expect(screen.getByText('30.0 %')).toBeInTheDocument();
    expect(screen.queryByText(/Accède à cette page depuis un portefeuille/)).not.toBeInTheDocument();
  });

  it('shows a placeholder in the allocation column while holdings have not loaded yet', () => {
    mockUseSearchParams.mockReturnValue([new URLSearchParams('from=3'), vi.fn()]);
    mockUseHoldings.mockReturnValue({ data: undefined });
    mockUseQuadrant.mockReturnValue({
      data: { quadrant: 'goldilocks', growth_confidence: 0.5, inflation_confidence: 0.5, overall_confidence: 0.5, growth_status: 'above', inflation_status: 'above', latest_date: '2026-08-01' },
      isLoading: false,
    });
    render(<QuadrantCard region="us" regionLabel="États-Unis" />);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

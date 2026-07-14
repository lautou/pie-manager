import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

const mockUsePoolAllocation = vi.fn();

vi.mock('@patternfly/react-core', () => pfCoreStubs);
vi.mock('@patternfly/react-table', () => pfTableStubs);
vi.mock('@patternfly/react-charts', () => ({
  ChartDonut: ({ data, labels }: any) => (
    <div data-testid="chart-donut">
      {data?.map((d: any, i: number) => <div key={i}>{labels ? labels({ datum: d }) : d.x}</div>)}
    </div>
  ),
  ChartThemeColor: { multi: 'multi' },
}));
vi.mock('../api/queries', () => ({
  usePoolAllocation: (...args: any[]) => mockUsePoolAllocation(...args),
}));

import PoolAllocationSection from './PoolAllocationSection';

describe('PoolAllocationSection', () => {
  it('renders nothing when there is no allocation data at all', () => {
    mockUsePoolAllocation.mockReturnValue({
      data: {
        pool_id: 1, pool_name: 'Energie', total_eur: 0,
        by_sector: [], by_company: [], unclassified_eur: 0, unclassified_pct: 0,
        holdings_updated_at: null,
      },
    });
    const { container } = render(<PoolAllocationSection portfolioId={1} poolId={1} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing while data is undefined (loading)', () => {
    mockUsePoolAllocation.mockReturnValue({ data: undefined });
    const { container } = render(<PoolAllocationSection portfolioId={1} poolId={1} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the sector donut by default, translating sector keys', () => {
    mockUsePoolAllocation.mockReturnValue({
      data: {
        pool_id: 1, pool_name: 'Energie', total_eur: 800,
        by_sector: [{ key: 'energy', label: 'energy', value_eur: 700, pct: 87.5 }],
        by_company: [{ key: 'TTE.PA', label: 'TotalEnergies SE', value_eur: 393.15, pct: 49.14 }],
        unclassified_eur: 0, unclassified_pct: 0,
        holdings_updated_at: null,
      },
    });
    render(<PoolAllocationSection portfolioId={1} poolId={1} />);
    expect(screen.getByTestId('chart-donut')).toBeTruthy();
    expect(screen.getByText(/Énergie/)).toBeTruthy();
  });

  it('switches to the company tab and shows the merged TotalEnergies line plus OTHER and unclassified rows', async () => {
    const user = userEvent.setup();
    mockUsePoolAllocation.mockReturnValue({
      data: {
        pool_id: 1, pool_name: 'Energie', total_eur: 1000,
        by_sector: [{ key: 'energy', label: 'energy', value_eur: 1000, pct: 100 }],
        by_company: [
          { key: 'TTE.PA', label: 'TotalEnergies SE', value_eur: 393.15, pct: 39.3 },
          { key: '__OTHER__', label: '__OTHER__', value_eur: 231.35, pct: 23.1 },
        ],
        unclassified_eur: 50, unclassified_pct: 5,
        holdings_updated_at: null,
      },
    });
    render(<PoolAllocationSection portfolioId={1} poolId={1} />);
    await user.click(screen.getByText('Par entreprise'));
    expect(screen.getByText('TotalEnergies SE')).toBeTruthy();
    expect(screen.getByText('Autres non détaillés')).toBeTruthy();
    expect(screen.getByText('Non classé (pas encore synchronisé)')).toBeTruthy();
  });
});

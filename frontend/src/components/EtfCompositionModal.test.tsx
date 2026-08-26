// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

const mockUseEtfComposition = vi.fn();

vi.mock('@patternfly/react-core', () => pfCoreStubs);
vi.mock('@patternfly/react-table', () => pfTableStubs);
vi.mock('../api/queries', () => ({
  useEtfComposition: (...args: any[]) => mockUseEtfComposition(...args),
}));

import EtfCompositionModal from './EtfCompositionModal';

describe('EtfCompositionModal', () => {
  it('renders nothing (closed modal) when ticker is null', () => {
    mockUseEtfComposition.mockReturnValue({ data: undefined, isLoading: false });
    render(<EtfCompositionModal ticker={null} onClose={vi.fn()} />);
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('shows a spinner while loading', () => {
    mockUseEtfComposition.mockReturnValue({ data: undefined, isLoading: true });
    render(<EtfCompositionModal ticker="FLXC.DE" onClose={vi.fn()} />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows the no-data message when composition has no holdings and no sectors', () => {
    mockUseEtfComposition.mockReturnValue({
      data: {
        ticker: 'XJSE.DE', name: 'Japan Govt Bond', top_holdings: [], top_holdings_coverage_pct: 0,
        sector_weightings: [], bond_duration: null, bond_maturity: null, holdings_updated_at: null,
      },
      isLoading: false,
    });
    render(<EtfCompositionModal ticker="XJSE.DE" onClose={vi.fn()} />);
    expect(screen.getByText(/Aucune donnée de composition/)).toBeInTheDocument();
  });

  it('renders top holdings, sector weightings, and freshness when data is present', () => {
    mockUseEtfComposition.mockReturnValue({
      data: {
        ticker: 'FLXC.DE', name: 'Franklin FTSE China', top_holdings: [
          { ticker: '0700.HK', name: 'Tencent Holdings Ltd', weight_pct: 0.1239 },
          { ticker: '9988.HK', name: 'Alibaba Group Holding', weight_pct: 0.0783 },
        ],
        top_holdings_coverage_pct: 20.22,
        sector_weightings: [{ sector: 'consumer_cyclical', weight_pct: 0.2149 }],
        bond_duration: null, bond_maturity: null,
        holdings_updated_at: '2026-07-14T06:00:00Z',
      },
      isLoading: false,
    });
    render(<EtfCompositionModal ticker="FLXC.DE" onClose={vi.fn()} />);
    expect(screen.getByText('0700.HK')).toBeInTheDocument();
    expect(screen.getByText('Tencent Holdings Ltd')).toBeInTheDocument();
    expect(screen.getByText('9988.HK')).toBeInTheDocument();
    expect(screen.getByText(/Consommation cyclique/)).toBeInTheDocument();
    expect(screen.getByText(/Dernière mise à jour/)).toBeInTheDocument();
  });

  it('renders bond duration/maturity when present and "never updated" when holdings_updated_at is null', () => {
    mockUseEtfComposition.mockReturnValue({
      data: {
        ticker: 'XJSE.DE', name: 'Japan Govt Bond',
        top_holdings: [], top_holdings_coverage_pct: 0,
        sector_weightings: [{ sector: 'energy', weight_pct: 1.0 }],
        bond_duration: 1.32, bond_maturity: 8.57,
        holdings_updated_at: null,
      },
      isLoading: false,
    });
    render(<EtfCompositionModal ticker="XJSE.DE" onClose={vi.fn()} />);
    expect(screen.getByText(/1.32/)).toBeInTheDocument();
    expect(screen.getByText(/8.57/)).toBeInTheDocument();
    expect(screen.getByText('Jamais synchronisé')).toBeInTheDocument();
  });

  it('falls back to the raw sector key when no i18n translation exists', () => {
    mockUseEtfComposition.mockReturnValue({
      data: {
        ticker: 'WEIRD.DE', name: 'Weird Fund', top_holdings: [],
        top_holdings_coverage_pct: 0,
        sector_weightings: [{ sector: 'not_a_real_sector', weight_pct: 1.0 }],
        bond_duration: null, bond_maturity: null, holdings_updated_at: null,
      },
      isLoading: false,
    });
    render(<EtfCompositionModal ticker="WEIRD.DE" onClose={vi.fn()} />);
    expect(screen.getByText('not_a_real_sector')).toBeInTheDocument();
  });
});

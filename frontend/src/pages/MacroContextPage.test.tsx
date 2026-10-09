// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for MacroContextPage — extracted from RebalancingPage.tsx's former
 * "Contexte macro-économique" card (see .claude/rules/rebalancing.md /
 * .claude/rules/macro-indicators.md).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
}));

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
}));

// QuadrantCard's own rendering (favorability table, allocation column, etc.) is already
// covered by QuadrantCard.test.tsx — here we only assert it receives the right region/
// portfolioId props (an explicit prop, never a silent URL `?from=` param).
vi.mock('../components/QuadrantCard', () => ({
  default: ({ region, regionLabel, portfolioId }: any) => (
    <div data-testid="quadrant-card">{region}|{regionLabel}|{String(portfolioId)}</div>
  ),
}));

const mockUseMacroRegions = vi.fn();
vi.mock('../api/queries', () => ({
  useMacroRegions: () => mockUseMacroRegions(),
}));

import MacroContextPage from './MacroContextPage';

const macroRegions = [
  { code: 'us', label: 'États-Unis', equity_ticker: '^SPXEW', bond_ticker: 'GOVT' },
  { code: 'fr', label: 'France', equity_ticker: '^FCHI', bond_ticker: 'MTE.PA' },
];

describe('MacroContextPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMacroRegions.mockReturnValue({ data: macroRegions });
  });

  it('renders the page title and the visible "Zone économique" region label', () => {
    render(<MacroContextPage />);
    expect(screen.getByText('Contexte macro')).toBeInTheDocument();
    expect(screen.getByText('Zone économique')).toBeInTheDocument();
  });

  it('defaults to the first region and passes the route portfolio ID to QuadrantCard', () => {
    render(<MacroContextPage />);
    // portfolioId comes from useParams (mocked to '1' above) — an explicit prop,
    // never a silent URL `?from=` param the way the old QuadrantCard used to infer it.
    expect(screen.getByTestId('quadrant-card')).toHaveTextContent('us|États-Unis|1');
  });

  it('switching the region combobox updates the QuadrantCard region props', async () => {
    const user = userEvent.setup({ delay: null });
    render(<MacroContextPage />);
    expect(screen.getByTestId('quadrant-card')).toHaveTextContent('us|États-Unis|1');

    await user.selectOptions(screen.getByRole('combobox'), 'fr');
    expect(screen.getByTestId('quadrant-card')).toHaveTextContent('fr|France|1');
  });

  it('does not render QuadrantCard when the region list is empty', () => {
    mockUseMacroRegions.mockReturnValue({ data: [] });
    render(<MacroContextPage />);
    expect(screen.getByText('Zone économique')).toBeInTheDocument();
    expect(screen.queryByTestId('quadrant-card')).not.toBeInTheDocument();
  });
});

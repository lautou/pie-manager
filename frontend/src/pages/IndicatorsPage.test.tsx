// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => ({ ...pfCoreStubs }));

vi.mock('../components/GrowthInflationSection', () => ({
  default: () => <div data-testid="growth-inflation-content">growth-inflation</div>,
}));
vi.mock('../components/MarketPerformanceSection', () => ({
  default: () => <div data-testid="market-performance-content">market-performance</div>,
}));
vi.mock('../components/SectorPerformanceSection', () => ({
  default: () => <div data-testid="sector-performance-content">sector-performance</div>,
}));
vi.mock('../components/EquityPremiumSection', () => ({
  default: () => <div data-testid="equity-premium-content">equity-premium</div>,
}));

import IndicatorsPage from './IndicatorsPage';

describe('IndicatorsPage', () => {
  it('renders the page title and all tab titles', () => {
    render(<IndicatorsPage />);
    expect(screen.getByText('Indicateurs macro')).toBeInTheDocument();
    expect(screen.getByText('Croissance / Inflation')).toBeInTheDocument();
    expect(screen.getByText('Performance des actions')).toBeInTheDocument();
    expect(screen.getByText("Performance des classes d'actifs")).toBeInTheDocument();
    expect(screen.getByText('Premium action')).toBeInTheDocument();
  });

  it('mounts only the Croissance/Inflation tab content by default', () => {
    render(<IndicatorsPage />);
    expect(screen.getByTestId('growth-inflation-content')).toBeInTheDocument();
    expect(screen.queryByTestId('market-performance-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sector-performance-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('equity-premium-content')).not.toBeInTheDocument();
  });

  it('switching tabs mounts Performance des actions and unmounts Croissance/Inflation', async () => {
    const user = userEvent.setup({ delay: null });
    render(<IndicatorsPage />);

    await user.click(screen.getByText('Performance des actions'));

    expect(screen.getByTestId('market-performance-content')).toBeInTheDocument();
    expect(screen.queryByTestId('growth-inflation-content')).not.toBeInTheDocument();
  });

  it("switching tabs mounts Performance des classes d'actifs and unmounts Croissance/Inflation", async () => {
    const user = userEvent.setup({ delay: null });
    render(<IndicatorsPage />);

    await user.click(screen.getByText("Performance des classes d'actifs"));

    expect(screen.getByTestId('sector-performance-content')).toBeInTheDocument();
    expect(screen.queryByTestId('growth-inflation-content')).not.toBeInTheDocument();
  });

  it('switching tabs mounts Premium action and unmounts Croissance/Inflation', async () => {
    const user = userEvent.setup({ delay: null });
    render(<IndicatorsPage />);

    await user.click(screen.getByText('Premium action'));

    expect(screen.getByTestId('equity-premium-content')).toBeInTheDocument();
    expect(screen.queryByTestId('growth-inflation-content')).not.toBeInTheDocument();
  });
});

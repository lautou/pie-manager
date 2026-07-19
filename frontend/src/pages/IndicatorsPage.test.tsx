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

import IndicatorsPage from './IndicatorsPage';

describe('IndicatorsPage', () => {
  it('renders the page title and both tab titles', () => {
    render(<IndicatorsPage />);
    expect(screen.getByText('Indicateurs macro')).toBeInTheDocument();
    expect(screen.getByText('Croissance / Inflation')).toBeInTheDocument();
    expect(screen.getByText('Performance des marchés')).toBeInTheDocument();
  });

  it('mounts only the Croissance/Inflation tab content by default', () => {
    render(<IndicatorsPage />);
    expect(screen.getByTestId('growth-inflation-content')).toBeInTheDocument();
    expect(screen.queryByTestId('market-performance-content')).not.toBeInTheDocument();
  });

  it('switching tabs mounts Performance des marchés and unmounts Croissance/Inflation', async () => {
    const user = userEvent.setup({ delay: null });
    render(<IndicatorsPage />);

    await user.click(screen.getByText('Performance des marchés'));

    expect(screen.getByTestId('market-performance-content')).toBeInTheDocument();
    expect(screen.queryByTestId('growth-inflation-content')).not.toBeInTheDocument();
  });
});

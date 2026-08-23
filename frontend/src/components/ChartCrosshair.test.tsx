// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import ChartCrosshair from './ChartCrosshair';

describe('ChartCrosshair', () => {
  it('renders nothing when crosshair is null', () => {
    const { container } = render(<ChartCrosshair crosshair={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the date header and one bullet row per series', () => {
    render(
      <ChartCrosshair
        crosshair={{
          xPx: 50,
          date: new Date('2020-06-15'),
          series: [
            { name: 'Offensif', value: 111.532, color: '#0066CC' },
            { name: 'Défensif', value: 103.561, color: '#3E8635' },
          ],
          containerWidth: 800,
        }}
      />
    );
    expect(screen.getByTestId('crosshair-line')).toBeInTheDocument();
    const tooltip = screen.getByTestId('crosshair-tooltip');
    expect(tooltip).toHaveTextContent('15/06/2020');
    expect(tooltip).toHaveTextContent('Offensif:');
    expect(tooltip).toHaveTextContent('111.53');
    expect(tooltip).toHaveTextContent('Défensif:');
    expect(tooltip).toHaveTextContent('103.56');
  });

  it('positions the tooltip to the right of the cursor when there is room', () => {
    render(
      <ChartCrosshair
        crosshair={{ xPx: 50, date: new Date('2020-01-01'), series: [{ name: 'A', value: 1, color: '#000' }], containerWidth: 800 }}
      />
    );
    expect(screen.getByTestId('crosshair-tooltip')).toHaveStyle({ left: '58px' });
  });

  it('flips the tooltip to the left of the cursor near the right edge of the chart', () => {
    render(
      <ChartCrosshair
        crosshair={{ xPx: 780, date: new Date('2020-01-01'), series: [{ name: 'A', value: 1, color: '#000' }], containerWidth: 800 }}
      />
    );
    expect(screen.getByTestId('crosshair-tooltip')).toHaveStyle({ left: '620px' });
  });
});

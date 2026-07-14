import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => pfCoreStubs);

import TickerLink from './TickerLink';

describe('TickerLink', () => {
  it.each(['ETF', 'SICAV/FCP', 'Action'])(
    'renders a clickable button for composable instrument type %s',
    async (instrumentType) => {
      const onClick = vi.fn();
      render(<TickerLink ticker="FLXC.DE" instrumentType={instrumentType} onClick={onClick} />);
      const button = screen.getByText('FLXC.DE').closest('button');
      expect(button).not.toBeNull();
      await userEvent.click(screen.getByText('FLXC.DE'));
      expect(onClick).toHaveBeenCalledWith('FLXC.DE');
    }
  );

  it.each(['Cash', 'Or physique', 'Obligation', null, undefined])(
    'renders plain text (no button) for non-composable instrument type %s',
    (instrumentType) => {
      const onClick = vi.fn();
      render(<TickerLink ticker="LIQUIDITE.EURO" instrumentType={instrumentType as any} onClick={onClick} />);
      expect(screen.getByText('LIQUIDITE.EURO').closest('button')).toBeNull();
    }
  );
});

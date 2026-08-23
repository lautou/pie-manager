// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import '../../src/i18n';

const mockUseSystemSetting = vi.fn();
const mockUseSetSystemSetting = vi.fn();

vi.mock('../api/queries', () => ({
  useSystemSetting: (key: string) => mockUseSystemSetting(key),
  useSetSystemSetting: () => mockUseSetSystemSetting(),
}));

import SettingField from './SettingField';

describe('SettingField', () => {
  beforeEach(() => {
    mockUseSystemSetting.mockReturnValue({ data: undefined });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  });

  it('seeds the input from defaultValue when no setting is saved yet', () => {
    render(<SettingField settingKey="macro.ticker.oil" label="Ticker Pétrole" defaultValue="CL=F" />);
    expect(screen.getByLabelText('Ticker Pétrole')).toHaveValue('CL=F');
  });

  it('seeds the input from the fetched setting value when present', () => {
    mockUseSystemSetting.mockReturnValue({ data: { key: 'macro.ticker.oil', value: 'BZ=F' } });
    render(<SettingField settingKey="macro.ticker.oil" label="Ticker Pétrole" defaultValue="CL=F" />);
    expect(screen.getByLabelText('Ticker Pétrole')).toHaveValue('BZ=F');
  });

  it('renders a number input when type="number"', () => {
    render(<SettingField settingKey="macro.ma_years" label="Durée MM" defaultValue="7" type="number" />);
    expect(screen.getByLabelText('Durée MM')).toHaveValue(7);
  });

  it('shows the pending label while a save is in flight', () => {
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });
    render(<SettingField settingKey="macro.ticker.oil" label="Ticker Pétrole" defaultValue="CL=F" />);
    expect(screen.getByText('Enregistrer…')).toBeInTheDocument();
  });

  describe('save flow', () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it('saves the edited value and shows a transient confirmation', async () => {
      const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
      const mockMutateAsync = vi.fn().mockResolvedValue({});
      mockUseSetSystemSetting.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
      render(<SettingField settingKey="macro.ticker.oil" label="Ticker Pétrole" defaultValue="CL=F" />);

      const input = screen.getByLabelText('Ticker Pétrole');
      await user.clear(input);
      await user.type(input, 'BZ=F');
      await act(async () => { await user.click(screen.getByText('Enregistrer')); });

      expect(mockMutateAsync).toHaveBeenCalledWith({ key: 'macro.ticker.oil', value: 'BZ=F' });
      expect(screen.getByText('✓ Enregistrer')).toBeInTheDocument();

      await act(async () => { vi.advanceTimersByTime(2000); });
      expect(screen.queryByText('✓ Enregistrer')).not.toBeInTheDocument();
    });

    it('selects all text on focus', async () => {
      const user = userEvent.setup({ delay: null });
      render(<SettingField settingKey="macro.ticker.oil" label="Ticker Pétrole" defaultValue="CL=F" />);
      const input = screen.getByLabelText('Ticker Pétrole') as HTMLInputElement;
      await user.click(input);
      expect(input.selectionStart).toBe(0);
      expect(input.selectionEnd).toBe(input.value.length);
    });
  });
});

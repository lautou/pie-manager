/**
 * Tests for FrDatePicker component.
 *
 * FrDatePicker wraps PatternFly's DatePicker with French locale helpers.
 * PatternFly's DatePicker uses ResizeObserver and CSS variables that are
 * unavailable in jsdom, so we mock it completely.
 *
 * We test:
 * 1. The component renders without error (module exports a valid React component).
 * 2. The mocked DatePicker receives the correct props (value converted from ISO,
 *    correct callbacks, placeholder, disabled state).
 * 3. The onChange callback is called with the right ISO string when PatternFly
 *    fires its callback with a valid Date.
 * 4. The onChange callback is called with '' when PatternFly fires with no string.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import type { ComponentProps } from 'react';
import FrDatePicker from './FrDatePicker';
import { isoToDisplay } from './FrDatePicker.utils';

// ---------------------------------------------------------------------------
// Capture the props passed to PatternFly DatePicker
// ---------------------------------------------------------------------------

type DatePickerProps = ComponentProps<'input'> & {
  value?: string;
  dateFormat?: (date: Date) => string;
  dateParse?: (value: string) => Date;
  placeholder?: string;
  isDisabled?: boolean;
  onChange?: (evt: Event, strVal: string, date?: Date) => void;
  appendTo?: () => HTMLElement;
  id?: string;
};

let capturedProps: DatePickerProps | null = null;

vi.mock('@patternfly/react-core', () => ({
  DatePicker: (props: DatePickerProps) => {
    capturedProps = props;
    return null; // No DOM output needed — we inspect props directly
  },
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FrDatePicker', () => {
  beforeEach(() => {
    capturedProps = null;
    vi.clearAllMocks();
  });

  it('is a function (valid React component)', async () => {
    const mod = await import('./FrDatePicker');
    expect(typeof mod.default).toBe('function');
  });

  it('renders without throwing', () => {
    expect(() =>
      render(<FrDatePicker value="2025-06-15" onChange={() => {}} />)
    ).not.toThrow();
  });

  it('passes the ISO value converted to display format as the "value" prop', () => {
    render(<FrDatePicker value="2025-01-15" onChange={() => {}} />);
    expect(capturedProps).not.toBeNull();
    // isoToDisplay('2025-01-15') === '15/01/2025'
    expect(capturedProps!.value).toBe(isoToDisplay('2025-01-15'));
  });

  it('passes an empty string as value when the ISO value is empty', () => {
    render(<FrDatePicker value="" onChange={() => {}} />);
    expect(capturedProps!.value).toBe('');
  });

  it('forwards the id prop to DatePicker', () => {
    render(<FrDatePicker value="2025-01-15" onChange={() => {}} id="test-date" />);
    expect(capturedProps!.id).toBe('test-date');
  });

  it('passes the custom placeholder when provided', () => {
    render(<FrDatePicker value="" onChange={() => {}} placeholder="DD/MM/YYYY" />);
    expect(capturedProps!.placeholder).toBe('DD/MM/YYYY');
  });

  it('uses the default placeholder "jj/mm/aaaa" when none is provided', () => {
    render(<FrDatePicker value="" onChange={() => {}} />);
    expect(capturedProps!.placeholder).toBe('jj/mm/aaaa');
  });

  it('passes isDisabled=true when disabled', () => {
    render(<FrDatePicker value="" onChange={() => {}} isDisabled />);
    expect(capturedProps!.isDisabled).toBe(true);
  });

  it('passes isDisabled=false by default', () => {
    render(<FrDatePicker value="" onChange={() => {}} />);
    expect(capturedProps!.isDisabled).toBe(false);
  });

  it('calls onChange with the correct ISO string when PatternFly fires with a valid Date', () => {
    const handleChange = vi.fn();
    render(<FrDatePicker value="" onChange={handleChange} />);

    // Simulate PatternFly DatePicker calling its onChange with a valid Date
    const testDate = new Date(2025, 0, 15, 12, 0, 0); // Jan 15, 2025 at noon
    capturedProps!.onChange?.(new Event('change'), '15/01/2025', testDate);

    expect(handleChange).toHaveBeenCalledTimes(1);
    expect(handleChange).toHaveBeenCalledWith('2025-01-15');
  });

  it('calls onChange with "" when PatternFly fires with an empty string and no date', () => {
    const handleChange = vi.fn();
    render(<FrDatePicker value="2025-01-15" onChange={handleChange} />);

    capturedProps!.onChange?.(new Event('change'), '', undefined);

    expect(handleChange).toHaveBeenCalledTimes(1);
    expect(handleChange).toHaveBeenCalledWith('');
  });

  it('does not call onChange when PatternFly fires with an invalid Date', () => {
    const handleChange = vi.fn();
    render(<FrDatePicker value="" onChange={handleChange} />);

    const invalidDate = new Date('not-a-date');
    capturedProps!.onChange?.(new Event('change'), 'bad', invalidDate);

    expect(handleChange).not.toHaveBeenCalled();
  });

  it('provides appendTo that returns an HTMLElement', () => {
    render(<FrDatePicker value="" onChange={() => {}} />);
    const appendTo = capturedProps!.appendTo;
    expect(typeof appendTo).toBe('function');
    const el = appendTo?.();
    expect(el).toBeInstanceOf(HTMLElement);
  });

  it('onFocus handler on wrapper div is a no-op when no input child exists (DatePicker renders null)', () => {
    // The current mock renders null for DatePicker, so the wrapper div has no <input> child.
    // onFocus: const input = (e.currentTarget).querySelector('input') → null → if (input) skips.
    const { container } = render(<FrDatePicker value="" onChange={() => {}} />);
    const wrapperDiv = container.firstElementChild as HTMLElement;
    expect(wrapperDiv?.tagName).toBe('DIV');
    // Firing focus should call the onFocus handler. querySelector returns null → no crash.
    expect(() => fireEvent.focus(wrapperDiv)).not.toThrow();
  });

  it('onFocus handler calls input.select() when a child input exists', () => {
    // Temporarily override capturedProps to make DatePicker return a real input
    // We use a different approach: render manually, inject an <input> child, then spy
    const { container } = render(<FrDatePicker value="2025-01-15" onChange={() => {}} />);
    const wrapperDiv = container.firstElementChild as HTMLElement;
    expect(wrapperDiv?.tagName).toBe('DIV');

    // Inject a real <input> child so querySelector('input') finds it
    const fakeInput = document.createElement('input');
    const selectSpy = vi.fn();
    fakeInput.select = selectSpy;
    wrapperDiv.appendChild(fakeInput);

    // Firing focus on the wrapper div invokes the onFocus handler
    fireEvent.focus(wrapperDiv);

    // select() should have been called on the injected input
    expect(selectSpy).toHaveBeenCalled();

    // Cleanup
    wrapperDiv.removeChild(fakeInput);
  });
});

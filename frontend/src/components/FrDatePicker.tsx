// SPDX-License-Identifier: AGPL-3.0-or-later
import { DatePicker } from '@patternfly/react-core';
import { dateFormat, dateParse, isoToDisplay, dateToISO } from './FrDatePicker.utils';

interface FrDatePickerProps {
  value: string;           // ISO format YYYY-MM-DD (internal state)
  onChange: (iso: string) => void;
  id?: string;
  placeholder?: string;
  isDisabled?: boolean;
}

export default function FrDatePicker({
  value,
  onChange,
  id,
  placeholder = 'jj/mm/aaaa',
  isDisabled = false,
}: FrDatePickerProps) {
  return (
    // Wrapper intercepts focus to select all text in the inner <input>,
    // so the user can immediately type a new date without manual selection.
    // React bubbles focus synthetically through the *component* tree, not the
    // real DOM — the calendar popover is a child of DatePicker even though
    // `appendTo={document.body}` portals it elsewhere in the DOM. Every focus
    // move inside that popover (e.g. PatternFly refocusing a day cell after
    // clicking the month-navigation arrows) therefore bubbles up here too.
    // Forcibly calling .select() on the text input then steals focus back
    // from the popover, PatternFly tries to restore it, and the two fight in
    // an infinite focus loop (RangeError: Maximum call stack size exceeded)
    // that crashes the picker closed. Only react when the input itself —
    // not some other focused descendant — is the actual event target.
    <div
      onFocus={(e) => {
        const input = (e.currentTarget as HTMLElement).querySelector('input');
        if (input && e.target === input) input.select();
      }}
    >
      <DatePicker
        id={id}
        value={isoToDisplay(value)}
        dateFormat={dateFormat}
        dateParse={dateParse}
        placeholder={placeholder}
        isDisabled={isDisabled}
        onChange={(_evt, _strVal, date) => {
          if (date && !isNaN(date.getTime())) {
            onChange(dateToISO(date));
          } else if (!_strVal) {
            onChange('');
          }
        }}
        appendTo={() => document.body}
      />
    </div>
  );
}

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
    <div
      onFocus={(e) => {
        const input = (e.currentTarget as HTMLElement).querySelector('input');
        if (input) input.select();
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

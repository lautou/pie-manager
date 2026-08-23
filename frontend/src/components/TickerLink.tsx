// SPDX-License-Identifier: AGPL-3.0-or-later
import { Button } from '@patternfly/react-core';

// Composition data (top holdings / sector weightings) only exists for these instrument
// types — Cash, Or physique, Obligation and Frais tickers render as plain text so clicking
// them never opens an empty modal.
const COMPOSABLE_INSTRUMENT_TYPES = ['ETF', 'SICAV/FCP', 'Action'];

interface TickerLinkProps {
  ticker: string;
  instrumentType?: string | null;
  onClick: (ticker: string) => void;
}

export default function TickerLink({ ticker, instrumentType, onClick }: TickerLinkProps) {
  const isComposable = !!instrumentType && COMPOSABLE_INSTRUMENT_TYPES.includes(instrumentType);

  if (!isComposable) {
    return <>{ticker}</>;
  }

  return (
    <Button variant="link" isInline onClick={() => onClick(ticker)}>
      {ticker}
    </Button>
  );
}

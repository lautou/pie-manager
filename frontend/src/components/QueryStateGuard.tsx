// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from 'react';
import { PageSection, PageSectionVariants, Spinner, Content, ContentVariants } from '@patternfly/react-core';

/**
 * Full-page centered spinner, for the "still loading" branch of a page's data-fetch guard
 * clause. Not every page uses this shape (some keep chrome visible while loading instead) —
 * apply only where the existing early return already renders exactly this markup.
 */
export function renderLoadingState(ariaLabel: string): ReactNode {
  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
        <Spinner size="xl" aria-label={ariaLabel} />
      </div>
    </PageSection>
  );
}

/** Full-page red-text error message, for the "fetch failed" branch of the same guard clause. */
export function renderErrorState(message: string): ReactNode {
  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Content>
        <Content component={ContentVariants.p} style={{ color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
          {message}
        </Content>
      </Content>
    </PageSection>
  );
}

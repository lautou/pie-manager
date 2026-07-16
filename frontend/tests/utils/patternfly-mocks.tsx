/**
 * Centralised PatternFly mock stubs for Vitest tests.
 *
 * Import the objects you need and spread them inside `vi.mock(...)` factory
 * functions.  Pages that need component-specific behaviour (e.g. a Modal that
 * renders data-testid attributes, or a Button that captures its onClick) must
 * override those entries locally — only the generic, pass-through stubs belong
 * here.
 *
 * Usage:
 *   import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';
 *   vi.mock('@patternfly/react-core', () => pfCoreStubs);
 *   vi.mock('@patternfly/react-table', () => pfTableStubs);
 *   vi.mock('@patternfly/react-icons', () => pfIconStubs);
 */
import React from 'react';
import '../../src/i18n'; // ensures initReactI18next runs in each test file's module context

// ---------------------------------------------------------------------------
// Primitive stub helpers
// ---------------------------------------------------------------------------

/** Renders children transparently. */
export const Stub = ({ children }: { children?: React.ReactNode }) => <>{children}</>;

/** Renders children inside a <div> (avoids React fragment nesting issues in some
 *  table contexts where a <div> wrapper is needed). */
export const DivStub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;

// ---------------------------------------------------------------------------
// @patternfly/react-core — generic stubs
// ---------------------------------------------------------------------------

/**
 * Generic stubs for @patternfly/react-core components.
 *
 * These are the lowest-common-denominator implementations shared across most
 * page tests.  Pages that assert on specific props (onClick, isOpen, etc.)
 * should spread these and override individual components.
 */
export const pfCoreStubs = {
  // Layout
  Card: DivStub,
  CardBody: DivStub,
  CardTitle: DivStub,
  Grid: Stub,
  GridItem: Stub,
  Gallery: Stub,
  GalleryItem: Stub,
  PageSection: Stub,
  PageSectionVariants: { default: 'default' },
  PageSidebar: ({ children, isSidebarOpen }: any) => (
    <div data-testid="sidebar" data-open={String(isSidebarOpen)}>{children}</div>
  ),
  PageSidebarBody: Stub,

  // Typography
  Text: ({ children }: any) => <span>{children}</span>,
  TextContent: Stub,
  TextVariants: { p: 'p', h1: 'h1', h2: 'h2', small: 'small' },
  Title: ({ children }: any) => <h1>{children}</h1>,

  // Feedback
  Spinner: () => <div data-testid="spinner" />,
  Badge: ({ children }: any) => <span>{children}</span>,
  Label: ({ children, color }: any) => <span data-testid="label" data-color={color}>{children}</span>,

  // Tooltip — pass-through, renders children directly
  Tooltip: ({ children }: any) => <>{children}</>,

  // Modal — generic stub that renders nothing (pages needing modal assertions override this)
  Modal: ({ children, isOpen }: any) => (isOpen ? <div data-testid="modal">{children}</div> : null),
  ModalVariant: { medium: 'medium', large: 'large', small: 'small' },

  // Form
  Alert: ({ title, variant, children }: any) => (
    <div data-testid={`alert-${variant}`} role="alert">
      <span>{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick, isLoading, isDisabled }: any) => (
    <button onClick={onClick} disabled={isDisabled} data-loading={String(!!isLoading)}>
      {children}
    </button>
  ),
  FormGroup: ({ children, label }: any) => (
    <div>
      <label>{label}</label>
      {children}
    </div>
  ),
  FormSelect: ({ children, value, onChange, 'aria-label': ariaLabel }: any) => (
    <select aria-label={ariaLabel} value={value} onChange={(e: any) => onChange?.(e, e.target.value)}>
      {children}
    </select>
  ),
  FormSelectOption: ({ value, label, isDisabled }: any) => (
    <option value={value} disabled={isDisabled}>{label}</option>
  ),
  NumberInput: ({ value, onMinus, onPlus, onChange, min, isDisabled }: any) => (
    <div>
      <button onClick={onMinus} disabled={isDisabled}>-</button>
      <input type="number" value={value} min={min} onChange={onChange} disabled={isDisabled} />
      <button onClick={onPlus} disabled={isDisabled}>+</button>
    </div>
  ),
  Switch: ({ id, label, isChecked, onChange }: any) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="checkbox"
        checked={isChecked}
        onChange={(e: any) => onChange?.(e, e.target.checked)}
      />
    </div>
  ),
  Checkbox: ({ id, 'aria-label': ariaLabel, isChecked, isDisabled, onChange }: any) => (
    <input
      id={id}
      type="checkbox"
      aria-label={ariaLabel}
      checked={isChecked}
      disabled={isDisabled}
      onChange={(e: any) => onChange?.(e, e.target.checked)}
    />
  ),
  TextInput: ({ value, onChange, placeholder, validated, 'aria-label': ariaLabel, type, onKeyDown, onPaste }: any) => (
    <input
      type={type || 'text'}
      value={value}
      placeholder={placeholder}
      aria-label={ariaLabel}
      data-validated={validated}
      onChange={(e: any) => onChange?.(e, e.target.value)}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
    />
  ),

  // Navigation
  Nav: Stub,
  NavItem: Stub,
  NavList: Stub,
  NavLink: ({ children, to }: any) => <a href={to}>{children}</a>,

  // Pagination
  Pagination: ({ onSetPage, onPerPageSelect, page }: any) => (
    <div data-testid="pagination">
      <button onClick={() => onSetPage(null, (page ?? 1) + 1)}>Next</button>
      <button onClick={() => onPerPageSelect?.(null, 20)}>Per Page 20</button>
    </div>
  ),

  // Toggle
  ToggleGroup: Stub,
  ToggleGroupItem: ({ text, isSelected, onChange }: any) => (
    <button data-testid={`toggle-${text}`} data-selected={String(isSelected)} onClick={onChange}>
      {text}
    </button>
  ),

  // Tabs
  Tabs: ({ children, activeKey, onSelect }: any) => (
    <div data-testid="tabs" data-active-key={String(activeKey)}>
      {React.Children.map(children, (child: any) =>
        React.cloneElement(child, { onSelect, isActive: child.props.eventKey === activeKey })
      )}
    </div>
  ),
  Tab: ({ children, eventKey, title, onSelect, isActive }: any) => (
    <div data-testid={`tab-${eventKey}`}>
      <button onClick={(e: any) => onSelect?.(e, eventKey)}>{title}</button>
      {isActive && <div data-testid={`tab-panel-${eventKey}`}>{children}</div>}
    </div>
  ),
  TabTitleText: ({ children }: any) => <>{children}</>,

  // Progress
  Progress: ({ value, 'aria-label': ariaLabel }: any) => (
    <div data-testid="progress" aria-label={ariaLabel}>{value}%</div>
  ),
  ProgressMeasureLocation: { outside: 'outside' },

  // Masthead
  Masthead: Stub,
  MastheadBrand: Stub,
  MastheadMain: Stub,
  MastheadToggle: Stub,
  Page: ({ children, sidebar, header }: any) => <div>{header}{sidebar}{children}</div>,
  SkipToContent: () => null,

  // Empty state
  EmptyState: Stub,
  EmptyStateBody: ({ children }: any) => <div>{children}</div>,

  // Misc
  Toolbar: Stub,
  ToolbarContent: Stub,
  ToolbarItem: ({ children }: any) => <div>{children}</div>,
};

// ---------------------------------------------------------------------------
// @patternfly/react-table — generic stubs (identical across all page tests)
// ---------------------------------------------------------------------------

export const pfTableStubs = {
  Table: ({ children, 'aria-label': ariaLabel }: any) => (
    <table aria-label={ariaLabel}>{children}</table>
  ),
  Thead: Stub,
  Tbody: Stub,
  Tr: ({ children, onRowClick, style }: any) => (
    <tr style={style} onClick={onRowClick}>{children}</tr>
  ),
  Th: ({ children }: any) => <th>{children}</th>,
  Td: ({ children, colSpan }: any) => <td colSpan={colSpan}>{children}</td>,
};

// ---------------------------------------------------------------------------
// @patternfly/react-icons — generic stubs
// ---------------------------------------------------------------------------

export const pfIconStubs = {
  BarsIcon: () => null,
  CheckCircleIcon: () => <span>✓</span>,
  DatabaseIcon: () => <span>db</span>,
  DownloadIcon: () => <span>dl</span>,
  ExclamationTriangleIcon: () => <span>!</span>,
  ImportIcon: () => <span>import</span>,
  PencilAltIcon: () => <span>edit</span>,
  PlusCircleIcon: () => <span>+</span>,
  SyncAltIcon: () => <span>sync</span>,
  TrashIcon: () => <span>trash</span>,
  UploadIcon: () => <span>ul</span>,
};

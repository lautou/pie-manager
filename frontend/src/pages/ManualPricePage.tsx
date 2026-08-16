import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  FormGroup,
  Grid,
  GridItem,
  Label,
  PageSection,
  PageSectionVariants,
  Spinner,
  Text,
  TextContent,
  TextVariants,
  Title,
} from '@patternfly/react-core';
import { useParams } from 'react-router-dom';
import { useProducts, usePrices, useCreatePrice, useHoldings } from '../api/queries';
import type { Product } from '../types';
import { localDateStr } from '../utils/format';
import FrDatePicker from '../components/FrDatePicker';

const today = () => localDateStr();

const formatEUR = (val: number, currency = 'EUR') =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency }).format(val);

/** Returns how many calendar days ago `dateStr` (YYYY-MM-DD) is relative to today. */
function priceDaysAgo(dateStr: string): number {
  const priceMs = new Date(dateStr).getTime();
  const todayMs = new Date(today()).getTime();
  return Math.floor((todayMs - priceMs) / (1000 * 60 * 60 * 24));
}

function PriceAgeBadge({ dateStr }: { dateStr: string | null }) {
  const { t } = useTranslation();
  if (!dateStr) {
    return (
      <Label color="red" isCompact>
        {t('manualPrices.noPriceWarning')}
      </Label>
    );
  }
  const days = priceDaysAgo(dateStr);
  if (days <= 7) {
    return (
      <Label color="green" isCompact>
        {t('manualPrices.updatedDaysAgo', { days })}
      </Label>
    );
  }
  if (days <= 30) {
    return (
      <Label color="orange" isCompact>
        {t('manualPrices.updatedDaysAgo', { days })}
      </Label>
    );
  }
  return (
    <Label color="red" isCompact>
      {t('manualPrices.daysWithoutUpdate', { days })}
    </Label>
  );
}

// ─── Per-product form card ────────────────────────────────────────────────────

interface ProductCardProps {
  product: Product;
}

function ProductCard({ product }: ProductCardProps) {
  const { t } = useTranslation();
  const { data: prices, isLoading: pricesLoading } = usePrices(product.ticker);
  const createPrice = useCreatePrice();

  const [date, setDate] = useState<string>(today());
  const [price, setPrice] = useState<number>(0);
  const [successVisible, setSuccessVisible] = useState(false);

  // Pre-fill price with the latest known value when prices load
  useEffect(() => {
    if (prices && prices.length > 0) {
      setPrice(prices[0].price);
    }
  }, [prices]);

  const latestPrice = prices && prices.length > 0 ? prices[0] : null;
  const currency = product.currency || 'EUR';

  const handleSave = async () => {
    try {
      await createPrice.mutateAsync({
        ticker: product.ticker,
        date,
        price,
        currency,
        source: 'manual',
      });
      setSuccessVisible(true);
      setTimeout(() => setSuccessVisible(false), 3000);
    } catch {
      // Error handling is left to the mutation's built-in error state
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {product.name}
            <Badge isRead>{product.ticker}</Badge>
          </div>
        </CardTitle>
      </CardHeader>
      <CardBody>
        {/* Last known price */}
        <div style={{ marginBottom: '1rem' }}>
          {pricesLoading ? (
            <Spinner size="sm" aria-label={t('common.loading')} />
          ) : latestPrice ? (
            <TextContent>
              <Text component={TextVariants.p}>
                <strong>{t('manualPrices.lastKnownPrice')}</strong>{' '}
                {formatEUR(latestPrice.price, latestPrice.currency)}{' '}
                <span style={{ color: 'var(--pf-v5-global--Color--200)', fontSize: '0.85rem' }}>
                  ({latestPrice.date})
                </span>
                {' '}
                <PriceAgeBadge dateStr={latestPrice.date} />
              </Text>
            </TextContent>
          ) : (
            <TextContent>
              <Text
                component={TextVariants.p}
                style={{ color: 'var(--pf-v5-global--Color--200)', fontStyle: 'italic' }}
              >
                {t('manualPrices.noPriceRecorded')}{' '}
                <PriceAgeBadge dateStr={null} />
              </Text>
            </TextContent>
          )}
        </div>

        {/* Entry form */}
        <Grid hasGutter>
          <GridItem span={6}>
            <FormGroup label={t('common.date')} fieldId={`date-${product.ticker}`}>
              <FrDatePicker
                id={`date-${product.ticker}`}
                value={date}
                onChange={(iso) => setDate(iso)}
              />
            </FormGroup>
          </GridItem>

          <GridItem span={3}>
            <FormGroup
              label={t('manualPrices.priceLabel', { currency })}
              fieldId={`price-${product.ticker}`}
            >
              <input
                id={`price-${product.ticker}`}
                type="number"
                min={0}
                step={0.0001}
                value={price || ''}
                onFocus={(e) => e.target.select()}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  if (!isNaN(val)) setPrice(val);
                  else setPrice(0);
                }}
                style={{ width: '100%', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
              />
            </FormGroup>
          </GridItem>

          <GridItem span={12}>
            <Button
              variant="primary"
              onClick={handleSave}
              isDisabled={createPrice.isPending || price <= 0 || !date}
              isLoading={createPrice.isPending}
            >
              {createPrice.isPending ? (
                <>
                  <Spinner size="sm" aria-label={t('common.saving')} />
                  &nbsp;{t('common.saving')}
                </>
              ) : (
                t('common.save')
              )}
            </Button>
          </GridItem>

          {createPrice.isError && (
            <GridItem span={12}>
              <Alert
                variant="danger"
                isInline
                title={t('error.saveFailed')}
              />
            </GridItem>
          )}

          {successVisible && (
            <GridItem span={12}>
              <Alert variant="success" isInline title={t('manualPrices.savedSuccess')} />
            </GridItem>
          )}
        </Grid>
      </CardBody>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ManualPricePage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const { data: products, isLoading: productsLoading, isError } = useProducts();
  const { data: holdings, isLoading: holdingsLoading } = useHoldings(portfolioId);
  const isLoading = productsLoading || holdingsLoading;

  // Scope to this portfolio's actual holdings (issue #75) — the global product catalog has
  // exactly one OR.PHYSIQUE row shared across every portfolio, so filtering it alone showed
  // this screen for every portfolio regardless of whether it ever held physical gold.
  const heldTickers = new Set((holdings ?? []).map((h) => h.ticker));
  const manualProducts: Product[] = (products ?? []).filter(
    (p) => p.instrument_type === 'Or physique' && heldTickers.has(p.ticker),
  );

  if (isLoading) {
    return (
      <PageSection variant={PageSectionVariants.default}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" aria-label={t('common.loading')} />
        </div>
      </PageSection>
    );
  }

  if (isError) {
    return (
      <PageSection variant={PageSectionVariants.default}>
        <Alert variant="danger" isInline title={t('error.loadingPrices')} />
      </PageSection>
    );
  }

  return (
    <PageSection variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '0.5rem' }}>
        {t('manualPrices.title')}
      </Title>

      <TextContent style={{ marginBottom: '1.5rem' }}>
        <Text component={TextVariants.p}>
          {t('manualPrices.description')}
        </Text>
      </TextContent>

      {manualProducts.length === 0 ? (
        <TextContent>
          <Text
            component={TextVariants.p}
            style={{ color: 'var(--pf-v5-global--Color--200)', fontStyle: 'italic' }}
          >
            {t('configGenerale.noManualProducts')}
          </Text>
        </TextContent>
      ) : (
        <Grid hasGutter>
          {manualProducts.map((product) => (
            <GridItem key={product.ticker} span={6}>
              <ProductCard product={product} />
            </GridItem>
          ))}
        </Grid>
      )}
    </PageSection>
  );
}

import { useQueryClient, useIsFetching } from '@tanstack/react-query';
import { Button } from '@patternfly/react-core';
import { SyncAltIcon } from '@patternfly/react-icons';
import { REFRESH_KEYS } from '../hooks/useAutoRefresh';
import apiClient from '../api/client';

export default function RefreshButton() {
  const qc = useQueryClient();
  const isFetching = useIsFetching();

  const handleRefresh = async () => {
    try {
      await apiClient.post('/api/admin/refresh-prices');
    } catch { /* non-blocking */ }
    REFRESH_KEYS.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
  };

  return (
    <Button
      variant="secondary"
      icon={<SyncAltIcon />}
      isDisabled={!!isFetching}
      isLoading={!!isFetching}
      onClick={handleRefresh}
      size="sm"
    >
      Actualiser
    </Button>
  );
}

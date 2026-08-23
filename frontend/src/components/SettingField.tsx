// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSetSystemSetting, useSystemSetting } from '../api/queries';

/** A single SystemSetting-backed labeled input + save button. Seeds its initial value from
 * `defaultValue` until a saved override exists, matching the pattern already established by
 * GlobalConfigPage's "Taux TTF" card. */
export default function SettingField({ settingKey, label, defaultValue, type = 'text' }: {
  settingKey: string; label: string; defaultValue: string; type?: 'text' | 'number';
}) {
  const { t } = useTranslation();
  const { data: setting } = useSystemSetting(settingKey);
  const setSetting = useSetSystemSetting();
  const [value, setValue] = useState(defaultValue);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (setting?.value) setValue(setting.value);
  }, [setting]);

  const save = async () => {
    await setSetting.mutateAsync({ key: settingKey, value });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
      <label style={{ minWidth: 220, fontSize: '0.9rem' }}>{label}</label>
      <input
        type={type}
        value={value}
        aria-label={label}
        onFocus={(e) => e.target.select()}
        onChange={(e) => setValue(e.target.value)}
        style={{ width: 140, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
      />
      <button
        onClick={save}
        disabled={setSetting.isPending}
        style={{
          padding: '6px 16px', background: '#0066CC', color: 'white', border: 'none',
          borderRadius: 4, cursor: 'pointer', fontSize: '0.85rem',
        }}
      >
        {setSetting.isPending ? `${t('common.save')}…` : saved ? `✓ ${t('common.save')}` : t('common.save')}
      </button>
    </div>
  );
}

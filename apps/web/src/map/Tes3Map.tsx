import type { DatasetManifest } from '@morrowind-map/contracts';
import type { MapUrlState } from '../navigation/mapUrlState';
import { DatasetMap } from './DatasetMap';

interface Tes3MapProps {
  readonly dataset: DatasetManifest;
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly navigationState: MapUrlState;
  readonly navigationRevision: number;
  readonly onNavigationChange: (state: MapUrlState, mode: 'push' | 'replace') => void;
  readonly onBack: () => void;
}

export function Tes3Map({
  dataset,
  datasetSnapshots,
  navigationState,
  navigationRevision,
  onNavigationChange,
  onBack,
}: Tes3MapProps) {
  return (
    <DatasetMap
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      navigationState={navigationState}
      navigationRevision={navigationRevision}
      onNavigationChange={onNavigationChange}
      onBack={onBack}
    />
  );
}

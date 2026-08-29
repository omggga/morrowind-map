import type { DatasetManifest } from '@morrowind-map/contracts';
import { DatasetMap } from './DatasetMap';

interface Tes3MapProps {
  readonly dataset: DatasetManifest;
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly onBack: () => void;
}

export function Tes3Map({ dataset, datasetSnapshots, onBack }: Tes3MapProps) {
  return (
    <DatasetMap
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      onBack={onBack}
    />
  );
}

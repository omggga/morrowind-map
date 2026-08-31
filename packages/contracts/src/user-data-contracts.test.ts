import { describe, expect, it } from "vitest";

import { ContractValidationError, parsePortableBackup } from "./validation";

const datasetId = "original-goty-hd";
const snapshotId = "original:goty-hd:fixture";
const placeId = "original-goty-hd.vvardenfell.balmora";

function portableBackupFixture() {
  return {
    schemaVersion: 3,
    kind: "morrowind-map-backup",
    exportedAt: "2026-08-31T12:01:00.000Z",
    datasets: { [datasetId]: snapshotId },
    progress: [
      {
        datasetId,
        placeId,
        status: "active",
        note: "Return after joining a Great House",
        updatedAt: "2026-08-31T12:00:00.000Z",
        provenance: { kind: "manual", sourceFingerprint: null },
      },
    ],
    customMarkers: [],
  };
}

describe("portable user-data backup contract", () => {
  it("accepts an EN-era manual-only portable backup", () => {
    const backup = parsePortableBackup(portableBackupFixture());

    expect(backup.schemaVersion).toBe(3);
    expect(backup.progress[0]?.status).toBe("active");
  });

  it("rejects duplicate progress identities", () => {
    const input = portableBackupFixture();
    input.progress.push({ ...input.progress[0]! });

    expect(() => parsePortableBackup(input)).toThrow(ContractValidationError);
  });

  it("preserves marker tombstones and rejects timestamps in reverse order", () => {
    const marker = {
      id: "original-goty-hd.custom.fixture",
      datasetId,
      label: "Return point",
      note: "",
      position: [10, 20],
      createdAt: "2026-08-31T12:00:00.000Z",
      updatedAt: "2026-08-31T12:02:00.000Z",
      deletedAt: "2026-08-31T12:02:00.000Z",
      provenance: { kind: "manual", sourceFingerprint: null },
    };
    const input = {
      ...portableBackupFixture(),
      progress: [],
      customMarkers: [marker],
    };

    expect(parsePortableBackup(input).customMarkers[0]?.deletedAt).toBe(marker.deletedAt);
    expect(() =>
      parsePortableBackup({
        ...input,
        customMarkers: [
          { ...marker, createdAt: "2026-08-31T12:04:00.000Z" },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("rejects deprecated MIM provenance and import receipts", () => {
    const withMimProvenance = portableBackupFixture() as unknown as {
      progress: Array<{ provenance: { kind: string; sourceFingerprint: string | null } }>;
    };
    withMimProvenance.progress[0]!.provenance = {
      kind: "mim-import",
      sourceFingerprint: "a".repeat(64),
    };
    expect(() => parsePortableBackup(withMimProvenance)).toThrow(
      ContractValidationError,
    );

    expect(() =>
      parsePortableBackup({
        ...portableBackupFixture(),
        importReceipts: [],
      }),
    ).toThrow(ContractValidationError);
  });

  it("does not normalize legacy portable backups", () => {
    expect(() =>
      parsePortableBackup({
        ...portableBackupFixture(),
        schemaVersion: 2,
        importReceipts: [],
      }),
    ).toThrow(ContractValidationError);
  });
});

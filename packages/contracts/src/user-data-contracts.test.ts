import { describe, expect, it } from "vitest";

import {
  ContractValidationError,
  parseMimImportBundle,
  parsePortableBackup,
} from "./validation";
import { createMimImportReceiptId } from "./import-receipt";

const datasetId = "original-goty";
const snapshotId = "original:goty:fixture";
const placeId = "original-goty.vvardenfell.mim-0000";
const fingerprint = "a".repeat(64);

describe("user data contracts", () => {
  it("accepts a duplicate-safe MIM progress snapshot", () => {
    const bundle = parseMimImportBundle({
      schemaVersion: 1,
      kind: "mim-progress",
      targetDatasetId: datasetId,
      targetSnapshotId: snapshotId,
      sourceFingerprint: fingerprint,
      sourceFiles: [
        {
          path: "mim_morrowind/user.gdb",
          sha256: "b".repeat(64),
        },
      ],
      progress: [{ placeId, status: "visited", note: "" }],
      customMarkers: [
        {
          id: "original-goty.custom.mim-0000",
          label: "Дом с силовым полем",
          note: "",
          position: [59_590, 184_171],
        },
      ],
    });

    expect(bundle.progress[0]?.placeId).toBe(placeId);
    expect(bundle.customMarkers[0]?.position).toEqual([59_590, 184_171]);
  });

  it("accepts a portable backup and rejects duplicate record identities", () => {
    const progress = {
      datasetId,
      placeId,
      status: "active",
      note: "Вернуться позже",
      updatedAt: "2026-08-26T20:00:00.000Z",
      provenance: { kind: "manual", sourceFingerprint: null },
    };
    const backup = parsePortableBackup({
      schemaVersion: 2,
      kind: "morrowind-map-backup",
      exportedAt: "2026-08-26T20:01:00.000Z",
      datasets: { [datasetId]: snapshotId },
      progress: [progress],
      customMarkers: [],
      importReceipts: [],
    });

    expect(backup.progress[0]?.status).toBe("active");
    expect(() =>
      parsePortableBackup({ ...backup, progress: [progress, progress] }),
    ).toThrow(ContractValidationError);
  });

  it("preserves marker tombstones and rejects timestamps in reverse order", () => {
    const marker = {
      id: "original-goty.custom.fixture",
      datasetId,
      label: "Моя отметка",
      note: "",
      position: [10, 20],
      createdAt: "2026-08-26T20:00:00.000Z",
      updatedAt: "2026-08-26T20:02:00.000Z",
      deletedAt: "2026-08-26T20:02:00.000Z",
      provenance: { kind: "manual", sourceFingerprint: null },
    };
    const input = {
      schemaVersion: 2,
      kind: "morrowind-map-backup",
      exportedAt: "2026-08-26T20:03:00.000Z",
      datasets: { [datasetId]: snapshotId },
      progress: [],
      customMarkers: [marker],
      importReceipts: [],
    };

    expect(parsePortableBackup(input).customMarkers[0]?.deletedAt).toBe(marker.deletedAt);
    expect(() =>
      parsePortableBackup({
        ...input,
        customMarkers: [
          { ...marker, createdAt: "2026-08-26T20:04:00.000Z" },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("requires the canonical receipt id for its dataset and fingerprint", () => {
    const receiptId = createMimImportReceiptId(datasetId, fingerprint);
    const backup = {
      schemaVersion: 2,
      kind: "morrowind-map-backup",
      exportedAt: "2026-08-26T20:03:00.000Z",
      datasets: { [datasetId]: snapshotId },
      progress: [],
      customMarkers: [],
      importReceipts: [
        {
          id: receiptId,
          datasetId,
          sourceKind: "mim",
          sourceFingerprint: fingerprint,
          importedAt: "2026-08-26T20:02:00.000Z",
        },
      ],
    };

    expect(receiptId).toBe(
      `mim:1d5aa4d3cdbd7185c5fdf48fa80f871c:${fingerprint}`,
    );
    expect(parsePortableBackup(backup).importReceipts[0]?.id).toBe(receiptId);
    expect(() =>
      parsePortableBackup({
        ...backup,
        importReceipts: [
          {
            ...backup.importReceipts[0],
            id: createMimImportReceiptId("another-dataset", fingerprint),
          },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("keeps canonical receipt ids bounded for maximum-length dataset ids", () => {
    const maximumDatasetId = "a".repeat(160);
    const receiptId = createMimImportReceiptId(maximumDatasetId, fingerprint);
    const backup = parsePortableBackup({
      schemaVersion: 2,
      kind: "morrowind-map-backup",
      exportedAt: "2026-08-26T20:03:00.000Z",
      datasets: { [maximumDatasetId]: snapshotId },
      progress: [],
      customMarkers: [],
      importReceipts: [
        {
          id: receiptId,
          datasetId: maximumDatasetId,
          sourceKind: "mim",
          sourceFingerprint: fingerprint,
          importedAt: "2026-08-26T20:02:00.000Z",
        },
      ],
    });

    expect(receiptId).toHaveLength(101);
    expect(backup.importReceipts[0]?.id).toBe(receiptId);
  });

  it("normalizes a strictly related legacy v1 receipt into v2", () => {
    const legacyReceiptId = `mim:${datasetId}:${fingerprint}`;
    const backup = parsePortableBackup({
      schemaVersion: 1,
      kind: "morrowind-map-backup",
      exportedAt: "2026-08-26T20:03:00.000Z",
      datasets: { [datasetId]: snapshotId },
      progress: [],
      customMarkers: [],
      importReceipts: [
        {
          id: legacyReceiptId,
          datasetId,
          sourceKind: "mim",
          sourceFingerprint: fingerprint,
          importedAt: "2026-08-26T20:02:00.000Z",
        },
      ],
    });

    expect(backup.schemaVersion).toBe(2);
    expect(backup.importReceipts[0]?.id).toBe(
      createMimImportReceiptId(datasetId, fingerprint),
    );
  });

  it.each([
    `mim:another-dataset:${fingerprint}`,
    `mim:${datasetId}:${"b".repeat(64)}`,
    createMimImportReceiptId(datasetId, fingerprint),
    "arbitrary-receipt-id",
  ])("rejects a foreign or non-legacy receipt id in v1: %s", (receiptId) => {
    expect(() =>
      parsePortableBackup({
        schemaVersion: 1,
        kind: "morrowind-map-backup",
        exportedAt: "2026-08-26T20:03:00.000Z",
        datasets: { [datasetId]: snapshotId },
        progress: [],
        customMarkers: [],
        importReceipts: [
          {
            id: receiptId,
            datasetId,
            sourceKind: "mim",
            sourceFingerprint: fingerprint,
            importedAt: "2026-08-26T20:02:00.000Z",
          },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("keeps v2 strict and rejects legacy receipt ids", () => {
    expect(() =>
      parsePortableBackup({
        schemaVersion: 2,
        kind: "morrowind-map-backup",
        exportedAt: "2026-08-26T20:03:00.000Z",
        datasets: { [datasetId]: snapshotId },
        progress: [],
        customMarkers: [],
        importReceipts: [
          {
            id: `mim:${datasetId}:${fingerprint}`,
            datasetId,
            sourceKind: "mim",
            sourceFingerprint: fingerprint,
            importedAt: "2026-08-26T20:02:00.000Z",
          },
        ],
      }),
    ).toThrow(ContractValidationError);
  });
});

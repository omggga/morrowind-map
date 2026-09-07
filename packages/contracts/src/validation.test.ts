import { describe, expect, it } from "vitest";

import datasetIndexFixture from "../../../apps/web/public/datasets/index.json";
import originalFixture from "../../../apps/web/public/datasets/manifests/original-goty-hd.json";
import poisonSongFixture from "../../../apps/web/public/datasets/manifests/poison-song-26.08.json";
import cyrodiilFixture from "../../../apps/web/public/datasets/manifests/abecean-shores-25.05a.json";
import homeOfNordsFixture from "../../../apps/web/public/datasets/manifests/dragonstar-25.05.json";
import {
  ContractValidationError,
  getDatasetIndexValidationIssues,
  getDatasetManifestValidationIssues,
  parseDatasetIndex,
  parseDatasetManifest,
} from "./validation";

const manifestsByDatasetId: Readonly<Record<string, unknown>> = {
  "original-goty-hd": originalFixture,
  "poison-song-26.08": poisonSongFixture,
  "abecean-shores-25.05a": cyrodiilFixture,
  "dragonstar-25.05": homeOfNordsFixture,
};

describe("public dataset fixtures", () => {
  it("validates the index and all four referenced manifests", () => {
    const index = parseDatasetIndex(datasetIndexFixture);

    expect(index.datasets).toHaveLength(4);
    for (const entry of index.datasets) {
      const manifest = parseDatasetManifest(manifestsByDatasetId[entry.datasetId]);
      expect(manifest.datasetId).toBe(entry.datasetId);
      expect(entry.manifestUrl).toBe(`/datasets/manifests/${entry.datasetId}.json`);
      expect(manifest.map.projection.code).toBe("TES3:WORLD");
      expect(manifest.map.projection.cellSize).toBe(8192);
    }
  });

  it("publishes Original HD with pinned basemap and English catalog artifacts", () => {
    const manifest = parseDatasetManifest(originalFixture);
    const catalogInventory =
      "6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1";
    const basemapInventory =
      "aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014";

    expect(manifest.datasetId).toBe("original-goty-hd");
    expect(manifest.readiness).toMatchObject({
      status: "ready",
      exactProfile: true,
      blockers: [],
      warnings: [],
    });
    expect(manifest.profile.status).toBe("confirmed");
    expect(manifest.localization).toMatchObject({
      defaultLocale: "en",
      locales: [{ locale: "en", status: "available", coverage: 1 }],
    });
    expect(manifest.provenance.kind).toBe("generated");
    expect(manifest.artifacts.tiles).toEqual({
      manifestUrl: `/datasets/metadata/original-goty-hd/${basemapInventory}/map-assets.json`,
      sha256: "aee6af3f16a0fcd739d87702991b52a72d1022299dd038dab7f370c2ac4071e7",
    });
    expect(manifest.artifacts.locations).toEqual({
      url: `/datasets/generated/original-goty-hd/catalogs/${catalogInventory}/locations.json`,
      mediaType: "application/json",
      sha256: "2f1711b8eb7cea50a7f37fc3b3042ab188268c49bab2f356f1d452c286ca869b",
      bytes: 522768,
    });
    expect(manifest.artifacts.locales).toEqual([
      {
        locale: "en",
        artifact: {
          url: `/datasets/generated/original-goty-hd/catalogs/${catalogInventory}/locales/en.json`,
          mediaType: "application/json",
          sha256: "5e75464dbf6db5c9a4f668ba7defc3306d14c9d120efb98a65a1767b0fa184df",
          bytes: 107432,
        },
      },
    ]);
    expect(manifest.artifacts.catalogAudit).toEqual({
      url: `/datasets/metadata/original-goty-hd/catalogs/${catalogInventory}/catalog-audit.json`,
      mediaType: "application/json",
      sha256: "46312ba10205a32b47cec07e7d609234646925a7c8ebe9ba0ecb6afb988ab207",
      bytes: 7907,
    });
  });

  it("pins Original HD to the isolated English GOTY ESM/BSA profile", () => {
    const expectIsolationIssue = (value: unknown) => {
      const issues = getDatasetManifestValidationIssues(value);
      expect(
        issues.some(
          ({ instancePath, message }) =>
            instancePath === "/profile" && message.includes("isolated Original GOTY profile"),
        ),
      ).toBe(true);
    };
    const extraContent = structuredClone(originalFixture);
    extraContent.profile.contentFiles.push({
      name: "Tamriel_Data.esm",
      kind: "esm",
      version: null,
      sha256: "e94ca3a5c62e0228ac3782e813cae58c4e10da2e9e8b7611e0a8f5ff9a98d06f",
      loadOrder: 3,
      inclusion: "required",
      enabled: true,
    });

    const extraArchive = structuredClone(originalFixture);
    extraArchive.profile.registeredArchives.push({
      name: "Tamriel_Data.bsa",
      sha256: "a".repeat(64),
      order: 3,
      required: true,
      registered: true,
    });

    const extraDirectory = structuredClone(originalFixture);
    extraDirectory.profile.dataDirectories.push({
      id: "tamriel-data",
      order: 1,
      status: "confirmed",
    });

    for (const invalid of [extraContent, extraArchive, extraDirectory]) {
      expectIsolationIssue(invalid);
    }

    const changedEsmHash = structuredClone(originalFixture);
    changedEsmHash.profile.contentFiles[0]!.sha256 = "b".repeat(64);
    const changedEsmOrder = structuredClone(originalFixture);
    changedEsmOrder.profile.contentFiles[1]!.loadOrder = 2;
    const changedBsaHash = structuredClone(originalFixture);
    changedBsaHash.profile.registeredArchives[0]!.sha256 = "c".repeat(64);
    const changedBsaOrder = structuredClone(originalFixture);
    changedBsaOrder.profile.registeredArchives[2]!.order = 1;
    const changedDirectory = structuredClone(originalFixture);
    changedDirectory.profile.dataDirectories[0]!.id = "base-and-mods";

    for (const invalid of [
      changedEsmHash,
      changedEsmOrder,
      changedBsaHash,
      changedBsaOrder,
      changedDirectory,
    ]) {
      expectIsolationIssue(invalid);
    }
  });

  it("publishes the current Tamriel Rebuilt release as the shared TR map family", () => {
    const manifest = parseDatasetManifest(poisonSongFixture);
    const catalogInventory =
      "3acf616265926d55c254c961e256cc4ab71aaba23f4dc18d9d368813f0490d3a";
    const basemapInventory =
      "93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2";

    expect(manifest.localization.locales.map(({ locale }) => locale)).toEqual(["en"]);
    expect(manifest.localization.locales[0]).toMatchObject({
      status: "available",
      coverage: 1,
    });
    expect(manifest.datasetId).toBe("poison-song-26.08");
    expect(manifest.mapKey).toBe("tamriel-rebuilt");
    expect(manifest.readiness).toMatchObject({
      status: "ready",
      exactProfile: true,
      blockers: [],
      warnings: [],
    });
    expect(manifest.provenance.kind).toBe("generated");
    expect(manifest.artifacts.tiles).toEqual({
      manifestUrl: `/datasets/metadata/poison-song-26.08/${basemapInventory}/map-assets.json`,
      sha256: "b6e8c18b3986b99267eab9f3509a331865e77da978b8652e99054f5c48003de9",
    });
    expect(manifest.artifacts.locations).toEqual({
      url: `/datasets/generated/poison-song-26.08/catalogs/${catalogInventory}/locations.json`,
      mediaType: "application/json",
      sha256: "6990d34252d988cdaec08ee040bd40c2a1169570cfefdf44564eb3f0c185c479",
      bytes: 2_118_003,
    });
    expect(manifest.artifacts.locales[0]).toEqual({
      locale: "en",
      artifact: {
        url: `/datasets/generated/poison-song-26.08/catalogs/${catalogInventory}/locales/en.json`,
        mediaType: "application/json",
        sha256: "2c2bd0f33d9b5cef3cfe0f30ca946e07fec6bcf14acf8afb737235aab506ee0b",
        bytes: 430_196,
      },
    });
    expect(manifest.artifacts.catalogAudit).toEqual({
      url: `/datasets/metadata/poison-song-26.08/catalogs/${catalogInventory}/catalog-audit.json`,
      mediaType: "application/json",
      sha256: "082e83f0e8f32e4041736767524bed30010af2ddb3fa1e9e7dd7f0cd47cf078c",
      bytes: 12_890,
    });
  });

  it("rejects the retired release-specific Poison Song map family", () => {
    const invalid = structuredClone(poisonSongFixture);
    invalid.mapKey = "poison-song";

    expect(getDatasetManifestValidationIssues(invalid)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instancePath: "/mapKey", keyword: "enum" }),
      ]),
    );
  });
});

describe("strict schema validation", () => {
  it("rejects unknown manifest properties", () => {
    const invalid = {
      ...structuredClone(originalFixture),
      unexpected: true,
    };

    expect(() => parseDatasetManifest(invalid)).toThrow(ContractValidationError);
    expect(getDatasetManifestValidationIssues(invalid)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ keyword: "additionalProperties", instancePath: "" }),
      ]),
    );
  });

  it("rejects projection constants other than TES3:WORLD and cell size 8192", () => {
    const invalidProjection = structuredClone(originalFixture);
    invalidProjection.map.projection.code = "EPSG:3857";
    invalidProjection.map.projection.cellSize = 4096;

    const issues = getDatasetManifestValidationIssues(invalidProjection);
    expect(issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instancePath: "/map/projection/code", keyword: "const" }),
        expect.objectContaining({ instancePath: "/map/projection/cellSize", keyword: "const" }),
      ]),
    );
  });
});

describe("semantic validation", () => {
  it("rejects a center outside the extent and non-descending resolutions", () => {
    const invalid = structuredClone(originalFixture);
    invalid.map.projection.center = [999999, 999999];
    invalid.map.tileGrid.resolutions = [16, 32];

    const issues = getDatasetManifestValidationIssues(invalid);
    expect(issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instancePath: "/map/projection/center" }),
        expect.objectContaining({ instancePath: "/map/tileGrid/resolutions" }),
      ]),
    );
  });

  it("rejects duplicate index ids and a missing default dataset", () => {
    const invalid = structuredClone(datasetIndexFixture);
    invalid.defaultDatasetId = "missing-dataset";
    invalid.datasets[1] = {
      datasetId: "original-goty-hd",
      manifestUrl: "/datasets/manifests/original-goty-hd.json",
      order: 0,
    };

    const issues = getDatasetIndexValidationIssues(invalid);
    expect(issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instancePath: "/defaultDatasetId" }),
        expect.objectContaining({ instancePath: "/datasets" }),
      ]),
    );
  });

  it("rejects locales and fallback values outside the EN-only contract", () => {
    const invalid = structuredClone(originalFixture) as unknown as {
      localization: {
        defaultLocale: string;
        locales: Array<{
          locale: string;
          status: string;
          coverage: number;
          fallbackLocale: string | null;
        }>;
      };
    };
    invalid.localization.locales.push({
      locale: "fr",
      status: "available",
      coverage: 1,
      fallbackLocale: "en",
    });

    const issues = getDatasetManifestValidationIssues(invalid);
    expect(
      issues.some(
        ({ instancePath, keyword }) => keyword === "maxItems" && instancePath === "/localization/locales",
      ),
    ).toBe(true);
  });
});

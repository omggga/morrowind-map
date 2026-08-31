import { describe, expect, it } from "vitest";

import datasetIndexFixture from "../../../apps/web/public/datasets/index.json";
import originalFixture from "../../../apps/web/public/datasets/manifests/original-goty-hd.json";
import poisonSongFixture from "../../../apps/web/public/datasets/manifests/poison-song-26.08.json";
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
};

describe("public dataset fixtures", () => {
  it("validates the index and exactly two referenced manifests", () => {
    const index = parseDatasetIndex(datasetIndexFixture);

    expect(index.datasets).toHaveLength(2);
    for (const entry of index.datasets) {
      const manifest = parseDatasetManifest(manifestsByDatasetId[entry.datasetId]);
      expect(manifest.datasetId).toBe(entry.datasetId);
      expect(entry.manifestUrl).toBe(`/datasets/manifests/${entry.datasetId}.json`);
      expect(manifest.map.projection.code).toBe("TES3:WORLD");
      expect(manifest.map.projection.cellSize).toBe(8192);
    }
  });

  it("keeps Original HD blocked until its generated artifacts are published", () => {
    const manifest = parseDatasetManifest(originalFixture);

    expect(manifest.datasetId).toBe("original-goty-hd");
    expect(manifest.readiness.status).toBe("blocked");
    expect(manifest.readiness.exactProfile).toBe(true);
    expect(manifest.profile.status).toBe("confirmed");
    expect(manifest.readiness.blockers.length).toBeGreaterThan(0);
    expect(manifest.localization).toMatchObject({
      defaultLocale: "en",
      locales: [{ locale: "en", status: "planned", coverage: 0 }],
    });
    expect(manifest.artifacts).toMatchObject({
      locations: null,
      tiles: null,
      mimImport: null,
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

  it("publishes only English for Poison Song without creating another dataset", () => {
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

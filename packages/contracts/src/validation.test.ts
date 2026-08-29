import { describe, expect, it } from "vitest";

import datasetIndexFixture from "../../../apps/web/public/datasets/index.json";
import fullrestFixture from "../../../apps/web/public/datasets/manifests/fullrest-25.08.json";
import originalFixture from "../../../apps/web/public/datasets/manifests/original-goty.json";
import poisonSongFixture from "../../../apps/web/public/datasets/manifests/poison-song-26.08.json";
import {
  ContractValidationError,
  getDatasetIndexValidationIssues,
  getDatasetManifestValidationIssues,
  parseDatasetIndex,
  parseDatasetManifest,
} from "./validation";

const manifestsByDatasetId: Readonly<Record<string, unknown>> = {
  "original-goty": originalFixture,
  "fullrest-25.08": fullrestFixture,
  "poison-song-26.08": poisonSongFixture,
};

describe("public dataset fixtures", () => {
  it("validates the index and all three referenced manifests", () => {
    const index = parseDatasetIndex(datasetIndexFixture);

    expect(index.datasets).toHaveLength(3);
    for (const entry of index.datasets) {
      const manifest = parseDatasetManifest(manifestsByDatasetId[entry.datasetId]);
      expect(manifest.datasetId).toBe(entry.datasetId);
      expect(entry.manifestUrl).toBe(`/datasets/manifests/${entry.datasetId}.json`);
      expect(manifest.map.projection.code).toBe("TES3:WORLD");
      expect(manifest.map.projection.cellSize).toBe(8192);
    }
  });

  it("keeps Fullrest explicitly blocked and inexact", () => {
    const manifest = parseDatasetManifest(fullrestFixture);

    expect(manifest.readiness.status).toBe("blocked");
    expect(manifest.readiness.exactProfile).toBe(false);
    expect(manifest.profile.status).toBe("unconfirmed");
    expect(manifest.readiness.blockers.length).toBeGreaterThan(0);
  });

  it("publishes only English for Poison Song without creating another dataset", () => {
    const manifest = parseDatasetManifest(poisonSongFixture);
    const catalogInventory =
      "3acf616265926d55c254c961e256cc4ab71aaba23f4dc18d9d368813f0490d3a";

    expect(manifest.localization.locales.map(({ locale }) => locale)).toEqual(["en"]);
    expect(manifest.localization.locales[0]).toMatchObject({
      status: "available",
      coverage: 1,
    });
    expect(manifest.datasetId).toBe("poison-song-26.08");
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
      datasetId: "original-goty",
      manifestUrl: "/datasets/manifests/original-goty.json",
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

  it("rejects cyclic locale fallback chains", () => {
    const invalid = structuredClone(parseDatasetManifest(fullrestFixture));
    const russianLocale = invalid.localization.locales.find(({ locale }) => locale === "ru");
    if (!russianLocale) {
      throw new Error("Fullrest fixture must declare the Russian locale");
    }
    russianLocale.fallbackLocale = "en";

    const issues = getDatasetManifestValidationIssues(invalid);
    expect(
      issues.some(
        ({ instancePath, keyword }) =>
          keyword === "semantic" &&
          /^\/localization\/locales\/\d+\/fallbackLocale$/.test(instancePath),
      ),
    ).toBe(true);
  });
});

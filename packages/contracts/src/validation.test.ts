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

    expect(manifest.localization.locales.map(({ locale }) => locale)).toEqual(["en"]);
    expect(manifest.datasetId).toBe("poison-song-26.08");
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

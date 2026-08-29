import { describe, expect, it } from "vitest";

import {
  ContractValidationError,
  getTileCoverageValidationIssues,
  parseLocationCatalog,
  parseMapAssetsManifest,
  parsePlaceLocaleCatalog,
  parseTileCoverage,
} from "./validation";

const snapshotId = "original:goty:fixture";
const placeId = "original-goty.vvardenfell.mim-0000";

function sparseMapAssetsFixture() {
  return {
    schemaVersion: 1,
    datasetId: "poison-song-26.08",
    snapshotId: "tr:poison-song-26.08:fixture",
    projection: "TES3:WORLD",
    rasters: [],
    tilePyramids: [
      {
        id: "poison-song-26.08.world",
        regionIds: ["vvardenfell", "mainland", "solstheim"],
        kind: "xyz-pyramid",
        urlTemplate:
          "/datasets/generated/poison-song-26.08/fixture/tiles/{z}/{x}/{y}.webp",
        mediaType: "image/webp",
        tileSize: 512,
        extent: [-229_376, -475_136, 409_600, 278_528],
        origin: [-229_376, 278_528],
        resolutions: [2048, 1024, 512],
        minZoom: 0,
        maxZoom: 2,
        sparse: true,
        coverage: {
          url: "/datasets/metadata/poison-song-26.08/tile-coverage.json",
          mediaType: "application/json",
          sha256: "a".repeat(64),
          bytes: 3_000,
        },
        qualityReport: {
          url: "/datasets/metadata/poison-song-26.08/basemap-audit.json",
          mediaType: "application/json",
          sha256: "b".repeat(64),
          bytes: 20_000,
        },
        derivation: {
          kind: "cross-shard-seam-stabilization",
          version: "cross-shard-linear-feather-v1",
          sourceInventorySha256: "5".repeat(64),
          implementationSha256: "6".repeat(64),
          receipt: {
            url: "/datasets/metadata/poison-song-26.08/seam-stabilization.json",
            mediaType: "application/json",
            sha256: "7".repeat(64),
            bytes: 10_000,
          },
        },
        integrity: {
          tileCount: 7,
          totalBytes: 100_000,
          inventorySha256: "c".repeat(64),
          inventoryFileSha256: "d".repeat(64),
          provenanceFingerprint: "e".repeat(64),
          planFingerprint: "f".repeat(64),
          profileFingerprint: "0".repeat(64),
          rendererFingerprint: "1".repeat(64),
          productionSourceFingerprint: "2".repeat(64),
          assetTreeFingerprint: "3".repeat(64),
          inputFingerprint: "4".repeat(64),
        },
      },
    ],
  };
}

function tileCoverageFixture() {
  return {
    schemaVersion: 1,
    datasetId: "poison-song-26.08",
    snapshotId: "tr:poison-song-26.08:fixture",
    tilePyramidId: "poison-song-26.08.world",
    encoding: "x-y-ranges-v1",
    tileCount: 7,
    levels: [
      { z: 0, columns: [{ x: 0, yRanges: [[0, 0]] }] },
      {
        z: 1,
        columns: [
          { x: 0, yRanges: [[0, 1]] },
          { x: 1, yRanges: [[1, 1]] },
        ],
      },
      {
        z: 2,
        columns: [
          { x: 0, yRanges: [[0, 0], [2, 2]] },
          { x: 1, yRanges: [[1, 1]] },
        ],
      },
    ],
  };
}

describe("generated dataset artifact contracts", () => {
  it("accepts a location, locale and static raster vertical slice", () => {
    const locations = parseLocationCatalog({
      schemaVersion: 1,
      datasetId: "original-goty",
      snapshotId,
      places: [
        {
          id: placeId,
          regionId: "vvardenfell",
          type: "settlement",
          mapPosition: [-20_000, -12_000],
          exteriorCell: [-3, -2],
          mimCategory: 19,
          minZoom: 2,
          entrances: [],
          sources: [
            {
              kind: "mim",
              plugin: "mwmain.gdb",
              recordId: null,
              mimIndex: 0,
            },
          ],
        },
      ],
    });
    const locale = parsePlaceLocaleCatalog({
      schemaVersion: 1,
      datasetId: "original-goty",
      snapshotId,
      locale: "ru",
      places: [{ placeId, name: "Балмора", aliases: [] }],
    });
    const assets = parseMapAssetsManifest({
      schemaVersion: 1,
      datasetId: "original-goty",
      snapshotId,
      projection: "TES3:WORLD",
      rasters: [
        {
          id: "original-goty.vvardenfell",
          regionId: "vvardenfell",
          kind: "static-image",
          imageUrl: "/datasets/generated/original-goty/rasters/vvardenfell.jpg",
          mediaType: "image/jpeg",
          pixelSize: [3300, 3800],
          extent: [-196_608, -180_224, 196_608, 229_376],
          sha256: "a".repeat(64),
        },
      ],
    });

    expect(locations.places[0]?.id).toBe(placeId);
    expect(locale.places[0]?.name).toBe("Балмора");
    expect(assets.rasters[0]?.pixelSize).toEqual([3300, 3800]);
  });

  it("rejects duplicate place ids and inverted raster bounds", () => {
    const duplicatePlace = {
      id: placeId,
      regionId: "vvardenfell",
      type: "other",
      mapPosition: [0, 0],
      exteriorCell: [0, 0],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [{ kind: "esm", plugin: "Morrowind.esm", recordId: "1", mimIndex: null }],
    };

    expect(() =>
      parseLocationCatalog({
        schemaVersion: 1,
        datasetId: "original-goty",
        snapshotId,
        places: [duplicatePlace, duplicatePlace],
      }),
    ).toThrow(ContractValidationError);
    expect(() =>
      parseMapAssetsManifest({
        schemaVersion: 1,
        datasetId: "original-goty",
        snapshotId,
        projection: "TES3:WORLD",
        rasters: [
          {
            id: "original-goty.vvardenfell",
            regionId: "vvardenfell",
            kind: "static-image",
            imageUrl: "/datasets/generated/original-goty/rasters/vvardenfell.jpg",
            mediaType: "image/jpeg",
            pixelSize: [3300, 3800],
            extent: [1, 0, -1, 2],
            sha256: "b".repeat(64),
          },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("rejects global entrance collisions, coordinate-cell mismatches and duplicate aliases", () => {
    const entrance = {
      id: "original-goty.entrance-shared",
      coordinate: [100, 200],
      exteriorCell: [0, 0],
      sourcePlugin: "Morrowind.esm",
      sourceRef: "0x00000001",
    };
    const source = {
      kind: "esm",
      plugin: "Morrowind.esm",
      recordId: "Cell",
      mimIndex: null,
    };
    expect(() =>
      parseLocationCatalog({
        schemaVersion: 1,
        datasetId: "original-goty",
        snapshotId,
        places: [
          {
            id: "original-goty.place-a",
            regionId: "vvardenfell",
            type: "other",
            mapPosition: [100, 200],
            exteriorCell: [0, 0],
            mimCategory: null,
            minZoom: 0,
            entrances: [entrance],
            sources: [source],
          },
          {
            id: "original-goty.place-b",
            regionId: "vvardenfell",
            type: "other",
            mapPosition: [100, 200],
            exteriorCell: [1, 0],
            mimCategory: null,
            minZoom: 0,
            entrances: [entrance],
            sources: [source],
          },
        ],
      }),
    ).toThrow(ContractValidationError);
    expect(() =>
      parsePlaceLocaleCatalog({
        schemaVersion: 1,
        datasetId: "original-goty",
        snapshotId,
        locale: "en",
        places: [
          {
            placeId: "original-goty.place-a",
            name: "Balmora",
            aliases: ["BALMORA", "Market", "market"],
          },
        ],
      }),
    ).toThrow(ContractValidationError);
  });

  it("accepts a sparse WebP pyramid and binds its exact coverage", () => {
    const assets = parseMapAssetsManifest(sparseMapAssetsFixture());
    const coverage = parseTileCoverage(tileCoverageFixture(), assets);

    expect(assets.rasters).toEqual([]);
    expect(assets.tilePyramids?.[0]?.mediaType).toBe("image/webp");
    expect(coverage.tileCount).toBe(assets.tilePyramids?.[0]?.integrity.tileCount);
  });

  it("requires at least one raster or tile pyramid", () => {
    const invalid = sparseMapAssetsFixture();
    invalid.tilePyramids = [];

    expect(() => parseMapAssetsManifest(invalid)).toThrow(ContractValidationError);
  });

  it("rejects invalid pyramid grids", () => {
    const invertedExtent = sparseMapAssetsFixture();
    invertedExtent.tilePyramids[0]!.extent = [1, 0, -1, 2];
    expect(() => parseMapAssetsManifest(invertedExtent)).toThrow(ContractValidationError);

    const wrongOrigin = sparseMapAssetsFixture();
    wrongOrigin.tilePyramids[0]!.origin = [0, 0];
    expect(() => parseMapAssetsManifest(wrongOrigin)).toThrow(ContractValidationError);

    const unorderedResolutions = sparseMapAssetsFixture();
    unorderedResolutions.tilePyramids[0]!.resolutions = [2048, 512, 1024];
    expect(() => parseMapAssetsManifest(unorderedResolutions)).toThrow(
      ContractValidationError,
    );
  });

  it("rejects incorrect, unordered and overlapping coverage", () => {
    const incorrectCount = tileCoverageFixture();
    incorrectCount.tileCount = 8;
    expect(() => parseTileCoverage(incorrectCount)).toThrow(ContractValidationError);

    const unorderedLevels = tileCoverageFixture();
    unorderedLevels.levels[1]!.z = 0;
    expect(() => parseTileCoverage(unorderedLevels)).toThrow(ContractValidationError);

    const unorderedColumns = tileCoverageFixture();
    unorderedColumns.levels[1]!.columns[0]!.x = 2;
    expect(() => parseTileCoverage(unorderedColumns)).toThrow(ContractValidationError);

    const overlappingRanges = tileCoverageFixture();
    overlappingRanges.levels[2]!.columns[0]!.yRanges[1] = [0, 2];
    expect(() => parseTileCoverage(overlappingRanges)).toThrow(ContractValidationError);

    const adjacentRanges = tileCoverageFixture();
    adjacentRanges.levels[2]!.columns[0]!.yRanges[1] = [1, 2];
    expect(() => parseTileCoverage(adjacentRanges)).toThrow(ContractValidationError);
  });

  it("checks coverage identity, tile count and zooms against map assets", () => {
    const assets = parseMapAssetsManifest(sparseMapAssetsFixture());
    const invalid = tileCoverageFixture();
    invalid.datasetId = "original-goty";
    invalid.tileCount = 8;
    invalid.levels[2]!.z = 3;

    const paths = getTileCoverageValidationIssues(invalid, assets).map(
      (issue) => issue.instancePath,
    );
    expect(paths).toContain("/datasetId");
    expect(paths).toContain("/tileCount");
    expect(paths).toContain("/levels/2/z");
  });

  it("checks complete coverage levels and coordinates against the pyramid grid", () => {
    const assets = parseMapAssetsManifest(sparseMapAssetsFixture());
    const missingLevel = tileCoverageFixture();
    missingLevel.levels.splice(1, 1);
    missingLevel.tileCount = 4;
    expect(getTileCoverageValidationIssues(missingLevel, assets)).toEqual(
      expect.arrayContaining([expect.objectContaining({ instancePath: "/levels" })]),
    );

    const outsideGrid = tileCoverageFixture();
    outsideGrid.levels[0]!.columns[0]!.x = 1;
    expect(getTileCoverageValidationIssues(outsideGrid, assets)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instancePath: "/levels/0/columns/0/x" }),
      ]),
    );
  });
});

import { describe, expect, it } from "vitest";

import {
  ContractValidationError,
  parseLocationCatalog,
  parseMapAssetsManifest,
  parsePlaceLocaleCatalog,
} from "./validation";

const snapshotId = "original:goty:fixture";
const placeId = "original-goty.vvardenfell.mim-0000";

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
});

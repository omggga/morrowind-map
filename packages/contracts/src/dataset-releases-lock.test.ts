import Ajv from "ajv";
import { describe, expect, it } from "vitest";

import schema from "./schemas/dataset-releases-lock.schema.json";

const validate = new Ajv({ allErrors: true, strict: true }).compile(schema);
const inventorySha256 = "a".repeat(64);

function lockFixture() {
  return {
    schemaVersion: 1,
    repository: "omggga/morrowind-map",
    tileSets: [
      {
        datasetId: "original-goty-hd",
        pyramidId: "original-goty-hd-v1",
        inventorySha256,
        format: "ustar-v1",
        releaseTag: `tiles-v1/original-goty-hd/original-goty-hd-v1/${inventorySha256}`,
        parts: [
          {
            name: "tiles-0001.tar",
            sha256: "b".repeat(64),
            bytes: 10240,
            tileCount: 1,
            unpackedBytes: 1234,
          },
        ],
      },
    ],
  };
}

describe("dataset release transport schema", () => {
  it("accepts one archive per map and independent multipart archives", () => {
    const input = lockFixture();
    expect(validate(input)).toBe(true);
    input.tileSets[0]!.parts.push({
      ...input.tileSets[0]!.parts[0]!,
      name: "tiles-0002.tar",
      sha256: "c".repeat(64),
    });
    expect(validate(input)).toBe(true);
  });

  it("rejects unknown or missing properties at every object level", () => {
    for (const select of [
      (input: ReturnType<typeof lockFixture>) => input,
      (input: ReturnType<typeof lockFixture>) => input.tileSets[0]!,
      (input: ReturnType<typeof lockFixture>) => input.tileSets[0]!.parts[0]!,
    ]) {
      const withExtra = lockFixture();
      Object.assign(select(withExtra), { unexpected: true });
      expect(validate(withExtra)).toBe(false);
      for (const key of Object.keys(select(lockFixture()))) {
        const missing = lockFixture();
        Reflect.deleteProperty(select(missing), key);
        expect(validate(missing), `missing ${key}`).toBe(false);
      }
    }
  });

  it("pins the repository, schema version, and archive format", () => {
    expect(validate({ ...lockFixture(), repository: "other/morrowind-map" })).toBe(false);
    expect(validate({ ...lockFixture(), schemaVersion: 2 })).toBe(false);
    const input = lockFixture();
    input.tileSets[0]!.format = "pax";
    expect(validate(input)).toBe(false);
  });

  it.each(["", "../escape", "UPPER", "a:b", "a_b", "a..b", "a.lock", "a\n", "a".repeat(129)])(
    "rejects unsafe or oversized dataset and pyramid IDs: %j",
    (value) => {
      for (const key of ["datasetId", "pyramidId"] as const) {
        const input = lockFixture();
        input.tileSets[0]![key] = value;
        expect(validate(input)).toBe(false);
      }
    },
  );

  it.each([
    `tiles-v2/original-goty-hd/original-goty-hd-v1/${inventorySha256}`,
    `tiles-v1/../original-goty-hd-v1/${inventorySha256}`,
    `tiles-v1/original.lock/original-goty-hd-v1/${inventorySha256}`,
    `tiles-v1/original-goty-hd/pyramid.lock/${inventorySha256}`,
    `tiles-v1/${"a".repeat(129)}/p/${inventorySha256}`,
    `tiles-v1/d/${"a".repeat(129)}/${inventorySha256}`,
    `tiles-v1/d/p/${inventorySha256}\n`,
    `tiles-v1/d/p/${"A".repeat(64)}`,
    "https://example.com/tiles.tar",
  ])("rejects unsafe or noncanonical tag shapes: %j", (releaseTag) => {
    const input = lockFixture();
    input.tileSets[0]!.releaseTag = releaseTag;
    expect(validate(input)).toBe(false);
  });

  it.each(["A".repeat(64), "a".repeat(63), "a".repeat(65), `${"a".repeat(63)}g`, `${inventorySha256}\n`])(
    "requires lowercase SHA-256 values: %j",
    (value) => {
      const inventory = lockFixture();
      inventory.tileSets[0]!.inventorySha256 = value;
      expect(validate(inventory)).toBe(false);
      const archive = lockFixture();
      archive.tileSets[0]!.parts[0]!.sha256 = value;
      expect(validate(archive)).toBe(false);
    },
  );

  it.each(["tiles-0000.tar", "tiles-1000.tar", "tiles-001.tar", "tiles-0001.tar.gz", "../tiles-0001.tar", "tiles-0001.tar\n"])(
    "rejects invalid archive names: %j",
    (name) => {
      const input = lockFixture();
      input.tileSets[0]!.parts[0]!.name = name;
      expect(validate(input)).toBe(false);
    },
  );

  it("enforces archive byte alignment, the upload limit, and inventory bounds", () => {
    const invalidFields = {
      bytes: [0, 10239, 10241, 2137487360, "10240"],
      tileCount: [0, 1.5, 500001, "1"],
      unpackedBytes: [0, 1.5, 2137483649, "1"],
    };
    for (const [field, values] of Object.entries(invalidFields)) {
      for (const value of values) {
        const input = lockFixture();
        Object.assign(input.tileSets[0]!.parts[0]!, { [field]: value });
        expect(validate(input), `${field}: ${value}`).toBe(false);
      }
    }
    const largest = lockFixture();
    Object.assign(largest.tileSets[0]!.parts[0]!, {
      bytes: 2137477120,
      tileCount: 500000,
      unpackedBytes: 2137483648,
    });
    expect(validate(largest)).toBe(true);
  });

  it("bounds the number of tile sets and parts", () => {
    const input = lockFixture();
    expect(validate({ ...input, tileSets: [] })).toBe(false);
    expect(validate({ ...input, tileSets: Array(101).fill(input.tileSets[0]) })).toBe(false);
    input.tileSets[0]!.parts = [];
    expect(validate(input)).toBe(false);
    input.tileSets[0]!.parts = Array.from({ length: 999 }, (_, index) => ({
      ...lockFixture().tileSets[0]!.parts[0]!,
      name: `tiles-${String(index + 1).padStart(4, "0")}.tar`,
    }));
    expect(validate(input)).toBe(true);
    input.tileSets[0]!.parts.push({ ...input.tileSets[0]!.parts[0]! });
    expect(validate(input)).toBe(false);
  });
});

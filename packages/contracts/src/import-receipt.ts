const FNV1A_128_OFFSET_BASIS = 0x6c62272e07bb014262b821756295c58dn;
const FNV1A_128_PRIME = 0x0000000001000000000000000000013bn;
const UINT128_MASK = (1n << 128n) - 1n;

function fnv1a128(value: string): string {
  let hash = FNV1A_128_OFFSET_BASIS;

  for (const byte of new TextEncoder().encode(value)) {
    hash ^= BigInt(byte);
    hash = (hash * FNV1A_128_PRIME) & UINT128_MASK;
  }

  return hash.toString(16).padStart(32, "0");
}

/**
 * Builds the stable primary key for one MIM import receipt.
 *
 * The dataset component is hashed so a valid 160-character dataset id cannot
 * push the receipt past the shared identifier limit. The complete SHA-256
 * source fingerprint remains in the key so distinct source snapshots retain
 * their full collision resistance.
 */
export function createMimImportReceiptId(
  datasetId: string,
  sourceFingerprint: string,
): string {
  return `mim:${fnv1a128(datasetId)}:${sourceFingerprint}`;
}

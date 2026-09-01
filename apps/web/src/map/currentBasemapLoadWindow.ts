export class CurrentBasemapLoadWindow<Tile extends object> {
  private generation = 0;
  private requestGenerations = new WeakMap<Tile, number>();
  private readonly loadedTiles = new Set<Tile>();

  get loadedCount(): number {
    return this.loadedTiles.size;
  }

  beginViewport(): void {
    this.generation += 1;
    this.loadedTiles.clear();
  }

  start(tile: Tile): void {
    this.requestGenerations.set(tile, this.generation);
  }

  finish(tile: Tile): void {
    if (this.requestGenerations.get(tile) === this.generation) {
      this.loadedTiles.add(tile);
    }
  }

  fail(tile: Tile): void {
    this.loadedTiles.delete(tile);
  }

  reset(): void {
    this.beginViewport();
    this.requestGenerations = new WeakMap<Tile, number>();
  }
}

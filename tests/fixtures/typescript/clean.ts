// A small, healthy module.
export class Counter {
  private count = 0;

  increment(step: number = 1): number {
    this.count += step;
    return this.count;
  }

  reset(): void {
    this.count = 0;
  }
}

export function greet(name: string): string {
  if (!name) {
    return "Hello, stranger";
  }
  return `Hello, ${name}`;
}

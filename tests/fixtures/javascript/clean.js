// A small, healthy module.
export class Counter {
  constructor() {
    this.count = 0;
  }

  increment(step = 1) {
    this.count += step;
    return this.count;
  }

  reset() {
    this.count = 0;
  }
}

export function greet(name) {
  if (!name) {
    return "Hello, stranger";
  }
  return `Hello, ${name}`;
}

export const total = (values) => values.filter((v) => v > 0).reduce((a, b) => a + b, 0);

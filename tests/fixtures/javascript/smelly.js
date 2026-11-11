// Smelly fixture: every smell below is asserted in the tests.
export function process(a, b, c, d, e) {
  let total = 0;
  if ((a && b) || c) {
    for (const item of d) {
      if (item > 0) {
        while (e) {
          if (item % 2 === 0) {
            total += item;
          }
          e -= 1;
        }
      } else if (item < 0) {
        total -= item;
      } else {
        total += 1;
      }
    }
  }
  return total;
}

export function bumpy(x, y) {
  if (x) {
    if (y) {
      x += 1;
    }
  }
  y = x * 2;
  for (let i = 0; i < y; i++) {
    if (i % 3 === 0) {
      x += i;
    }
  }
  return x;
}

function dupOne(values) {
  const result = [];
  for (const v of values) {
    if (v > 10) {
      result.push(v * 2);
    } else {
      result.push(v + 1);
    }
  }
  const count = result.length;
  const first = result[0];
  const last = result[count - 1];
  return first + last;
}

function dupTwo(items) {
  const out = [];
  for (const w of items) {
    if (w > 20) {
      out.push(w * 3);
    } else {
      out.push(w + 5);
    }
  }
  const size = out.length;
  const head = out[0];
  const tail = out[size - 1];
  return head + tail;
}

export class Mixed {
  incA() {
    this.a += 1;
  }

  incB() {
    this.b += this.a;
  }

  incX() {
    this.x += 1;
  }

  incY() {
    this.y += this.x;
  }
}

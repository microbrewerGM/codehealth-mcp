function copied(values) {
  let total = 0;
  for (const v of values) {
    if (v % 2 === 0) {
      total += v * 2;
    } else {
      total -= 1;
    }
  }
  const count = values.length;
  const first = values[0];
  return total + count + first;
}

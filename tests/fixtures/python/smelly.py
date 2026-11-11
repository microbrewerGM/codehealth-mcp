"""Smelly fixture: every smell below is asserted in the tests."""


def process(a, b, c, d, e):
    total = 0
    if a and b or c:
        for item in d:
            if item > 0:
                while e:
                    if item % 2 == 0:
                        total += item
                    e -= 1
            elif item < 0:
                total -= item
            else:
                total += 1
    return total


def bumpy(x, y):
    if x:
        if y:
            x += 1
    y = x * 2
    for i in range(y):
        if i % 3 == 0:
            x += i
    return x


def dup_one(values):
    result = []
    for v in values:
        if v > 10:
            result.append(v * 2)
        else:
            result.append(v + 1)
    count = len(result)
    first = result[0]
    last = result[-1]
    middle = result[count // 2]
    return first + last + middle


def dup_two(items):
    out = []
    for w in items:
        if w > 20:
            out.append(w * 3)
        else:
            out.append(w + 5)
    size = len(out)
    head = out[0]
    tail = out[-1]
    mid = out[size // 2]
    return head + tail + mid


class Mixed:
    def __init__(self):
        self.a = 0
        self.b = 0
        self.x = 0
        self.y = 0

    def inc_a(self):
        self.a += 1

    def inc_b(self):
        self.b += self.a

    def inc_x(self):
        self.x += 1

    def inc_y(self):
        self.y += self.x

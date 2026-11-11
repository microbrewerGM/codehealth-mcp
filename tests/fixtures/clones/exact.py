# Exact copy: CPD reports it, and the token comparison must not report it again.


def first_copy(values):
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


def second_copy(values):
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

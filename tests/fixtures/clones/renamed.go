// Renamed clone: one/two differ only in names and constants (CPD's Go lexer ignores --ignore-identifiers).
package main

func one(values []int) int {
	result := []int{}
	for _, v := range values {
		if v > 10 {
			result = append(result, v*2)
		} else {
			result = append(result, v+1)
		}
	}
	count := len(result)
	first := result[0]
	last := result[count-1]
	return first + last + count
}

func two(items []int) int {
	out := []int{}
	for _, w := range items {
		if w > 20 {
			out = append(out, w*3)
		} else {
			out = append(out, w+5)
		}
	}
	size := len(out)
	head := out[0]
	tail := out[size-1]
	return head + tail + size
}

// Package smelly is a fixture: every smell below is asserted in the tests.
package smelly

type Mixed struct {
	a, b, x, y int
}

func Process(a, b, c bool, d []int, e int) int {
	total := 0
	if a && b || c {
		for _, item := range d {
			if item > 0 {
				for e > 0 {
					if item%2 == 0 {
						total += item
					}
					e--
				}
			} else if item < 0 {
				total -= item
			} else {
				total++
			}
		}
	}
	return total
}

func Bumpy(x, y int) int {
	if x > 0 {
		if y > 0 {
			x++
		}
	}
	y = x * 2
	for i := 0; i < y; i++ {
		if i%3 == 0 {
			x += i
		}
	}
	return x
}

func (m *Mixed) IncA() { m.a++ }

func (m *Mixed) IncB() { m.b += m.a }

func (m *Mixed) IncX() { m.x++ }

func (m *Mixed) IncY() { m.y += m.x }

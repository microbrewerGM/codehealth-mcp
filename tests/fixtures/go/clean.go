// Package clean is a small, healthy module.
package clean

import "fmt"

// Counter counts.
type Counter struct {
	count int
}

// Increment adds step.
func (c *Counter) Increment(step int) int {
	c.count += step
	return c.count
}

// Greet returns a greeting.
func Greet(name string) string {
	if name == "" {
		return "Hello, stranger"
	}
	return fmt.Sprintf("Hello, %s", name)
}

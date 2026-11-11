// A small, healthy component.
type Props = { name: string };

export function Greeting({ name }: Props) {
  return <p className="greeting">Hello, {name}</p>;
}

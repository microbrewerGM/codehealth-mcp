# Third-party notices

codehealth-mcp uses the open-source components below. None is modified or
vendored in this repository: the Python packages are normal dependencies, and
PMD is an optional download (`codehealth install-pmd`, into the per-user data
directory or `CODEHEALTH_PMD_HOME`) that runs as a separate process.

## lizard 1.26.x

- Project: https://github.com/terryyin/lizard (Terry Yin and contributors)
- Use: imported in-process (`lizard_core.file_analyzer.FileAnalyzer`, the
  `nd` and `cognitive` extensions) for per-function metrics.
- Licence: MIT. The package metadata declares `License: MIT` and the shipped
  `LICENSE.txt` is the MIT permission notice:

  > Copyright Terry Yin and other contributors
  >
  > Permission is hereby granted, free of charge, to any person obtaining a
  > copy of this software and associated documentation files (the
  > "Software"), to deal in the Software without restriction, including
  > without limitation the rights to use, copy, modify, merge, publish,
  > distribute, sublicense, and/or sell copies of the Software, and to permit
  > persons to whom the Software is furnished to do so, subject to the
  > following conditions:
  >
  > The above copyright notice and this permission notice shall be included
  > in all copies or substantial portions of the Software.
  >
  > THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
  > OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
  > MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
  > NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
  > DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
  > OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
  > USE OR OTHER DEALINGS IN THE SOFTWARE.

  Note: the `lizard.py` facade module carries an Apache-2.0 header; both
  licences are permissive and compatible with this project's use.

## PMD 7.29.0 (including CPD)

- Project: https://pmd.github.io/ , https://github.com/pmd/pmd
- Use: optional external tool, run as a subprocess (`pmd cpd`, `pmd check`
  with Java design rules). Downloaded from the official GitHub release
  `pmd_releases/7.29.0`, asset `pmd-dist-7.29.0-bin.zip`, SHA-256
  `d27177c185b837fa57f097e482d1253468aa035379c5eb2671fa0a279109b179`
  (the digest GitHub publishes for the asset).
- Licence: "PMD's BSD-style license" (Copyright (c) 2003-2009, InfoEther, LLC;
  BSD conditions plus the DARPA acknowledgement clause: "This product includes
  software developed in part by support from the Defense Advanced Research
  Project Agency (DARPA)"). Parts of the distribution are under the Apache
  License 2.0. The full text ships as `LICENSE` inside the PMD distribution
  (`pmd-bin-7.29.0/LICENSE` after installation); bundled
  third-party jars are listed in its `sbom/` directory.

## defusedxml 0.7.x

- Project: https://github.com/tiran/defusedxml
- Use: safe parsing of CPD XML reports.
- Licence: Python Software Foundation License.

## Other Python dependencies

| package | licence | use |
|---|---|---|
| `mcp` (MCP Python SDK) | MIT | MCP server and client |
| `tree-sitter` | MIT | parser runtime |
| `tree-sitter-language-pack` | MIT OR Apache-2.0 (bundled grammars carry their own permissive licences) | grammars for Python, JS/TS/TSX, Java, Go |
| `platformdirs` | MIT | per-user data directory for PMD |

# Small, required test fixtures

`raw.scadpkg` (about 290 KiB) is the retained native passive-pendulum fixture used
by legacy schema 1.0/1.1 package roundtrip tests. It is source test data, not a
discardable verification result.

`rigid-chain-raw.scadpkg` (about 116 KiB) is a fresh SCA 2.2.5 capture of the
native CAD in `examples/rigid_chain/assembly.py` and `cable.py`. It contains no
attached addon metadata. SHA-256:
`6d45190209f93a829c00f708f8274db9b428703cf031ea02327724b0943fafde`.
The authoritative file hash can be recomputed; test assertions verify complete
package roundtrip invariants rather than relying on this documentation.

To regenerate, copy both CAD scripts to an external output directory and run
`python -I -B -m simplecadapi.cli run <output>/assembly.py --out <output>/raw.scadpkg --no-cache`
using the SCA 2.2.5 modeling environment. The example README gives the complete
physics/USD workflow. Do not write SCA notebook caches into this repository.

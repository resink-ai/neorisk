"""State machines (spec §04): declarations and validation (`spec`), the closed `std`
vocabulary (`helpers`); compilation to generated kernel source follows (D62)."""

# `std` re-exports `machine.helpers`, which imports spec submodules: load `spec` (and so `std`)
# first, so importing `neorisk_simkit.machine.*` before `neorisk_simkit.spec` resolves the cycle.
import neorisk_simkit.spec  # noqa: F401

# rpc

- **Endpoint:** `https://ethereum-rpc.publicnode.com` by default, or `$ETH_RPC_URL` / `--endpoint`.
  No key. Tested 2026-10-24: publicnode works; `eth.llamarpc.com` (525), `cloudflare-eth.com`
  (-32046) and `rpc.ankr.com/eth` (needs a key) did not.
- **Not an archive node:** `eth_getLogs` over more than ~10,000 blocks is refused with "Archive
  requests require a personal token". So nothing historical goes through here.

## Modes

| mode | calls | writes |
| --- | --- | --- |
| `codes` (default) | `eth_getCode(addr, "latest")`, JSON-RPC batches of 50 | `addresses` with `is_contract` |
| `blocks --blocks N` | `eth_getBlockByNumber(n, true)` for the latest N | external `transfers` (status null: receipts not fetched) |

Without `--addresses`, `codes` flags every address in the addresses table plus every transfer
counterparty. Batches are cached by request body, so a rerun of the same list is free.

Note: `is_contract` is "has code now". An address that self-destructed, or a counterfactual
smart wallet not yet deployed, reads as not a contract.

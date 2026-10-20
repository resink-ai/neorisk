# Brief: a layer-1 chain's transaction envelope

**Business.** About 300 wallets send transfers and contract calls. Blocks come every 12 seconds. A transaction is valid only if its nonce is the account's next and the balance covers the maximum fee plus the value. Reverted calls pay gas but move nothing. Wallets sometimes resend a stale nonce, which is dropped.

**Who acts.** Wallets (owners); the chain (one shard) that holds every balance and nonce.

## Rates we know

| # | Fact | Value |
|---|------|-------|
| 1 | Contract calls among transactions | about 35% |
| 2 | Calls that revert | about 10% |
| 3 | Transactions dropped for a stale nonce | about 2% |
